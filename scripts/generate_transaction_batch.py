"""Deterministic local batch 002; no Snowflake imports or baseline writes."""

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import tempfile
from uuid import NAMESPACE_URL, uuid5

from generate_transactions_v2 import CATEGORIES, END_DATE, format_pence
from transaction_batch_state import (
    BatchError, apply_delivery, baseline_state, require, seal_delivery, summarize,
    validate_delivery,
)

BATCH_ID = "banking-batch-002"
SEED = 1234
GENERATOR_VERSION = "1"
SOURCE_UPDATED_AT = "2026-10-01T00:00:00Z"
NAMESPACE = uuid5(NAMESPACE_URL, "etl-nlp-project/transaction-batches")


def generate_delivery(state):
    require(not state.batches and len(state.records) == 10000,
            "Batch 002 generation requires untouched baseline state.")
    rng = random.Random(SEED)
    account_ids = tuple(sorted(state.accounts))
    records = []
    for ordinal in range(1, 101):
        key = str(uuid5(NAMESPACE, f"{BATCH_ID}:payment:{ordinal}"))
        require(key not in state.records, "Batch ID collides with baseline transaction ID.")
        records.append(dict(
            transaction_id=key, account_id=rng.choice(account_ids), transaction_type="payment",
            merchant_category=rng.choice(CATEGORIES), amount=format_pence(rng.randint(100, 50000)),
            direction="debit", transaction_date=END_DATE.isoformat(), status="completed", currency="GBP",
            original_transaction_id="", source_version=1, source_updated_at=SOURCE_UPDATED_AT,
        ))
    pending = sorted((r for r in state.records.values()
                      if r["transaction_type"] == "payment" and r["status"] == "pending"),
                     key=lambda r: r["transaction_id"])
    require(len(pending) >= 20, "Too few pending baseline payments.")
    for previous in pending[:20]:
        record = deepcopy(previous)
        record.update(status="completed", source_version=2, source_updated_at=SOURCE_UPDATED_AT)
        records.append(record)
    delivery = seal_delivery(dict(batch_id=BATCH_ID, baseline_sha256=state.baseline_sha256,
                                  accounts_sha256=state.accounts_sha256, generator_version=GENERATOR_VERSION,
                                  seed=SEED, records=records))
    validate_delivery(delivery, state)
    require(delivery["record_count"] == 120
            and delivery["source_version_counts"] == {"1": 100, "2": 20},
            "Incorrect batch exercise allocation.")
    return delivery


def delivery_bytes(delivery):
    return (json.dumps(delivery, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_delivery(delivery, output_dir, state):
    """Exclusive output publication; never overwrite prior deliveries or baseline files."""
    validate_delivery(delivery, state)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    raw = delivery_bytes(delivery)
    with (output_dir / "delivery.json").open("xb") as file:
        file.write(raw)
    with (output_dir / "SHA256SUMS").open("x") as file:
        file.write(hashlib.sha256(raw).hexdigest() + "  delivery.json\n")
    return output_dir / "delivery.json"


def read_delivery(output_dir, state):
    """Verify file bytes before parsing and verify the complete envelope afterward."""
    output_dir = Path(output_dir)
    raw = (output_dir / "delivery.json").read_bytes()
    expected = hashlib.sha256(raw).hexdigest() + "  delivery.json\n"
    require((output_dir / "SHA256SUMS").read_text() == expected, "Delivery file checksum mismatch.")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field.")
            result[key] = value
        return result
    try:
        delivery = json.loads(raw, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BatchError("Invalid delivery JSON.") from exc
    validate_delivery(delivery, state)
    return delivery


def reconcile_exercise(before, after, delivery, result):
    """Assert the fixed batch-002 acceptance totals and independent monthly deltas."""
    old, new = summarize(before.records), summarize(after.records)
    require({k: result[k] for k in ("inserted", "updated", "unchanged", "stale")}
            == dict(inserted=100, updated=20, unchanged=0, stale=0),
            "Exercise application counts failed reconciliation.")
    require(old["transaction_count"] == 10000 and new["transaction_count"] == 10100
            and new["unique_transactions"] == 10100, "Exercise row counts failed reconciliation.")
    require(old["statuses"] == dict(completed=9000, pending=700, failed=300)
            and new["statuses"] == dict(completed=9120, pending=680, failed=300),
            "Exercise statuses failed reconciliation.")
    inserted = [r for r in delivery["records"] if r["transaction_id"] not in before.records]
    updated = [r for r in delivery["records"] if r["transaction_id"] in before.records]
    new_amount = sum((Decimal(r["amount"]) for r in inserted), Decimal("0.00"))
    update_amount = sum((Decimal(r["amount"]) for r in updated), Decimal("0.00"))
    expected_amounts = dict(old["amounts"])
    expected_amounts[("GBP", "completed", "debit")] += new_amount + update_amount
    expected_amounts[("GBP", "pending", "debit")] -= update_amount
    require(new["amounts"] == expected_amounts, "Exact status/direction amounts failed reconciliation.")
    require(new["amounts"][("GBP", "completed", "credit")] == Decimal("226623.07"),
            "Completed credits changed unexpectedly.")
    expected_monthly = deepcopy(old["monthly"])
    for record in delivery["records"]:
        key = (record["transaction_date"][:7] + "-01", record["currency"])
        group = expected_monthly.setdefault(key, dict(transaction_count=0, debit_total=Decimal("0.00"),
                                                     credit_total=Decimal("0.00"), net_outflow=Decimal("0.00")))
        group["transaction_count"] += 1
        group["debit_total"] += Decimal(record["amount"])
        group["net_outflow"] += Decimal(record["amount"])
    require(new["monthly"] == expected_monthly, "Monthly completed results failed reconciliation.")
    return dict(before=old, after=new, inserted_amount=new_amount,
                updated_amount=update_amount, completed_debit_delta=new_amount + update_amount)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Optional new output directory; default demonstration uses temporary storage.")
    args = parser.parse_args()
    state = baseline_state()
    delivery = generate_delivery(state)
    def demonstrate(output_dir):
        path = write_delivery(delivery, output_dir, state)
        checked = read_delivery(path.parent, state)
        after, result = apply_delivery(state, checked)
        replayed, replay = apply_delivery(after, checked)
        require(replayed == after and replay["already_applied"], "Replay changed local state.")
        report = reconcile_exercise(state, after, checked, result)
        before_summary, after_summary = report["before"], report["after"]
        print(f"Verified delivery: {delivery['record_count']} records; {delivery['content_sha256']}")
        print(f"Applied: {result['inserted']} inserted, {result['updated']} updated; replay unchanged.")
        print(f"Transactions: {before_summary['transaction_count']} -> {after_summary['transaction_count']}")
        print(f"Statuses: {after_summary['statuses']}")
        print(f"Exact completed debit/net-outflow delta: {report['completed_debit_delta']} "
              f"({report['inserted_amount']} new + {report['updated_amount']} newly completed)")
        for key in sorted(after_summary['monthly']):
            old, new = before_summary['monthly'][key], after_summary['monthly'][key]
            print(f"{key}: completed {old['transaction_count']} -> {new['transaction_count']}; "
                  f"net outflow {old['net_outflow']} -> {new['net_outflow']}")
    if args.output_dir is not None:
        demonstrate(args.output_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="transaction-batch-") as tmp:
            demonstrate(Path(tmp) / BATCH_ID)


if __name__ == "__main__":
    main()
