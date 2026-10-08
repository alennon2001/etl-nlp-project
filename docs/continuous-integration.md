# Local continuous integration

The [Banking local checks workflow](../.github/workflows/banking-local-checks.yml)
runs on pull requests targeting main, pushes to main, and manual dispatch once
the workflow is available on the default branch.

## What happens

GitHub starts a fresh Ubuntu 24.04 runner, checks out the code, installs uv
0.12.23 and the Python runtime from .python-version, and installs dependencies
with uv sync --locked. It then:

1. Checks installed package compatibility.
2. Generates the synthetic transactions from the committed accounts fixture.
3. Runs both loaders with --validate-only.
4. Runs the Python unittest suite, including the expected CSV SHA-256 check.
5. Checks that tracked files were not modified.

Generation precedes the test suite because some existing loader tests read
output/banking-v2. Generated CSVs remain temporary runner output and are not
committed or uploaded. Dependency caching is disabled so the initial workflow
also exercises a fresh installation.

## How to read the result

Open a pull request's Checks tab, select **Reproduce and validate banking data**,
and expand individual steps. A failed command fails the job; inspect the first
failed step. Dependency or runner failures are distinct from data/test failures.
A green check applies to that run's tested revision, not every future change.

The workflow uses a read-only repository token, does not persist checkout
credentials, and does not reference repository secrets. It calls only local
generation, validate-only entry points and tests. It does not configure a
Snowflake profile, load a database, run dbt build or deploy anything.

This check does not prove that the 66 Snowflake data tests pass. Those still
require a separately authenticated dbt build. It also does not enforce merge
blocking by itself: branch rules must explicitly require the status check
if that behaviour is desired. This change does not modify branch rules.

## Reproduce locally

From a fresh clone, follow the commands in
[fresh-clone setup](fresh-clone-banking.md). On an existing checkout with
output/banking-v2 already present, do not rerun the overwrite-refusing generator;
validate the existing output and run the test suite. The reproduction test
itself uses temporary storage.

## Maintenance

Third-party actions are pinned to reviewed commit SHAs. Update those pins and
the explicit uv version deliberately. The dependency lockfile and
.python-version control the project environment. The job has a 15-minute timeout
and cancels older runs for the same ref when a new one starts.
