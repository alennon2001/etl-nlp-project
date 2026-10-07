"""Local-only loader checks; the fake connection never contacts Snowflake."""

from decimal import Decimal
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
loader = importlib.import_module("load_transactions_snowflake")


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=None):
        self.statement = statement
        self.connection.statements.append(statement)
        if statement.startswith("INSERT"):
            self.connection.batches += 1
            if self.connection.fail_batch == self.connection.batches:
                raise RuntimeError("Simulated insert failure")
            assert all(isinstance(parameters[i], Decimal)
                       for i in range(4, len(parameters), len(loader.COLUMNS)))
        return self

    def fetchone(self):
        if "CURRENT_ROLE" in self.statement:
            return (loader.ROLE,)
        if "COUNT(DISTINCT" in self.statement:
            return (10000, 10000)
        return (self.connection.existing_count,)

    def fetchall(self):
        if self.statement.startswith("DESCRIBE"):
            return list(zip((c.upper() for c in loader.COLUMNS), loader.EXPECTED_TYPES))
        groups = dict(self.connection.expected)
        if self.connection.bad_totals:
            key = next(iter(groups))
            count, amount = groups[key]
            groups[key] = (count, amount + Decimal("0.01"))
        return [(*key, *values) for key, values in groups.items()]


class FakeConnection:
    def __init__(self, expected, existing_count=0, fail_batch=None, bad_totals=False):
        self.expected = expected
        self.existing_count = existing_count
        self.fail_batch = fail_batch
        self.bad_totals = bad_totals
        self.batches = 0
        self.commits = 0
        self.rollbacks = 0
        self.statements = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = loader.read_validated_input()
        cls.expected = loader.reconcile_groups(cls.rows)

    def test_validated_actual_csv(self):
        self.assertEqual(len(self.rows), 10000)
        self.assertEqual(sum(n for n, _ in self.expected.values()), 10000)

    def test_exact_decimal_and_blank_parent_conversion(self):
        row = dict(self.rows[0], amount="123.45", original_transaction_id="")
        bound = loader.insert_parameters(row)
        self.assertEqual(bound[4], Decimal("123.45"))
        self.assertIsInstance(bound[4], Decimal)
        self.assertIsNone(bound[-1])
        self.assertIsInstance(bound[0], str)

    def test_commit_only_after_reconciliation(self):
        connection = FakeConnection(self.expected)
        loader.load_transactionally(connection, self.rows)
        self.assertEqual((connection.commits, connection.rollbacks), (1, 0))
        self.assertEqual(connection.batches, 20)
        self.assertTrue(all(not s.startswith(("CREATE", "TRUNCATE", "DELETE"))
                            for s in connection.statements))

    def test_existing_data_stops_before_inserts(self):
        connection = FakeConnection(self.expected, existing_count=1)
        with self.assertRaisesRegex(loader.LoadError, "already contains data"):
            loader.load_transactionally(connection, self.rows)
        self.assertEqual((connection.batches, connection.commits, connection.rollbacks),
                         (0, 0, 1))

    def test_insert_failure_rolls_back_prior_batches(self):
        connection = FakeConnection(self.expected, fail_batch=2)
        with self.assertRaises(RuntimeError):
            loader.load_transactionally(connection, self.rows)
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))

    def test_amount_mismatch_prevents_commit(self):
        connection = FakeConnection(self.expected, bad_totals=True)
        with self.assertRaisesRegex(loader.LoadError, "reconciliation failed"):
            loader.load_transactionally(connection, self.rows)
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))

    def test_changed_csv_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "transactions.csv").write_bytes(
                (loader.OUTPUT_DIR / "transactions.csv").read_bytes() + b"\n")
            (target / "generation.json").write_bytes(
                (loader.OUTPUT_DIR / "generation.json").read_bytes())
            with self.assertRaisesRegex(loader.LoadError, "SHA-256"):
                loader.read_validated_input(target)

    def test_changed_snapshot_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "transactions.csv").write_bytes(
                (loader.OUTPUT_DIR / "transactions.csv").read_bytes())
            metadata = json.loads((loader.OUTPUT_DIR / "generation.json").read_text())
            metadata["input_sha256"]["accounts.csv"] = "0" * 64
            (target / "generation.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(loader.LoadError, "frozen snapshot"):
                loader.read_validated_input(target)


if __name__ == "__main__":
    unittest.main()
