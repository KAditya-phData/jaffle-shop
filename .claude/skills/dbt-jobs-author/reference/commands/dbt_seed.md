# dbt seed

**Aliases:** seed

## What it does

Loads CSV files located in the project's configured seed-paths into the data warehouse as tables, via INSERT statements. On a normal (non-full-refresh) run, if the table already exists and its schema matches the CSV, dbt truncates the table and reinserts the rows; if the table doesn't exist yet, it creates it. This is typically used for small, static, reference/lookup datasets (e.g. country codes, mappings) that are checked into the dbt project as version-controlled files rather than sourced from a production data system.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

dbt seed writes real tables and rows into the warehouse: it creates/truncates a table per CSV file and inserts the file's rows. With --full-refresh it drops (drop cascade) and rebuilds the table, which can cascade-drop downstream dependent objects (views) that reference it. This is NOT limited to local artifacts (target/*.json) or metadata -- it is a genuine warehouse-data-mutating command, similar in kind to dbt run for models, just backed by CSV inputs instead of SQL transformation logic.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no - unlike 'Generate docs on run' or 'Run source freshness', dbt seed is NOT a dbt Cloud job checkbox/toggle. It is added the same way as dbt run/dbt test: as an explicit command in the job's execute_steps / Commands list (or implicitly included when the step is 'dbt build', which runs seeds+models+tests+snapshots together).
- **Notes:** Include it as a job step only if the project actually has seed files that need loading/refreshing as part of that job's run (e.g. a job that depends on reference/lookup CSV data). Many projects seed once manually or in a separate setup job and never need it in every scheduled run.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| resource selection (which seeds, if not all) | `ask_user` | Ask whether the job should seed everything (bare 'dbt seed') or only specific seed files/tags via --select. Agent cannot infer which seeds belong to a given job's scope without being told. |
| full-refresh requirement | `ask_user` | Whether the seed's schema changes over time (new/renamed columns) or downstream views depend on it determines if --full-refresh is needed. Must ask; defaulting to full-refresh on every run is unnecessary churn, defaulting to never can break on schema drift. |
| job/command chain position | `have` | Agent knows seed commands conventionally run early in a job (before run/build) since models may reference seeded tables as sources. |
| account/project/environment IDs for the job definition | `memory` | Standard dbt-jobs-as-code job-level fields (account_id, project_id, environment_id) come from stored config/memory, not re-asked per command. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Restrict the seed operation to specific seed files, tags, or paths instead of loading every seed in the project.
- **Data effect:** Still writes warehouse data (create/truncate + insert), just scoped to fewer tables; does not change the write nature, only its extent.
- **Info needed:** Must ask the user which seed(s) or tag(s) matter for this job, since seed names are project-specific and the agent has no way to infer intent from a generic request.
- **When to include:** Include when the job should only touch a subset of reference data (e.g. one CSV changed) or to keep the job fast/scoped; omit (run bare dbt seed) when the job's purpose is a full reference-data refresh and the project has few/small seeds.
- **Good vs bad:** Good: `dbt seed --select country_codes` for a job that only owns that lookup table. Bad: omitting --select in a large multi-team project causes the job to reload every team's seeds, risking unrelated table locks/downtime.

### `--exclude`
- **Purpose:** Removes specific seeds/tags from the selected set (same semantics as --exclude for run/build).
- **Data effect:** Reduces which tables get written; same write nature as base command, just narrower.
- **Info needed:** Ask the user which seeds to exclude if they want 'everything except X' behavior; otherwise not needed.
- **When to include:** Include only when the ask is naturally 'all seeds except this one' rather than a positive include list; --select is usually clearer and preferred for job-as-code specs.
- **Good vs bad:** Good: `dbt seed --exclude legacy_lookup` to skip a deprecated seed while still loading everything else. Bad: chaining many --exclude tags instead of just writing a positive --select list, making the job spec harder to read and reason about.

### `--full-refresh / -f`
- **Purpose:** Forces dbt to drop and rebuild the seed table from scratch rather than truncate+reinsert, needed when the CSV's column structure (names/types/count) has changed.
- **Data effect:** More destructive write: performs a drop cascade of the existing table before recreating it, which can cascade-drop downstream views/objects built on top of that seed table -- a stronger warehouse-write effect than the default truncate+insert.
- **Info needed:** Ask the user: has the seed's schema changed, or do they run this periodically to guard against drift? Also confirm whether downstream objects depend on the seed table (cascade-drop risk) before defaulting this on for a recurring scheduled job.
- **When to include:** Include for a one-off/manual run after changing a seed's columns, or in a low-risk dev/CI job; avoid as a default on every scheduled production run since the drop-cascade can break downstream dependent views unexpectedly and adds unnecessary rebuild cost when the schema hasn't changed.
- **Good vs bad:** Good: run `dbt seed --full-refresh` manually/once right after adding a column to a seed CSV. Bad: baking --full-refresh into a nightly scheduled job by default, causing unnecessary drop-cascade churn and potential downstream view breakage every night.

## Best practices

- **Only include dbt seed in a scheduled job when that job actually owns/depends on the seed data changing on that cadence; otherwise seed once (manually or in a dedicated setup job) and let scheduled jobs skip it.**
  - Why: Seeds are typically static reference data -- reloading them on every scheduled run wastes warehouse compute/time and risks lock contention on tables that rarely change.
- **Scope seed steps with --select to the specific seed file(s)/tags relevant to the job rather than running a bare dbt seed across the whole project.**
  - Why: A bare dbt seed reloads every seed in the repo, which can affect tables owned by other teams/jobs and increases blast radius and runtime unnecessarily.

## Anti-patterns

- **Defaulting --full-refresh on for dbt seed in every scheduled/CI run.**
  - Why: --full-refresh drop-cascades the seed table, which can silently break downstream views/objects that depend on it -- an unnecessary destructive operation when the CSV schema hasn't actually changed.
- **Using dbt seed as a way to load large or frequently-changing datasets into the warehouse on a recurring job.**
  - Why: Seed is designed for small, mostly-static CSVs checked into the dbt repo; using it for sizeable or fast-changing data bloats the git repo, slows CI, and is not a substitute for a proper ingestion/EL tool or source table.

## Overlaps with

- dbt build (runs seeds + models + tests + snapshots together, sharing flags like --full-refresh and --select across all resource types)
- dbt run (models may depend on seeded tables as sources; ordering matters -- seed typically runs before run)
- dbt test (tests can be defined on seeds, so a seed step often precedes a test step that validates the seeded data)
- dbt run-operation (sometimes used as an alternative/companion to seed for more complex reference-data loading logic)
