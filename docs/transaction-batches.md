# Second transaction batch: local learning design

Status: design only. The generator, replay engine and database loading path
described below are not yet implemented.

## Goal

Extend our understanding from an initial load to recurring delivery:
insert new transactions, update the status of existing ones, and safely
replay a delivery. Idempotence means applying the same delivery again has
no additional effect on the resulting business state.

The first implementation is local and uses temporary state. Preserve the
banking-v2 CSV, fixture, hashes, original loaders and Snowflake tables.

## Concrete exercise

Use the verified banking-v2 dataset as the baseline:

| Measure | Baseline | After batch 002 |
| --- | ---: | ---: |
| Unique transactions | 10,000 | 10,100 |
| Completed attempts | 9,000 | 9,120 |
| Pending attempts | 700 | 680 |
| Failed attempts | 300 | 300 |

Batch 002 contains exactly 120 distinct transaction records:
- 100 new completed payment/debit records.
- 20 updates to existing pending payment/debit records, changing status to completed.

Updates preserve transaction_id and all other business fields. A status change
is another version of the same transaction, not a second financial event.

Select the 20 pending payments deterministically by sorting transaction_id.
Create new IDs with UUID5 using a separate batch-specific namespace/name,
and assert that they cannot collide with baseline IDs. Use fixed seed and
stable account ordering, positive integer-pence amounts, existing categories,
GBP and existing account IDs.

New payments use transaction_date 2026-09-30. The synthetic delivery occurs
at fixed source_updated_at 2026-10-01T00:00:00Z. This deliberately teaches a
later delivery of events within the existing reporting window. It does not
pretend to exercise October transaction reporting. Require each new payment
to occur on or after the referenced account's opening date.

The 20 status updates retain their original transaction dates. Consequently,
completed activity may change in older monthly summaries. This is reporting
by transaction-attempt date, not settlement date; a settlement-date report
would require additional source fields.

## Separate business fields from ingestion metadata

Keep the existing ten business columns. In the batch envelope add:
- batch_id: banking-batch-002.
- source_version: 1 for new IDs, 2 for updates to baseline IDs.
- source_updated_at: explicit timezone-aware synthetic source update time.

The local baseline state assigns source_version 1 and the baseline watermark
2026-09-30T23:59:59Z. That watermark is a simulation convention, not an observed
historical update time.

Use the source_version to order changes for the same transaction ID.
Do not use row order or local ingestion time to infer which state is newer.
Document the source-version contract as a training assumption; a real API
might provide a different ordering field or no such guarantee.

## Files and integrity

Proposed new code: scripts/generate_transaction_batch.py and
scripts/transaction_batch_state.py, with tests/test_transaction_batches.py.

Keep any generated delivery under a new ignored output directory, separate
from output/banking-v2. Metadata records the baseline CSV hash, account fixture
hash, generator version, batch ID, output hash, seed and record counts.
Refuse output overwrites. Generate and validate using temporary directories
in tests. Do not modify the original fixed 10,000-row validator to accept
arbitrary batches.

## Local state application rules

Validate the complete delivery before applying changes to a copy of state.
Publish the new state and successful batch entry together only after all
checks pass; a failure must leave both unchanged.

For each transaction:
- Reject duplicate transaction IDs within one delivery, even identical ones.
- Insert a previously unseen ID only at source_version 1 with valid fields.
- For an existing ID, same version and identical record is an unchanged replay.
- Same version with different business fields or update timestamp is a conflict.
- A lower version is stale and must not overwrite state; count it as stale.
- Accept the next version only for pending -> completed in this exercise.
  All other business fields must remain identical and source_updated_at must
  advance. Reject unsupported transitions or version gaps.

For a batch:
- Same batch_id and identical verified content hash returns an already-applied
  result without changing business state.
- Same batch_id with a different content hash is an error.
- Store the committed batch's hash and inserted/updated/unchanged/stale counts.
- Replaying identical records under a new batch ID must also leave business
  state unchanged, proving row-level replay safety as well as batch deduplication.

These in-memory/copy-on-write rules do not prove database atomicity or concurrent
writer safety. Those need a separate database implementation and verification.

## Acceptance checks

1. Generate exactly the same batch bytes twice from unchanged inputs.
2. Apply to baseline: 100 inserts, 20 updates, 10,100 unique IDs.
3. Check final status counts: 9,120 completed, 680 pending, 300 failed.
4. Replay batch 002: no state change, no extra successful ledger entry.
5. Re-deliver identical records under another batch ID: no extra business rows.
6. Reject a reused batch ID with changed contents.
7. Reject conflicting equal versions, duplicates within a batch, invalid
   account references, invalid dates/amounts and unsupported transitions.
8. Demonstrate stale versions cannot undo completion.
9. An invalid record after valid records must leave all state unchanged.
10. Preserve baseline files and all baseline checksums.

Reconcile exact Decimal totals. The increase in completed debit and net-outflow
totals equals the sum of 100 new payment amounts plus the amounts of the
20 newly completed payments. Completed credit total remains GBP 226,623.07.
Derive and assert the exact delta from the delivery; do not guess amounts.
Transaction-date monthly totals must match a fresh aggregation of final state.

## Learning sequence

1. Implement deterministic batch generation and explain one insert versus update.
2. Implement the local state transition function and replay tests.
3. Run the existing and new local tests through CI.
4. Review the before/after counts, amounts and per-month changes.
5. Design a separate Snowflake batch experiment only after local checks pass.

Before the database phase, agree on an isolated target and access settings,
version/audit columns, staging/deduplication, concurrent-writer behaviour and
recovery after uncertain commits. Keep DDL separate from transactional writes.
The original loaders intentionally refuse populated tables and must remain
available for reproducing the original baseline.

No Snowflake MERGE, new database objects or modifications to baseline dbt models
are authorized by executing this local exercise. Database execution will be a
separate explicit step.

## Out of scope for the first exercise

October event dates, partial refunds, account attribute history, new customers,
deletions, payment reversals, schema evolution, S3, APIs and scheduling.
These can be added once insert/update/replay semantics are understood.
