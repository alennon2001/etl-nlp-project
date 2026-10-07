# Archived dbt models

These are preserved copies of the original starter examples and unfinished
banking marts, moved out of `dbt/models/` to prepare the transaction-first
Snowflake flow. Their contents were not changed.

This directory is outside every active dbt resource path. The banking models
still have missing staging dependencies and known calculation issues; the
starter example contains an intentional null that fails its not-null test.
Use these files as references, not runnable production models.
