"""Batch generation, atomic local transitions and independent Decimal reconciliation."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_transaction_batch as generator
import transaction_batch_state as engine
from generate_transactions_v2 import COLUMNS, FIXTURE_DIR, OUTPUT_DIR, validate_dataset


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = engine.baseline_state()
        cls.delivery = generator.generate_delivery(cls.baseline)
        cls.after, cls.result = engine.apply_delivery(cls.baseline, cls.delivery)

    def subset(self, records, batch_id='test-delivery'):
        delivery = deepcopy(self.delivery)
        delivery.update(batch_id=batch_id, records=deepcopy(records))
        return engine.seal_delivery(delivery)

    def reject_unchanged(self, delivery, state=None):
        if state is None:
            state = deepcopy(self.baseline)
        snapshot = deepcopy(state)
        with self.assertRaises((engine.BatchError, ValueError)):
            engine.apply_delivery(state, delivery)
        self.assertEqual(state, snapshot)

    def test_deterministic_bytes_and_selection(self):
        rebuilt = generator.generate_delivery(self.baseline)
        self.assertEqual(generator.delivery_bytes(rebuilt), generator.delivery_bytes(self.delivery))
        self.assertEqual(self.delivery['record_count'], 120)
        self.assertEqual(self.delivery['source_version_counts'], {'1': 100, '2': 20})
        expected = sorted(r['transaction_id'] for r in self.baseline.records.values()
                          if r['status'] == 'pending' and r['transaction_type'] == 'payment')[:20]
        self.assertEqual([r['transaction_id'] for r in self.delivery['records'][100:]], expected)
        for row in self.delivery['records'][:100]:
            self.assertNotIn(row['transaction_id'], self.baseline.records)
            self.assertEqual(row['transaction_date'], '2026-09-30')
            self.assertEqual(row['source_updated_at'], generator.SOURCE_UPDATED_AT)

    def test_insert_update_and_isolation(self):
        self.assertEqual({k: self.result[k] for k in ('inserted','updated','unchanged','stale')},
                         dict(inserted=100, updated=20, unchanged=0, stale=0))
        self.assertEqual(len(self.after.records), 10100)
        self.assertEqual(len(self.baseline.records), 10000)
        self.assertEqual(self.baseline.batches, {})
        for update in self.delivery['records'][100:]:
            old = self.baseline.records[update['transaction_id']]
            self.assertEqual(old['status'], 'pending')
            self.assertEqual(self.after.records[update['transaction_id']]['status'], 'completed')
            self.assertTrue(all(old[k] == update[k] for k in COLUMNS if k != 'status'))
        candidate, _ = engine.apply_delivery(self.baseline, self.delivery)
        candidate.records[self.delivery['records'][0]['transaction_id']]['amount'] = '1.00'
        self.assertNotEqual(candidate.records, self.after.records)
        self.assertNotEqual(candidate.records[self.delivery['records'][0]['transaction_id']]['amount'],
                            self.delivery['records'][0]['amount'])

    def test_batch_and_row_replay(self):
        replayed, result = engine.apply_delivery(self.after, self.delivery)
        self.assertEqual(replayed, self.after)
        self.assertTrue(result['already_applied'])
        self.assertEqual(len(replayed.batches), 1)
        redelivery = self.subset(self.delivery['records'], 'banking-batch-003')
        new_state, result = engine.apply_delivery(self.after, redelivery)
        self.assertEqual(new_state.records, self.after.records)
        self.assertEqual(result['unchanged'], 120)
        self.assertEqual((result['inserted'], result['updated'], result['stale']), (0, 0, 0))
        self.assertEqual(len(new_state.batches), 2)

    def test_stale_cannot_undo_completion(self):
        old = self.baseline.records[self.delivery['records'][100]['transaction_id']]
        state, result = engine.apply_delivery(self.after, self.subset([old], 'stale-delivery'))
        self.assertEqual(state.records, self.after.records)
        self.assertEqual(result['stale'], 1)
        self.assertEqual(state.batches['stale-delivery']['stale'], 1)

    def test_reused_batch_id_conflict(self):
        changed = deepcopy(self.delivery)
        changed['records'][0]['amount'] = '1.00'
        self.reject_unchanged(engine.seal_delivery(changed), deepcopy(self.after))

    def test_equal_version_business_or_timestamp_conflicts(self):
        for field, value in (('amount', '1.00'), ('source_updated_at', '2026-10-02T00:00:00Z')):
            with self.subTest(field=field):
                row = dict(self.delivery['records'][0], **{field: value})
                self.reject_unchanged(self.subset([row]), deepcopy(self.after))

    def test_version_gaps_new_version_and_transitions(self):
        update = self.delivery['records'][100]
        cases = [dict(update, source_version=3), dict(update, status='failed'),
                 dict(update, amount='1.00'),
                 dict(update, source_updated_at=engine.BASELINE_WATERMARK),
                 dict(self.delivery['records'][0], source_version=2),
                 dict(self.delivery['records'][0], status='pending')]
        for row in cases:
            with self.subTest(row_version=row['source_version'], status=row['status']):
                self.reject_unchanged(self.subset([row]))
        completed = next(r for r in self.baseline.records.values()
                         if r['status'] == 'completed' and r['transaction_type'] == 'payment')
        self.reject_unchanged(self.subset([dict(completed, source_version=2,
                              source_updated_at=generator.SOURCE_UPDATED_AT)]))

    def test_invalid_fields_and_duplicate_ids(self):
        row = self.delivery['records'][0]
        for field, value in (
            ('account_id', '00000000-0000-0000-0000-000000000000'), ('transaction_id', 'bad'),
            ('amount', 'NaN'), ('amount', '0.00'), ('amount', '500.01'), ('amount', '1.1'),
            ('transaction_date', '2026-02-30'), ('transaction_date', '2026-04-20'),
            ('transaction_date', '2026-10-01'), ('currency', 'USD'), ('direction', 'credit'),
            ('transaction_type', 'refund'), ('merchant_category', 'unknown'), ('status', 'unknown'),
            ('original_transaction_id', row['transaction_id']), ('source_version', True),
            ('source_version', 0), ('source_version', '1'), ('source_updated_at', '2026-10-01'),
            ('source_updated_at', '2026-09-29T00:00:00Z'),
        ):
            with self.subTest(field=field, value=value):
                self.reject_unchanged(self.subset([dict(row, **{field:value})]))
        self.reject_unchanged(self.subset([row, row]))
        missing = dict(row)
        del missing['currency']
        self.reject_unchanged(self.subset([missing]))
        self.reject_unchanged(self.subset([dict(row, unexpected='value')]))

    def test_envelope_hash_counts_and_provenance(self):
        for field, value in (('batch_id', 'invalid id'), ('baseline_sha256', '0'*64),
                             ('accounts_sha256', '0'*64), ('generator_version', '2'),
                             ('seed', True)):
            self.reject_unchanged(engine.seal_delivery(dict(self.delivery, **{field:value})))
        for field, value in (('content_sha256', '0'*64), ('record_count', 1),
                             ('source_version_counts', {'1':120}),
                             ('source_version_counts', {'1':True, '2':20})):
            altered = deepcopy(self.delivery)
            altered[field] = value
            if field != 'content_sha256': altered['content_sha256'] = engine.content_hash(altered)
            self.reject_unchanged(altered)
        altered = deepcopy(self.delivery)
        altered['records'][0]['amount'] = '1.00'
        self.reject_unchanged(altered)
        self.reject_unchanged(self.subset([]))

    def test_failure_after_valid_records_is_atomic(self):
        # The last record passes field validation but fails a state transition,
        # after 100 inserts and 19 updates have been applied to the private copy.
        altered = deepcopy(self.delivery)
        altered['records'][-1]['amount'] = '1.00'
        self.reject_unchanged(engine.seal_delivery(altered))
        altered['records'][-1]['amount'] = 'NaN'
        self.reject_unchanged(engine.seal_delivery(altered))

    def test_files_roundtrip_overwrite_and_tampering(self):
        protected = [FIXTURE_DIR/'accounts.csv', FIXTURE_DIR/'SHA256SUMS',
                     OUTPUT_DIR/'transactions.csv', OUTPUT_DIR/'generation.json']
        before = {p:p.read_bytes() for p in protected}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root/'a', root/'b'
            generator.write_delivery(self.delivery, a, self.baseline)
            generator.write_delivery(self.delivery, b, self.baseline)
            self.assertEqual((a/'delivery.json').read_bytes(), (b/'delivery.json').read_bytes())
            self.assertEqual((a/'SHA256SUMS').read_bytes(), (b/'SHA256SUMS').read_bytes())
            self.assertEqual(generator.read_delivery(a, self.baseline), self.delivery)
            with self.assertRaises(FileExistsError):
                generator.write_delivery(self.delivery, a, self.baseline)
            (a/'delivery.json').write_bytes((a/'delivery.json').read_bytes()+b' ')
            with self.assertRaises(engine.BatchError): generator.read_delivery(a, self.baseline)
        self.assertEqual(before, {p:p.read_bytes() for p in protected})
        baseline_rows = [{k:r[k] for k in COLUMNS} for r in self.baseline.records.values()]
        validate_dataset(baseline_rows, self.baseline.accounts)
        final_rows = [{k:r[k] for k in COLUMNS} for r in self.after.records.values()]
        with self.assertRaisesRegex(ValueError, '10,000'):
            validate_dataset(final_rows, self.baseline.accounts)

    def test_exact_counts_decimal_amounts_and_monthly_reconciliation(self):
        report = generator.reconcile_exercise(self.baseline, self.after, self.delivery, self.result)
        self.assertEqual(report['after'], engine.summarize(self.after.records))
        corrupt = deepcopy(self.after)
        corrupt.records[self.delivery['records'][0]['transaction_id']]['amount'] = '1.00'
        with self.assertRaises(engine.BatchError):
            generator.reconcile_exercise(self.baseline, corrupt, self.delivery, self.result)
        before, after = engine.summarize(self.baseline.records), engine.summarize(self.after.records)
        self.assertEqual(before['statuses'], {'completed':9000, 'pending':700, 'failed':300})
        self.assertEqual(after['statuses'], {'completed':9120, 'pending':680, 'failed':300})
        self.assertEqual(after['unique_transactions'], 10100)
        inserted = sum((Decimal(r['amount']) for r in self.delivery['records'][:100]), Decimal('0.00'))
        updated = sum((Decimal(r['amount']) for r in self.delivery['records'][100:]), Decimal('0.00'))
        completed_debit = ('GBP','completed','debit')
        self.assertEqual(before['amounts'][completed_debit], Decimal('2012092.38'))
        self.assertEqual(after['amounts'][completed_debit]-before['amounts'][completed_debit], inserted+updated)
        self.assertEqual(before['amounts'][('GBP','completed','credit')], Decimal('226623.07'))
        for key, amount in before['amounts'].items():
            if key == completed_debit: expected = amount+inserted+updated
            elif key == ('GBP','pending','debit'): expected = amount-updated
            else: expected = amount
            self.assertEqual(after['amounts'][key], expected)
        self.assertEqual(sum(after['amounts'].values())-sum(before['amounts'].values()), inserted)
        # Independently apply per-delivery deltas to the prior monthly result.
        expected = deepcopy(before['monthly'])
        for row in self.delivery['records']:
            group = expected[(row['transaction_date'][:7]+'-01', row['currency'])]
            group['transaction_count'] += 1
            group['debit_total'] += Decimal(row['amount'])
            group['net_outflow'] += Decimal(row['amount'])
        self.assertEqual(after['monthly'], expected)
        # Fresh independent aggregation, without summarize or delivery deltas.
        fresh = {}
        for month, currency in expected:
            rows = [r for r in self.after.records.values() if r['status']=='completed'
                    and r['transaction_date'].startswith(month[:7]) and r['currency']==currency]
            debit = sum((Decimal(r['amount']) for r in rows if r['direction']=='debit'), Decimal('0.00'))
            credit = sum((Decimal(r['amount']) for r in rows if r['direction']=='credit'), Decimal('0.00'))
            fresh[(month,currency)] = dict(transaction_count=len(rows), debit_total=debit,
                                           credit_total=credit, net_outflow=debit-credit)
        self.assertEqual(after['monthly'], fresh)
        self.assertEqual(sum(g['transaction_count'] for g in fresh.values()), 9120)
        self.assertEqual(sum(g['net_outflow'] for g in fresh.values()),
                         Decimal('1785469.31')+inserted+updated)


if __name__ == '__main__':
    unittest.main()
