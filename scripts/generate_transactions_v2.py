"""Generate the banking-v2 training dataset; see docs/banking-v2-dataset.md."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "banking-v2"
OUTPUT_DIR = PROJECT_ROOT / "output" / "banking-v2"
DATASET_VERSION = "banking-v2"
GENERATOR_VERSION = "2"  # Input packaging changed; transaction algorithm is unchanged.
SEED = 1234
START_DATE = date(2026, 4, 21)
END_DATE = date(2026, 9, 30)
MIN_PENCE = 100
MAX_PENCE = 50_000
ID_NAMESPACE = uuid5(NAMESPACE_URL, "etl-nlp-project/banking-transactions")
CATEGORIES = ("groceries", "travel", "utilities", "entertainment")
PAYMENT_STATUSES = {"completed": 8100, "pending": 630, "failed": 270}
REFUND_STATUSES = {"completed": 900, "pending": 70, "failed": 30}
COLUMNS = (
    "transaction_id", "account_id", "transaction_type", "merchant_category",
    "amount", "direction", "transaction_date", "status", "currency",
    "original_transaction_id",
)


def require(condition, message):
    """Use explicit validation that remains enabled under python -O."""
    if not condition:
        raise ValueError(message)


def read_manifest(fixture_dir):
    hashes = {}
    for line in (fixture_dir / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([\w.-]+\.csv)", line)
        require(match is not None, "Invalid SHA256SUMS entry")
        digest, name = match.groups()
        require(name not in hashes, "Duplicate SHA256SUMS entry")
        hashes[name] = digest
    require(set(hashes) == {"accounts.csv"},
            "Fixture manifest must list only the required accounts.csv")
    return hashes


def parse_opening_date(value):
    # The frozen Spoof file uses: 2026-04-21 10:05:15 +0000 UTC.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    if value.endswith(" UTC"):
        opened = datetime.strptime(value[:-4], "%Y-%m-%d %H:%M:%S %z")
    else:
        opened = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(opened.tzinfo is not None, "Opening timestamps must include a timezone")
    return opened.astimezone(timezone.utc).date()


def read_and_validate_accounts(fixture_dir=FIXTURE_DIR):
    """Verify frozen bytes before parsing and return accounts in stable order."""
    hashes = read_manifest(fixture_dir)
    accounts_bytes = None
    for name, expected in hashes.items():
        data = (fixture_dir / name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected,
                f"Fixture SHA-256 mismatch: {name}")
        if name == "accounts.csv":
            accounts_bytes = data

    reader = csv.DictReader(io.StringIO(accounts_bytes.decode("utf-8-sig")))
    require(reader.fieldnames is not None and
            len(set(reader.fieldnames)) == len(reader.fieldnames),
            "Missing or duplicate account headers")
    require({"account_id", "opened_at"}.issubset(reader.fieldnames),
            "Accounts require account_id and opened_at")
    accounts = {}
    for row_number, row in enumerate(reader, start=2):
        require(None not in row and all(v is not None for v in row.values()),
                f"Malformed account CSV row {row_number}")
        account_id = row["account_id"]
        require(str(UUID(account_id)) == account_id,
                f"Account ID must be a canonical UUID at row {row_number}")
        require(account_id not in accounts, "Duplicate account ID")
        opened_at = parse_opening_date(row["opened_at"])
        require(opened_at < END_DATE,
                "Account opens too late for a payment followed by a refund")
        accounts[account_id] = opened_at
    require(bool(accounts), "Frozen accounts CSV is empty")
    return dict(sorted(accounts.items())), hashes


def transaction_id(transaction_type, ordinal):
    return str(uuid5(ID_NAMESPACE,
                    f"{DATASET_VERSION}:{transaction_type}:{ordinal}"))


def shuffled_statuses(allocation, rng):
    statuses = [status for status, count in allocation.items() for _ in range(count)]
    rng.shuffle(statuses)
    return statuses


def random_date(first, last, rng):
    require(first <= last, "Empty eligible date range")
    return first + timedelta(days=rng.randrange((last - first).days + 1))


def format_pence(pence):
    return f"{pence // 100}.{pence % 100:02d}"


def generate_payments(accounts, rng):
    account_ids = tuple(sorted(accounts))
    payments = []
    for ordinal, status in enumerate(shuffled_statuses(PAYMENT_STATUSES, rng), 1):
        account_id = rng.choice(account_ids)
        first = max(START_DATE, accounts[account_id])
        # Every payment can have a later refund within the reporting window.
        payment_date = random_date(first, END_DATE - timedelta(days=1), rng)
        payments.append(dict(zip(COLUMNS, (
            transaction_id("payment", ordinal), account_id, "payment",
            rng.choice(CATEGORIES), format_pence(rng.randint(MIN_PENCE, MAX_PENCE)),
            "debit", payment_date.isoformat(), status, "GBP", "",
        ))))
    return payments


def generate_refunds(payments, rng):
    eligible = sorted(
        (p for p in payments if p["status"] == "completed"
         and date.fromisoformat(p["transaction_date"]) < END_DATE),
        key=lambda p: p["transaction_id"],
    )
    require(len(eligible) >= 1000, "Too few eligible completed refund parents")
    parents = rng.sample(eligible, 1000)
    statuses = shuffled_statuses(REFUND_STATUSES, rng)
    refunds = []
    for ordinal, (parent, status) in enumerate(zip(parents, statuses), 1):
        first = date.fromisoformat(parent["transaction_date"]) + timedelta(days=1)
        refunds.append(dict(zip(COLUMNS, (
            transaction_id("refund", ordinal), parent["account_id"], "refund",
            parent["merchant_category"], parent["amount"], "credit",
            random_date(first, END_DATE, rng).isoformat(), status,
            parent["currency"], parent["transaction_id"],
        ))))
    return refunds


def validate_dataset(rows, accounts):
    require(len(rows) == 10_000, "Expected exactly 10,000 transactions")
    # Check shape before indexing fields so malformed CSVs fail with a clear
    # validation error rather than KeyError or a regex TypeError.
    for row in rows:
        require(tuple(row) == COLUMNS, "Incorrect output columns or ordering")
        require(all(isinstance(value, str) for value in row.values()),
                "Missing or malformed CSV field")
    require(Counter(r["transaction_type"] for r in rows) ==
            {"payment": 9000, "refund": 1000}, "Incorrect transaction type counts")
    by_id = {r["transaction_id"]: r for r in rows}
    require(len(by_id) == len(rows), "Duplicate transaction IDs")
    ordinals = Counter()
    refund_parents = set()
    for row in rows:
        require(tuple(row) == COLUMNS, "Incorrect output columns or ordering")
        kind = row["transaction_type"]
        ordinals[kind] += 1
        require(row["transaction_id"] == transaction_id(kind, ordinals[kind]),
                "Transaction ID does not match deterministic ordinal")
        require(row["account_id"] in accounts, "Unknown account reference")
        value = row["transaction_date"]
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "Invalid date format")
        transaction_date = date.fromisoformat(value)
        require(max(START_DATE, accounts[row["account_id"]]) <= transaction_date <= END_DATE,
                "Transaction date outside allowed account window")
        require(re.fullmatch(r"\d+\.\d{2}", row["amount"]),
                "Amount must have exactly two decimal places")
        pounds, pence = row["amount"].split(".")
        require(MIN_PENCE <= int(pounds) * 100 + int(pence) <= MAX_PENCE,
                "Amount outside positive payment bounds")
        require(row["currency"] == "GBP", "Unexpected currency")
        require(row["merchant_category"] in CATEGORIES, "Unknown merchant category")
        require(row["direction"] == {"payment": "debit", "refund": "credit"}[kind],
                "Direction does not match transaction type")
        parent_id = row["original_transaction_id"]
        if kind == "payment":
            require(parent_id == "", "Payments must have blank original_transaction_id")
        else:
            require(parent_id in by_id, "Refund parent does not exist")
            require(parent_id not in refund_parents, "Repeated refund parent")
            refund_parents.add(parent_id)
            parent = by_id[parent_id]
            require(parent["transaction_type"] == "payment" and
                    parent["status"] == "completed", "Refund needs a completed payment")
            for field in ("account_id", "amount", "currency", "merchant_category"):
                require(row[field] == parent[field], f"Refund differs from parent: {field}")
            require(transaction_date > date.fromisoformat(parent["transaction_date"]),
                    "Refund must occur strictly after its payment")
    for kind, allocation in (("payment", PAYMENT_STATUSES), ("refund", REFUND_STATUSES)):
        require(Counter(r["status"] for r in rows if r["transaction_type"] == kind)
                == allocation, f"Incorrect {kind} status allocation")
    require(Counter(r["status"] for r in rows) ==
            {"completed": 9000, "pending": 700, "failed": 300},
            "Incorrect overall status totals")


def write_versioned_output(rows, accounts, input_hashes, output_dir=OUTPUT_DIR):
    """Validate first, then publish the final CSV without replacing any file."""
    validate_dataset(rows, accounts)
    require(not output_dir.exists() and not output_dir.is_symlink(),
            "banking-v2 output already exists; refusing to overwrite it")
    metadata = {
        "dataset_version": DATASET_VERSION,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": sys.version.split()[0],
        "seed": SEED,
        "uuid_namespace": str(ID_NAMESPACE),
        "date_start": START_DATE.isoformat(), "date_end": END_DATE.isoformat(),
        "payment_min_pence": MIN_PENCE, "payment_max_pence": MAX_PENCE,
        "payment_statuses": PAYMENT_STATUSES, "refund_statuses": REFUND_STATUSES,
        "merchant_categories": CATEGORIES,
        "currency": "GBP", "columns": COLUMNS,
        "input_sha256": input_hashes,
    }
    # Exclusive directory creation also catches another process creating it.
    output_dir.mkdir(parents=True, exist_ok=False)
    final_path = output_dir / "transactions.csv"
    # Temporary staging disappears on errors; existing final output is never replaced.
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=output_dir) as staging:
        candidate = Path(staging) / "transactions.csv"
        with candidate.open("x", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        with candidate.open(newline="", encoding="utf-8") as f:
            validate_dataset(list(csv.DictReader(f)), accounts)
        metadata["output_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        with (output_dir / "generation.json").open("x", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.write("\n")
        # A hard link atomically exposes the complete CSV and fails if it exists.
        os.link(candidate, final_path)
    return final_path


def main():
    require(not OUTPUT_DIR.exists() and not OUTPUT_DIR.is_symlink(),
            "banking-v2 output already exists; refusing to overwrite it")
    accounts, hashes = read_and_validate_accounts()
    rng = random.Random(SEED)
    payments = generate_payments(accounts, rng)
    refunds = generate_refunds(payments, rng)
    rows = payments + refunds
    validate_dataset(rows, accounts)
    path = write_versioned_output(rows, accounts, hashes)
    print(f"Validated and wrote {len(rows)} transactions to {path}")


if __name__ == "__main__":
    main()
