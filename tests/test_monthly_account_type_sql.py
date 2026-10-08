"""Execute mart guardrail SQL locally; no dbt adapter or warehouse connection."""
from pathlib import Path
import sqlite3
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def sql(name):
    return Environment().from_string((ROOT / 'dbt/tests' / name).read_text()).render(ref=lambda n: n)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            create table dim_accounts (account_id text, account_type text);
            create table fct_transactions (transaction_id text, account_id text);
            insert into dim_accounts values ('a', 'current'), ('b', 'savings');
            insert into fct_transactions values ('t1', 'a'), ('t2', 'b');
            create table monthly_transaction_summary (
                transaction_month text, currency text, transaction_count integer,
                debit_total numeric, credit_total numeric, net_outflow numeric);
            create table monthly_transaction_summary_by_account_type (
                transaction_month text, currency text, account_type text,
                transaction_count integer, debit_total numeric,
                credit_total numeric, net_outflow numeric);
            insert into monthly_transaction_summary values
                ('2026-04-01', 'GBP', 3, 150, 20, 130);
            insert into monthly_transaction_summary_by_account_type values
                ('2026-04-01', 'GBP', 'current', 2, 100, 20, 80),
                ('2026-04-01', 'GBP', 'savings', 1, 50, 0, 50);
        ''')

    def failures(self, name):
        return self.db.execute(sql(name)).fetchall()

    def test_valid_join_grain_and_rollup(self):
        for name in ('account_type_join_cardinality.sql', 'month_account_type_unique.sql',
                     'monthly_account_type_reconciliation.sql'):
            self.assertEqual(self.failures(name), [])

    def test_missing_and_duplicate_matches_cannot_cancel(self):
        self.db.execute("delete from dim_accounts where account_id = 'b'")
        self.db.execute("insert into dim_accounts values ('a', 'current')")
        self.assertEqual(set(self.failures('account_type_join_cardinality.sql')), {('t1',), ('t2',)})

    def test_duplicate_grain(self):
        self.db.execute('insert into monthly_transaction_summary_by_account_type select * from monthly_transaction_summary_by_account_type limit 1')
        self.assertTrue(self.failures('month_account_type_unique.sql'))

    def test_missing_or_unexpected_groups(self):
        self.db.execute("delete from monthly_transaction_summary_by_account_type")
        self.assertTrue(self.failures('monthly_account_type_reconciliation.sql'))
        self.db.execute("insert into monthly_transaction_summary_by_account_type values ('2026-05-01', 'GBP', 'current', 3, 150, 20, 130)")
        self.assertEqual(len(self.failures('monthly_account_type_reconciliation.sql')), 2)

    def test_each_measure_mismatch_and_null(self):
        for field in ('transaction_count', 'debit_total', 'credit_total', 'net_outflow'):
            for expression in (field + ' + 1', 'NULL'):
                with self.subTest(field=field, expression=expression):
                    self.db.execute('savepoint change')
                    self.db.execute(f'update monthly_transaction_summary_by_account_type set {field} = {expression}')
                    self.assertTrue(self.failures('monthly_account_type_reconciliation.sql'))
                    self.db.execute('rollback to change')
                    self.db.execute('release change')


if __name__ == '__main__':
    unittest.main()
