"""Validate frozen accounts locally, then load only an empty compatible raw table."""

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import getpass
import hashlib
import io
import logging
import re
import sys
from uuid import UUID
import warnings

import snowflake.connector

from generate_transactions_v2 import SNAPSHOT_DIR, read_manifest
from load_transactions_snowflake import LoadError, ROLE, read_connection_settings

TARGET = "BANKING_ANALYTICS.RAW.ACCOUNTS"
COLUMNS = ("account_id", "customer_id", "account_type", "spend_profile", "balance", "opened_at")
EXPECTED_TYPES = ("VARCHAR(36)", "VARCHAR(36)", "VARCHAR(32)", "VARCHAR(32)",
                  "VARCHAR(64)", "VARCHAR(64)")
BATCH_SIZE = 500


def validate_rows(rows):
    if len(rows) != 2000:
        raise LoadError("Frozen accounts must contain exactly 2,000 rows.")
    ids = set()
    for row in rows:
        if tuple(row) != COLUMNS or any(
            not isinstance(v, str) or not v.strip() or v != v.strip()
            or v.lower() in ("null", "none", "n/a") for v in row.values()
        ):
            raise LoadError("Accounts contain missing, malformed or noncanonical fields.")
        for column in ("account_id", "customer_id"):
            try:
                valid = str(UUID(row[column])) == row[column]
            except ValueError:
                valid = False
            if not valid:
                raise LoadError("Account/customer IDs must be canonical UUIDs.")
        if row["account_id"] in ids:
            raise LoadError("Duplicate account ID.")
        ids.add(row["account_id"])
        if row["account_type"] not in ("current", "savings", "credit"):
            raise LoadError("Unknown account type.")
        if row["spend_profile"] not in ("low_spender", "normal", "high_spender"):
            raise LoadError("Unknown synthetic spend profile.")
        try:
            balance = Decimal(row["balance"])
            valid = bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", row["balance"]))
            valid = valid and balance.is_finite() and Decimal(0) <= balance <= Decimal(10000)
        except InvalidOperation:
            valid = False
        if not valid or len(row["balance"]) > 64:
            raise LoadError("Invalid synthetic source balance.")
        # Exact frozen format, including its timezone; keep original text in raw.
        try:
            opened = datetime.strptime(row["opened_at"], "%Y-%m-%d %H:%M:%S %z UTC")
            valid = opened.strftime("%Y-%m-%d %H:%M:%S %z UTC") == row["opened_at"]
            valid = valid and opened.utcoffset().total_seconds() == 0
        except ValueError:
            valid = False
        if not valid or len(row["opened_at"]) > 64:
            raise LoadError("Opening timestamp must use the frozen explicit UTC format.")


def read_validated_input(snapshot_dir=SNAPSHOT_DIR):
    expected = read_manifest(snapshot_dir)["accounts.csv"]
    raw = (snapshot_dir / "accounts.csv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise LoadError("Frozen accounts SHA-256 mismatch; nothing loaded.")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise LoadError("Account CSV header does not match the agreed six columns.")
    rows = list(reader)
    validate_rows(rows)
    return rows


def load_transactionally(connection, rows):
    """Reconcile every field as text before commit; no DDL or destructive SQL."""
    validate_rows(rows)
    expected = sorted(tuple(row[c] for c in COLUMNS) for row in rows)
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
            if actual != wanted or any(r[2] != "COLUMN" or r[3] != "N" for r in schema):
                raise LoadError("Target schema differs; review sql/snowflake/03_raw_accounts.sql. No inserts made.")
            cursor.execute(f"SELECT COUNT(*) FROM {TARGET}")
            if cursor.fetchone()[0] != 0:
                raise LoadError("Target already contains data; nothing appended or removed.")
            one_row = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
            for start in range(0, len(rows), BATCH_SIZE):
                batch = rows[start:start + BATCH_SIZE]
                sql = (f"INSERT INTO {TARGET} ({', '.join(COLUMNS)}) VALUES "
                       + ", ".join([one_row] * len(batch)))
                parameters = tuple(row[c] for row in batch for c in COLUMNS)
                cursor.execute(sql, parameters)
            cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT account_id) FROM {TARGET}")
            if tuple(cursor.fetchone()) != (len(rows), len(rows)):
                raise LoadError("Loaded account count/unique IDs failed reconciliation.")
            cursor.execute(f"SELECT {', '.join(COLUMNS)} FROM {TARGET}")
            if sorted(tuple(r) for r in cursor.fetchall()) != expected:
                raise LoadError("Loaded source records failed exact reconciliation.")
        connection.commit()
    except BaseException:
        try:
            connection.rollback()
        except Exception:
            print("Rollback could not be confirmed. Inspect the target before retrying.", file=sys.stderr)
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
        print(f"Local validation passed: {len(rows)} accounts, "
              "all six source fields validated.")
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
        print(f"Committed {len(rows)} rows to {TARGET}; all source records match.")
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
