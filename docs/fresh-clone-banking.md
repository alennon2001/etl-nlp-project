# Reproduce the banking pipeline from a fresh clone

## Required input

Only fixtures/banking-v2/accounts.csv is needed. This immutable synthetic file
retains the original account/customer UUIDs, categories, raw balance text and
opening timestamps. Its SHA256SUMS and provenance README are tracked alongside
it. The generator uses account IDs/opening dates; the accounts loader needs
all six columns. No customer email file, cards or old transactions are needed.

The former four-file snapshot verification was broader than the actual input
dependency. The revised manifest requires exactly accounts.csv and verifies
its bytes before parsing. Transaction metadata must match either that manifest
or the exact pinned historical four-hash mapping with the same account hash.
CSV hash and complete business-rule validation remain mandatory. Legacy omitted
file hashes identify historical provenance; their file contents are no longer
runtime verification dependencies. Existing ignored snapshots and outputs are
not migrated or rewritten.

## Fresh-clone local commands

Install uv and Git first, then clone this repository and change into its root.
Use Python 3.12.13 as pinned by .python-version and the locked dependencies:

```sh
git clone <repository-url> etl-nlp-project
cd etl-nlp-project
uv sync --locked
uv run python scripts/generate_transactions_v2.py
uv run python scripts/load_accounts_snowflake.py --validate-only
uv run python scripts/load_transactions_snowflake.py --validate-only
uv run python -m unittest discover -s tests -v
```

Replace `<repository-url>` with the actual clone URL. Generation creates ignored
output/banking-v2/transactions.csv and generation.json and refuses to overwrite
an existing output directory. On an existing checkout, use validate-only;
do not delete or regenerate working datasets to test reproduction.

Expected transaction CSV SHA-256:
`119498f5d5fbc3dde9f3da8fee4e3b7e45e89ee0bd453a877d31cf62c68f0f74`.
The committed reproduction test independently generates in temporary storage
and checks this digest. Metadata includes the revised input set and generator
hash/version, so generation.json itself is not expected to be byte-identical
to historical metadata.

## Separate Snowflake setup

Local generation/validation requires no Snowflake credentials or connection.
For database execution, provision your own Snowflake account/user, encrypted
private key and permissions outside Git. The existing loader convention
requires BANKING_DEVELOPER, BANKING_DEV_WH and BANKING_ANALYTICS. An administrator
must arrange these objects/permissions and register your public key; the raw
table files do not provision users or authentication.

Configure ~/.dbt/profiles.yml with profile etl_project and output snowflake_dev,
type snowflake, your account/user, role BANKING_DEVELOPER, warehouse
BANKING_DEV_WH, database BANKING_ANALYTICS, your own target schema and
private_key_path. Use the existing dbt passphrase setting:
`private_key_passphrase: "{{ env_var('DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE') }}"`.
Keep profile values, keys and passphrases out of Git. Do not copy another
user's private key or profile. Loader authentication prompts privately and
does not evaluate the dbt passphrase environment reference.

In your Snowflake worksheet, run the non-destructive raw definitions:

1. sql/snowflake/02_raw_transactions.sql
2. sql/snowflake/03_raw_accounts.sql

Then, from the project root, run interactively:

```sh
uv run python scripts/load_accounts_snowflake.py
uv run python scripts/load_transactions_snowflake.py
```

Loaders refuse populated/incompatible tables; they never reset an existing
environment. They insert transactionally and reconcile before commit. Ensure
the role can read raw data and create the target dbt schemas/views.

Run the full project with the existing zsh workflow:

```zsh
(
  read -rs 'DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE?Private key passphrase: '
  printf '\n'
  export DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  uv run dbt build --project-dir dbt --profiles-dir "$HOME/.dbt" \
    --target snowflake_dev
)
```

This selects all active models/tests, including source tests. Analyses are
saved queries, not additional built models. Examine run_results.json to
confirm your actual database outcomes.

## Local verification of this change

A temporary clean directory was populated from Git-tracked working-tree
files plus the proposed new files, excluding .git, ignored snapshots,
ignored output, profiles and keys. Before generation it contained neither
data_snapshots nor output. Generation there reproduced the existing v2 CSV
byte-for-byte, including IDs, account links, dates and amounts. Both loader
validate-only entry points passed with profile reading, passphrase prompting
and connection methods patched to fail if invoked. Relevant local unit tests
passed in both the working directory and clean directory.

The existing ignored CSVs, manifest, generation metadata and snapshots were
checked for unchanged hashes afterward. No warehouse connection, database
build, staging, commit or push occurred. Dependency installation was not
repeated: the isolated checkout used the existing locked Python environment.
A new machine still needs uv/Python and network/package access for uv sync.
Live authentication, grants and Snowflake execution remain user-specific and
were not verified by this reproduction test. Exact CSV reproduction is
verified on the project's pinned Python runtime, not every Python version.
