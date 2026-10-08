# Frozen synthetic banking-v2 input

`accounts.csv` is the sole data fixture required by the banking-v2 transaction
generator and accounts loader. It is an exact byte copy of the original
`data_snapshots/banking-v1/accounts.csv`, also identical to the original
`output/accounts.csv`. SHA256SUMS records its checksum:
`77978fdca0ff97e336e090f549e96d1e00158f1d266253406df5e414afbdeb12`.

## Provenance and content review

The original project uses Spoof configurations in configs/, grouped by
bundles/banking_bundle.json. configs/accounts.json specifies 2,000 synthetic
accounts with seed 1234: generated UUID account IDs, cached generated customer
UUIDs, current/savings/credit categories, low_spender/normal/high_spender
labels, independently generated balance in 0–10,000, and opening timestamps.
configs/customers.json specifies 1,000 generated UUID customer IDs. The frozen
account references all belong to that original synthetic customer file.

Review verified the six-column header, 2,000 unique canonical UUID account IDs,
1,000 distinct canonical UUID customer references, category vocabularies,
numeric balance range, and explicit UTC opening timestamps against the local
frozen manifest and configurations. Only UUIDs, labels, numeric text and
timestamps occur; no customer names, emails, credentials or private-key
contents are included. No customer email values were displayed in review.
The historical generation invocation was not independently replayed: this
fixture preserves its verified bytes, rather than claiming that rerunning
Spoof today would reproduce the timestamp-dependent UUIDs/opening timestamps.

Balance is retained only for exact raw accounts ingestion. It has no ledger
or as-of meaning and is excluded from analytical models. Customer UUIDs remain
necessary because they are required columns of that ingestion contract.

## Minimal dependency manifest

The transaction algorithm consumes only account_id and the UTC opening date.
The accounts loader consumes all six columns. The original four-file snapshot
manifest also covered customers, cards and old v1 transactions, but these were
not consumed by either operation. They are deliberately not included in Git,
and the revised SHA256SUMS requires exactly accounts.csv. Original ignored
snapshots and outputs remain untouched.

New generation metadata records only this accounts hash. The transaction
loader also recognizes the exact historical four-hash metadata mapping pinned
in its code, requiring the same verified account hash and validating the
transaction CSV hash and all transaction business rules. Historical hashes
for omitted files are provenance records, not claims that their files are
still verified or required. No arbitrary extra metadata hashes are accepted.

Transaction RNG, IDs, date rules, pence arithmetic and CSV serialization are
unchanged. Generator version 2 denotes the input packaging change; metadata
bytes change, but the transaction CSV reproduces exactly:
`119498f5d5fbc3dde9f3da8fee4e3b7e45e89ee0bd453a877d31cf62c68f0f74`.

Treat the fixture as immutable. Do not regenerate parent accounts to recreate
v2 output. .gitattributes disables Git newline conversion for this CSV so its
checksum survives checkout. See [fresh-clone setup](../../docs/fresh-clone-banking.md)
for setup and verification.
