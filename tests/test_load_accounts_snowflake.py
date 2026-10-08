"""Local validation and simulated atomic loads; never connect to Snowflake."""
import contextlib
import csv
import hashlib
import importlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
loader = importlib.import_module('load_accounts_snowflake')


class Connection:
    def __init__(self, existing=0, incompatible=False, fail=False, corrupt=False,
                 bad_count=False, wrong_role=False):
        self.existing, self.incompatible = existing, incompatible
        self.fail, self.corrupt, self.bad_count = fail, corrupt, bad_count
        self.wrong_role = wrong_role
        self.records, self.statements = [], []
        self.commits = self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=None):
        self.statement = statement
        self.statements.append(statement)
        if statement.startswith('INSERT'):
            if self.fail and self.records:
                raise RuntimeError('simulated second batch failure')
            assert all(isinstance(v, str) for v in parameters)
            self.records.extend(tuple(parameters[i:i+6]) for i in range(0, len(parameters), 6))

    def fetchone(self):
        if 'CURRENT_ROLE' in self.statement:
            return ('OTHER' if self.wrong_role else loader.ROLE,)
        if 'COUNT(DISTINCT' in self.statement:
            return (len(self.records), 1 if self.bad_count else len(self.records))
        return (self.existing,)

    def fetchall(self):
        if self.statement.startswith('DESCRIBE'):
            result = [(c.upper(), t, 'COLUMN', 'N')
                      for c, t in zip(loader.COLUMNS, loader.EXPECTED_TYPES)]
            if self.incompatible:
                result[-1] = ('OPENED_AT', 'TIMESTAMP_TZ(9)', 'COLUMN', 'N')
            return result
        records = list(self.records)
        if self.corrupt:
            records[0] = (*records[0][:4], '0.00', records[0][5])
        return records

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class AccountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = loader.read_validated_input()

    def test_real_input_and_precision(self):
        self.assertEqual(len(self.rows), 2000)
        conn = Connection()
        loader.load_transactionally(conn, self.rows)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))
        self.assertEqual(conn.records, [tuple(r[c] for c in loader.COLUMNS) for r in self.rows])
        self.assertTrue(all(not s.startswith(('CREATE', 'DELETE', 'TRUNCATE', 'UPDATE'))
                            for s in conn.statements))

    def test_refusal_and_rollback(self):
        for options in ({'existing': 1}, {'incompatible': True}, {'wrong_role': True},
                        {'fail': True}, {'corrupt': True}, {'bad_count': True}):
            with self.subTest(options=options):
                conn = Connection(**options)
                with self.assertRaises((loader.LoadError, RuntimeError)):
                    loader.load_transactionally(conn, self.rows)
                self.assertEqual((conn.commits, conn.rollbacks), (0, 1))
                if any(k in options for k in ('existing', 'incompatible', 'wrong_role')):
                    self.assertEqual(conn.records, [])

    def test_source_validation_rejections(self):
        for field, value in [('account_id', 'bad'), ('customer_id', ''),
                             ('account_type', 'unknown'), ('spend_profile', 'unknown'),
                             ('balance', 'NaN'), ('balance', '10001'),
                             ('opened_at', '2026-04-21 10:05:15'),
                             ('opened_at', '2026-04-21 10:05:15 +0100 UTC')]:
            with self.subTest(field=field, value=value):
                rows = [dict(r) for r in self.rows]
                rows[0][field] = value
                with self.assertRaises(loader.LoadError):
                    loader.validate_rows(rows)
        rows = [dict(r) for r in self.rows]
        rows[1]['account_id'] = rows[0]['account_id']
        with self.assertRaises(loader.LoadError):
            loader.validate_rows(rows)
        with self.assertRaises(loader.LoadError):
            loader.validate_rows(self.rows[:-1])

    def test_hash_and_header_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            manifest = (loader.FIXTURE_DIR / 'SHA256SUMS').read_text()
            (target / 'SHA256SUMS').write_text(manifest)
            (target / 'accounts.csv').write_bytes(b'changed')
            with self.assertRaisesRegex(loader.LoadError, 'SHA-256'):
                loader.read_validated_input(target)
            raw = b'wrong,header\n'
            old = loader.read_manifest(loader.FIXTURE_DIR)['accounts.csv']
            (target / 'accounts.csv').write_bytes(raw)
            (target / 'SHA256SUMS').write_text(manifest.replace(old, hashlib.sha256(raw).hexdigest()))
            with self.assertRaisesRegex(loader.LoadError, 'header'):
                loader.read_validated_input(target)

    def test_validate_only_never_configures_or_connects(self):
        with patch.object(sys, 'argv', ['loader', '--validate-only']), \
             patch.object(loader, 'read_connection_settings', side_effect=AssertionError), \
             patch.object(loader.snowflake.connector, 'connect', side_effect=AssertionError), \
             patch.object(loader.getpass, 'getpass', side_effect=AssertionError), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(loader.main(), 0)


if __name__ == '__main__':
    unittest.main()
