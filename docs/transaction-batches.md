# Second transaction batch: local learning design

Status: local generator, copy-on-write state engine, replay tests and exact
reconciliation are implemented. Database loading remains future work.
The original banking-v2 generator, strict validator and Snowflake loaders are
unchanged. This exercise does not update any warehouse or baseline dbt model.

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

Implemented code: scripts/generate_transaction_batch.py and
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

## Implemented local interface

Run the temporary demonstration from the project root after the original v2
output has been generated:

```sh
uv run --locked python scripts/generate_transaction_batch.py
uv run --locked python -m unittest discover -s tests -v
```

The default demonstration creates and removes a TemporaryDirectory. An optional
`--output-dir` may retain a delivery in a **new** directory, for example beneath
ignored output/transaction-batches/. Existing directories are refused. All
tests use temporary storage. No new code imports Snowflake, either loader,
credentials or profile handling. CI runs discovery of all tests and the
temporary demonstration after generating/validating the original baseline.
CI itself has not been remotely executed by the agent.

`baseline_state()` verifies the canonical baseline CSV hash and account fixture
manifest, then calls the unchanged strict validate_dataset() on exactly
10,000 original rows. It assigns the simulation watermark/version in memory.
The 10,100-row resulting state is separate: the baseline validator still
rejects it. Baseline generation metadata and all input/output files stay intact.

`generate_delivery(state)` creates UUID5 IDs in the separate namespace
`etl-nlp-project/transaction-batches`, with names
`banking-batch-002:payment:1` through `:100`. Random draws use seed 1234, sorted
accounts and the existing category order. It then copies the first 20 pending
payments sorted by transaction_id, changing only status and source metadata.

The JSON envelope contains the batch_id, baseline and accounts hashes,
generator_version, seed, record count and source-version counts, records with
all ten unchanged business field names plus source_version/source_updated_at,
and content_sha256. Batch identity is shared envelope metadata rather than
repeated in each record. New amounts remain two-decimal strings generated from
integer pence. The content hash covers the entire canonical JSON envelope
excluding only content_sha256, so identity, provenance, counts and source
metadata are bound to the records. A SHA256SUMS beside delivery.json additionally
verifies its exact formatted file bytes before JSON parsing. Hashes detect
changes; they are not cryptographic authentication of a remote sender.

`apply_delivery(state, delivery)` returns a separate LocalState and result.
Complete envelope/field validation occurs first. Transition checks then apply
to a deep copy; even a conflict in the last record after earlier valid changes
cannot mutate the original records or ledger. Callers publish both together
by accepting the returned state only after success. The successful ledger
entry includes content hash and inserted/updated/unchanged/stale counts.
There is no on-disk state persistence, lock, database transaction or concurrent
writer guarantee. Delivery files are exclusively created, not a durable
transactional database ledger.

The reusable engine accepts smaller nonempty deliveries for replay/stale/error
exercises. Only generation of batch 002 enforces the exact 100/20 allocation.
It rejects non-payment deliveries, malformed business fields, unknown accounts,
event dates outside the existing inclusive window/account opening date,
invalid source versions and non-UTC/noncanonical source timestamp text.
New IDs must be version 1 completed September 30 payments. Existing IDs may
advance exactly one version only from pending to completed, with every other
business field unchanged and a later source timestamp. An older source version
is counted as stale and ignored, not allowed to reverse completion.

## One insert, one update and one replay

The first new record is transaction
`7775aae3-354a-5e6f-84dd-df8fb2c02b50`, a GBP 77.57 completed debit/payment
dated September 30, 2026. It is absent from baseline, has source_version 1,
and is delivered at October 1, 2026 00:00 UTC. Application adds one record.

The first selected update is transaction
`0042e9e4-c28c-510c-890a-c9c8819e76d4`, a GBP 335.91 payment dated July 19,
2026. Baseline has pending/source_version 1; delivery has completed/version 2
with the fixed October 1 timestamp. Amount, account, event date and all other
business fields remain the same. Application replaces its version, adding
no transaction ID; July completed reporting gains the payment amount.

After application, reapplying banking-batch-002 with verified content hash
`f33609b651742ef5e4533d8077fec02e0c79823226b2eccb5b307d4ba701df55`
returns already_applied=true and the original ledger counts, not new inserts
or updates. Records and the one ledger entry are unchanged. The stored
100-insert/20-update counts describe the original application. Re-sealing the
same 120 records under banking-batch-003 exercises row-level replay: 120
unchanged records, zero inserts/updates/stale records, and one new ledger entry.
Reusing batch 002 with a different verified hash is rejected.

## Verified before/after results

All 32 local tests passed, including 12 batch tests. Checks cover deterministic
file bytes, sorted update selection, collisions, inserts/updates, both replay
levels, stale records, equal-version conflicts, version gaps and unsupported
transitions, malformed fields/provenance/hashes/counts, duplicate transaction
IDs, file tampering, overwrite refusal and atomic failure after valid records.
Original fixture, manifest, baseline CSV and generation metadata bytes are
checked unchanged, and the strict baseline validation is rerun.

The 100 new amounts total **GBP 22,263.96**. The 20 pending payments newly
completed total **GBP 4,010.75**. Consequently completed debit and net-outflow
totals each rise by exactly **GBP 26,274.71**. Pending debit amounts decrease
by GBP 4,010.75; all-attempt amounts increase only by GBP 22,263.96. Status
changes do not create a second financial record.

| Completed measure | Before | After |
| --- | ---: | ---: |
| Transaction count | 9,000 | 9,120 |
| Debit total (GBP) | 2,012,092.38 | 2,038,367.09 |
| Credit total (GBP) | 226,623.07 | 226,623.07 |
| Net outflow (GBP) | 1,785,469.31 | 1,811,744.02 |

Fresh completed-only aggregation of final state gives:

| Month (2026), GBP | Before count | After count | After debits | After credits | Before net outflow | After net outflow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| April | 472 | 474 | 110,961.17 | 418.17 | 110,502.33 | 110,543.00 |
| May | 1,585 | 1,589 | 387,560.74 | 7,330.00 | 378,967.22 | 380,230.74 |
| June | 1,575 | 1,579 | 376,891.71 | 18,134.39 | 357,993.97 | 358,757.32 |
| July | 1,728 | 1,730 | 399,031.99 | 36,690.20 | 361,989.24 | 362,341.79 |
| August | 1,726 | 1,729 | 380,593.98 | 49,872.98 | 330,301.80 | 330,721.00 |
| September | 1,914 | 2,019 | 383,327.50 | 114,177.33 | 245,714.75 | 269,150.17 |

All amount arithmetic uses Decimal, not floats. reconcile_exercise() asserts
status/unique-row counts, exact amounts by status/direction, unchanged credits
and incremental per-month deltas against a fresh final-state summary. Tests
also independently re-aggregate final rows and reconcile every month and
currency group. These are locally executed simulation results, not Snowflake
query results or proof of any database application.

Future database work still requires an explicitly authorized isolated target,
schema/audit design, durable ledger, concurrency strategy and recovery tests.
