"""Validate banking-v2 locally, then load only its empty Snowflake raw table."""

import argparse
from collections import defaultdict
import csv
from datetime import date
from decimal import Decimal
import getpass
import hashlib
import io
import json
import logging
from pathlib import Path
import sys
import warnings

import snowflake.connector
import yaml

from generate_transactions_v2 import (
    COLUMNS, DATASET_VERSION, OUTPUT_DIR, read_and_validate_accounts,
    validate_dataset,
)


TARGET = "BANKING_ANALYTICS.RAW.TRANSACTIONS"
ROLE = "BANKING_DEVELOPER"
BATCH_SIZE = 500
EXPECTED_TYPES = (
    "VARCHAR(36)", "VARCHAR(36)", "VARCHAR(32)", "VARCHAR(64)",
    "NUMBER(18,2)", "VARCHAR(16)", "DATE", "VARCHAR(32)",
    "VARCHAR(3)", "VARCHAR(36)",
)


class LoadError(Exception):
    """A deliberately safe, actionable error message without secret values."""


def read_validated_input(input_dir=OUTPUT_DIR):
    accounts, hashes = read_and_validate_accounts()
    raw = (input_dir / "transactions.csv").read_bytes()
    metadata = json.loads((input_dir / "generation.json").read_text())
    if metadata.get("dataset_version") != DATASET_VERSION:
        raise LoadError("Input metadata is not the agreed banking-v2 dataset.")
    if metadata.get("input_sha256") != hashes:
        raise LoadError("Input metadata does not match the verified frozen snapshot.")
    if metadata.get("output_sha256") != hashlib.sha256(raw).hexdigest():
        raise LoadError("CSV SHA-256 does not match generation.json; nothing loaded.")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise LoadError("CSV header does not match the agreed ten-column schema.")
    rows = list(reader)
    validate_dataset(rows, accounts)
    return rows


def reconcile_groups(rows):
    """Count and sum exact amounts at currency/type/direction/status grain."""
    groups = defaultdict(lambda: [0, Decimal("0.00")])
    for row in rows:
        key = tuple(row[k] for k in (
            "currency", "transaction_type", "direction", "status"
        ))
        groups[key][0] += 1
        groups[key][1] += Decimal(row["amount"])
    return {key: tuple(value) for key, value in groups.items()}


def read_connection_settings():
    # Parse only the selected output; do not render or log the whole profile.
    # The dbt passphrase env_var reference is deliberately not evaluated:
    # this loader always asks for the key passphrase privately at runtime.
    profile_path = Path.home() / ".dbt" / "profiles.yml"
    try:
        profiles = yaml.safe_load(profile_path.read_text())
        output = profiles["etl_project"]["outputs"]["snowflake_dev"]
        required = ("account", "user", "role", "warehouse", "database",
                    "schema", "private_key_path")
        if any(not isinstance(output.get(k), str) or not output[k] for k in required):
            raise LoadError("snowflake_dev has missing or invalid connection settings.")
        if (output.get("type") != "snowflake" or output["role"] != ROLE
                or output["database"] != "BANKING_ANALYTICS"
                or output["warehouse"] != "BANKING_DEV_WH"):
            raise LoadError("snowflake_dev must use BANKING_DEVELOPER, "
                            "BANKING_ANALYTICS and BANKING_DEV_WH.")
        key = Path(output["private_key_path"]).expanduser()
        if not key.is_file():
            raise LoadError("Configured private key file is missing.")
        return {
            "account": output["account"], "user": output["user"],
            "role": ROLE, "warehouse": output["warehouse"],
            "database": "BANKING_ANALYTICS", "schema": "RAW",
            "private_key_file": str(key), "authenticator": "SNOWFLAKE_JWT",
            "autocommit": False, "paramstyle": "pyformat",
            "login_timeout": 60, "network_timeout": 120,
        }
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise LoadError("Cannot read etl_project/snowflake_dev from ~/.dbt/profiles.yml.") from exc


def insert_parameters(row):
    return tuple(
        Decimal(row[name]) if name == "amount" else
        date.fromisoformat(row[name]) if name == "transaction_date" else
        None if name == "original_transaction_id" and row[name] == "" else
        row[name]
        for name in COLUMNS
    )


def load_transactionally(connection, rows):
    """Use SELECT and INSERT only inside an explicit transaction; no DDL."""
    expected = reconcile_groups(rows)
    try:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("SELECT CURRENT_ROLE()")
            if cursor.fetchone()[0] != ROLE:
                raise LoadError("Session role is not BANKING_DEVELOPER; load stopped.")
            cursor.execute(f"DESCRIBE TABLE {TARGET}")
            schema = cursor.fetchall()
            actual = [(r[0], r[1].upper().replace(" ", "")) for r in schema]
            wanted = list(zip((c.upper() for c in COLUMNS), EXPECTED_TYPES))
            if actual != wanted:
                raise LoadError("Target column names/order/types differ; review "
                                "sql/snowflake/02_raw_transactions.sql. No inserts made.")
            cursor.execute(f"SELECT COUNT(*) FROM {TARGET}")
            if cursor.fetchone()[0] != 0:
                raise LoadError("Target already contains data; nothing appended or removed.")
            # pyformat binds preserve strings and Decimal values. Explicit batches
            # avoid automatic staging/temporary-table DDL during executemany.
            one_row = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
            for start in range(0, len(rows), BATCH_SIZE):
                batch = rows[start:start + BATCH_SIZE]
                sql = (f"INSERT INTO {TARGET} ({', '.join(COLUMNS)}) VALUES "
                       + ", ".join([one_row] * len(batch)))
                parameters = tuple(v for row in batch for v in insert_parameters(row))
                cursor.execute(sql, parameters)
            cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT transaction_id) FROM {TARGET}")
            if tuple(cursor.fetchone()) != (len(rows), len(rows)):
                raise LoadError("Inserted row count/unique IDs failed reconciliation.")
            cursor.execute(f"""
                SELECT currency, transaction_type, direction, status,
                       COUNT(*), SUM(amount)
                FROM {TARGET}
                GROUP BY currency, transaction_type, direction, status
            """)
            actual_groups = {}
            for currency, kind, direction, status, count, amount in cursor.fetchall():
                if not isinstance(amount, Decimal):
                    raise LoadError("Snowflake amount reconciliation did not return exact decimals.")
                actual_groups[(currency, kind, direction, status)] = (count, amount)
            if actual_groups != expected:
                raise LoadError("Grouped amount/count reconciliation failed; inserts rolled back.")
        connection.commit()
    except BaseException:
        try:
            connection.rollback()
        except Exception:
            print("Rollback could not be confirmed. Inspect the target before retrying.",
                  file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate CSV and hashes locally; never connect or prompt.")
    args = parser.parse_args()
    connection = None
    phase = "local validation"
    # Do not let connector diagnostics write authentication or configuration.
    logger = logging.getLogger("snowflake.connector")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    try:
        rows = read_validated_input()
        print(f"Local validation passed: {len(rows)} transactions, "
              f"{len(reconcile_groups(rows))} reconciliation groups.")
        if args.validate_only:
            return 0
        phase = "connection configuration"
        settings = read_connection_settings()
        if not sys.stdin.isatty():
            raise LoadError("Run interactively in a terminal to enter the passphrase privately.")
        phase = "key-pair authentication"
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                passphrase = getpass.getpass("Private key passphrase: ")
            except getpass.GetPassWarning as exc:
                raise LoadError("Cannot hide terminal input; passphrase prompt cancelled.") from exc
        if not passphrase:
            raise LoadError("An encrypted private key requires a nonempty passphrase.")
        try:
            connection = snowflake.connector.connect(
                **settings, private_key_file_pwd=passphrase
            )
        finally:
            del passphrase
        phase = "transactional insertion/reconciliation"
        load_transactionally(connection, rows)
        print(f"Committed {len(rows)} rows to {TARGET}; grouped counts and amounts match.")
        return 0
    except LoadError as exc:
        print(f"Load stopped: {exc}", file=sys.stderr)
        return 1
    except snowflake.connector.Error as exc:
        print(f"Snowflake error during {phase} (code {exc.errno}, SQLSTATE {exc.sqlstate}). "
              "Check key passphrase, privileges and target schema. If commit confirmation "
              "was lost, inspect target counts before retrying.", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Never echo arbitrary library exceptions: they can include profile/key data.
        print(f"Load stopped during {phase} ({type(exc).__name__}). "
              "Check local files, hashes, dataset rules and key passphrase.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Load cancelled; no successful commit was confirmed.", file=sys.stderr)
        return 1
    except Exception:
        print(f"Unexpected error during {phase}; details withheld to protect secrets. "
              "Inspect target counts before retrying if a commit may have occurred.",
              file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                print("Connection closure could not be confirmed; check session state.",
                      file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
