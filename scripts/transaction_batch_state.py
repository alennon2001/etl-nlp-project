"""Local copy-on-write transaction state; no database/authentication dependencies."""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from uuid import UUID

from generate_transactions_v2 import (
    COLUMNS, CATEGORIES, END_DATE, START_DATE, FIXTURE_DIR, OUTPUT_DIR,
    read_and_validate_accounts, validate_dataset,
)

BASELINE_SHA256 = "119498f5d5fbc3dde9f3da8fee4e3b7e45e89ee0bd453a877d31cf62c68f0f74"
BASELINE_WATERMARK = "2026-09-30T23:59:59Z"
RECORD_FIELDS = set(COLUMNS) | {"source_version", "source_updated_at"}
DELIVERY_FIELDS = {
    "batch_id", "baseline_sha256", "accounts_sha256", "generator_version", "seed",
    "record_count", "source_version_counts", "records", "content_sha256",
}


class BatchError(ValueError):
    """Invalid delivery or incompatible source state; messages omit raw records."""


def require(condition, message):
    if not condition:
        raise BatchError(message)


def timestamp(value):
    require(isinstance(value, str) and bool(re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)),
        "Source timestamp requires explicit UTC seconds.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BatchError("Invalid source timestamp.") from exc


def content_hash(delivery):
    """Hash canonical envelope bytes excluding only the hash field itself."""
    payload = {key: value for key, value in delivery.items() if key != "content_sha256"}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BatchError("Delivery is not canonical JSON data.") from exc
    return hashlib.sha256(encoded).hexdigest()


def seal_delivery(delivery):
    """Return an independent envelope with counts and canonical hash filled in."""
    result = deepcopy(delivery)
    result["record_count"] = len(result["records"])
    result["source_version_counts"] = dict(Counter(str(r["source_version"])
                                                  for r in result["records"]))
    result["content_sha256"] = content_hash(result)
    return result


@dataclass
class LocalState:
    records: dict
    batches: dict
    accounts: dict
    baseline_sha256: str
    accounts_sha256: str


def baseline_state(input_dir=OUTPUT_DIR, fixture_dir=FIXTURE_DIR):
    """Read only verified baseline CSV and account fixture, never profiles/keys."""
    accounts, hashes = read_and_validate_accounts(fixture_dir)
    raw = (Path(input_dir) / "transactions.csv").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == BASELINE_SHA256,
            "Baseline CSV must match the frozen banking-v2 hash.")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    require(tuple(reader.fieldnames or ()) == COLUMNS, "Invalid baseline header.")
    rows = list(reader)
    validate_dataset(rows, accounts)  # Keep the original strict 10,000-row contract.
    records = {r["transaction_id"]: dict(r, source_version=1,
                                        source_updated_at=BASELINE_WATERMARK) for r in rows}
    return LocalState(records, {}, accounts, BASELINE_SHA256, hashes["accounts.csv"])


def validate_record(record, accounts):
    require(isinstance(record, dict) and set(record) == RECORD_FIELDS,
            "Delivery record must have ten business fields and two source fields.")
    require(all(isinstance(record[k], str) for k in COLUMNS),
            "Business fields must be strings.")
    for key in ("transaction_id", "account_id"):
        try:
            valid = str(UUID(record[key])) == record[key]
        except ValueError:
            valid = False
        require(valid, "IDs must be canonical UUIDs.")
    require(record["account_id"] in accounts, "Unknown account reference.")
    require(record["transaction_type"] == "payment" and record["direction"] == "debit"
            and record["original_transaction_id"] == "",
            "This exercise accepts payment/debit records without parent links only.")
    require(record["status"] in ("completed", "pending", "failed"), "Invalid status.")
    require(record["merchant_category"] in CATEGORIES and record["currency"] == "GBP",
            "Invalid category or currency.")
    require(bool(re.fullmatch(r"\d+\.\d{2}", record["amount"])),
            "Amount requires two decimal places.")
    require(Decimal("1.00") <= Decimal(record["amount"]) <= Decimal("500.00"),
            "Amount is outside positive payment bounds.")
    require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["transaction_date"])),
            "Invalid transaction date format.")
    try:
        event_date = date.fromisoformat(record["transaction_date"])
    except ValueError as exc:
        raise BatchError("Invalid transaction date.") from exc
    require(max(START_DATE, accounts[record["account_id"]]) <= event_date <= END_DATE,
            "Transaction date is outside account/reporting window.")
    require(type(record["source_version"]) is int and record["source_version"] >= 1,
            "Source version must be a positive integer.")
    require(timestamp(record["source_updated_at"]).date() >= event_date,
            "Source timestamp cannot precede transaction date.")


def validate_delivery(delivery, state):
    require(isinstance(delivery, dict) and set(delivery) == DELIVERY_FIELDS,
            "Invalid delivery envelope fields.")
    require(isinstance(delivery["batch_id"], str) and bool(re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,99}", delivery["batch_id"])), "Invalid batch ID.")
    require(delivery["baseline_sha256"] == state.baseline_sha256
            and delivery["accounts_sha256"] == state.accounts_sha256,
            "Delivery provenance does not match baseline state.")
    require(delivery["generator_version"] == "1" and type(delivery["seed"]) is int,
            "Invalid batch generator metadata.")
    require(isinstance(delivery["records"], list) and bool(delivery["records"]),
            "Delivery requires records.")
    require(type(delivery["record_count"]) is int
            and delivery["record_count"] == len(delivery["records"]),
            "Delivery record count mismatch.")
    require(isinstance(delivery["source_version_counts"], dict)
            and all(isinstance(k, str) and type(v) is int and v > 0
                    for k, v in delivery["source_version_counts"].items()),
            "Invalid source-version count metadata.")
    require(isinstance(delivery["content_sha256"], str)
            and delivery["content_sha256"] == content_hash(delivery),
            "Delivery content hash mismatch.")
    ids = set()
    for record in delivery["records"]:
        validate_record(record, state.accounts)
        require(record["transaction_id"] not in ids, "Duplicate transaction ID in delivery.")
        ids.add(record["transaction_id"])
    require(delivery["source_version_counts"] == dict(Counter(
        str(r["source_version"]) for r in delivery["records"])),
        "Delivery source-version counts mismatch.")


def apply_delivery(state, delivery):
    """Return (new state, result); never mutate input state or delivery, even on failure."""
    validate_delivery(delivery, state)
    batch_id, digest = delivery["batch_id"], delivery["content_sha256"]
    if batch_id in state.batches:
        require(state.batches[batch_id]["content_sha256"] == digest,
                "Batch ID already committed with different content.")
        return deepcopy(state), dict(deepcopy(state.batches[batch_id]), already_applied=True)
    # All publications occur through the return value after every record succeeds.
    candidate = deepcopy(state)
    counts = dict(inserted=0, updated=0, unchanged=0, stale=0)
    for record in delivery["records"]:
        key = record["transaction_id"]
        previous = candidate.records.get(key)
        if previous is None:
            require(record["source_version"] == 1, "New ID must start at source version 1.")
            require(record["status"] == "completed" and record["transaction_date"] == END_DATE.isoformat(),
                    "New records must be completed September 30 payments.")
            counts["inserted"] += 1
            candidate.records[key] = deepcopy(record)
        elif record["source_version"] < previous["source_version"]:
            counts["stale"] += 1
        elif record["source_version"] == previous["source_version"]:
            require(record == previous, "Equal source versions contain conflicting records.")
            counts["unchanged"] += 1
        else:
            require(record["source_version"] == previous["source_version"] + 1,
                    "Source version gap.")
            require(previous["status"] == "pending" and record["status"] == "completed",
                    "Only pending-to-completed transitions are supported.")
            require(all(record[k] == previous[k] for k in COLUMNS if k != "status"),
                    "Status updates must preserve all other business fields.")
            require(timestamp(record["source_updated_at"]) > timestamp(previous["source_updated_at"]),
                    "Source update timestamp must advance.")
            counts["updated"] += 1
            candidate.records[key] = deepcopy(record)
    entry = dict(content_sha256=digest, **counts)
    candidate.batches[batch_id] = entry
    return candidate, dict(entry, already_applied=False)


def summarize(records):
    """Exact status/count/amount profile and completed monthly reporting results."""
    rows = list(records.values()) if isinstance(records, dict) else list(records)
    statuses = Counter(r["status"] for r in rows)
    amounts = defaultdict(lambda: Decimal("0.00"))
    monthly = {}
    for row in rows:
        amounts[(row["currency"], row["status"], row["direction"])] += Decimal(row["amount"])
        if row["status"] != "completed":
            continue
        key = (row["transaction_date"][:7] + "-01", row["currency"])
        group = monthly.setdefault(key, dict(transaction_count=0, debit_total=Decimal("0.00"),
                                             credit_total=Decimal("0.00"), net_outflow=Decimal("0.00")))
        group["transaction_count"] += 1
        amount = Decimal(row["amount"])
        group[row["direction"] + "_total"] += amount
        group["net_outflow"] += amount if row["direction"] == "debit" else -amount
    return dict(transaction_count=len(rows), unique_transactions=len({r["transaction_id"] for r in rows}),
                statuses=dict(statuses), amounts=dict(amounts), monthly=monthly)
