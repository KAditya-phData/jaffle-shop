# dbt deps

## What it does

Resolves and installs the package dependencies declared in packages.yml (or dependencies.yml), pulling them from dbt Hub, git, or local paths. It writes/updates a package-lock.yml for reproducible installs and downloads the packages into the local dbt_packages/ directory. It is purely a local project-setup step: it does not compile, run, or query the warehouse in any way.

## Effect on warehouse data

**Classification:** `writes-artifacts-only`

dbt deps only writes local files: it populates the dbt_packages/ directory with downloaded package code and writes/updates package-lock.yml. It makes no database connection and never reads or writes tables/views/rows in the warehouse.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** no
- **Available as a job parameter/toggle instead:** No explicit toggle exists, but dbt Cloud runs it automatically and implicitly for every job invocation, before the configured command steps (and alongside the repo-clone/connect built-in steps).
- **Notes:** Per dbt docs (docs.getdbt.com/docs/deploy/job-commands): 'Every job invocation automatically includes the dbt deps command,' so it does not need to be added to the job's execute_steps/Commands list. Adding it explicitly just runs it twice (redundant, not harmful). dbt-jobs-as-code examples correspondingly omit it from execute_steps.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| whether to include as an explicit step | `have` | Default answer is no - dbt Cloud auto-runs it before every job. Only add explicitly if the user wants to force a mid-job package refresh, or is running dbt Core outside dbt Cloud (e.g. self-hosted CI) where the automatic behavior does not apply. |
| packages.yml / dependencies.yml contents | `have` | Lives in the dbt project repo itself; not something the job-author agent configures or needs to ask about. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Best practices

- **Omit dbt deps from the execute_steps list entirely and let dbt Cloud's automatic pre-step handle it**
  - Why: dbt Cloud already runs it before any configured commands on every invocation, so adding it manually just duplicates work and clutters the job YAML.
- **Commit package-lock.yml to version control**
  - Why: Guarantees the exact same package versions are resolved and installed on every job run, avoiding drift or surprise breakage from upstream package updates.

## Anti-patterns

- **Adding 'dbt deps' as an explicit command step in a dbt Cloud job**
  - Why: It's redundant - dbt Cloud already runs it automatically as a chained pre-step before your configured commands, so it just wastes a step slot and run time.
- **Using dbt deps --upgrade routinely inside a scheduled production job**
  - Why: It bypasses the pinned package-lock.yml and can silently pull newer, untested package versions into a production run, risking unexpected model/macro behavior changes outside of code review.

## Overlaps with

- dbt run
- dbt build
- dbt debug (validates git/dependency setup)
- dbt clean
