# dbt run

## What it does

Executes compiled SQL for models only (not tests, seeds, snapshots, or sources) against the target database/warehouse, materializing them (view/table/incremental/etc.) per each model's config. Models execute in DAG dependency order using multi-threaded parallelism. It connects to and writes to the actual data warehouse.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

dbt run creates/replaces views and tables and inserts/merges/deletes rows in the target warehouse schemas per each model's materialization (table, view, incremental, etc.). This is a genuine warehouse write, not just a local artifact write. It does still produce local artifacts (run_results.json, manifest.json in target/) as a side effect, but its primary and defining effect is mutating warehouse objects. It is NOT read-only.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no - dbt run is a plain command step, not a dedicated checkbox/toggle. (Contrast with dbt docs generate, which has a 'Generate docs on run' checkbox, and dbt source freshness, which has a 'Run source freshness' checkbox.)
- **Notes:** dbt run is added as a command string in the job's command list (or dbt-jobs-as-code jobs.yml 'execute_steps'/'run_steps'), exactly like dbt build, dbt test, dbt seed, etc. Most dbt Cloud deploy jobs default to 'dbt build' instead, since build = run+test+seed+snapshot combined and covers freshness of testing in one DAG pass. dbt run alone is appropriate when the job author explicitly wants to separate model-building from testing (e.g., run then test as distinct steps for clearer failure isolation), or is maintaining a legacy job pattern predating dbt build. It cannot run in parallel with dbt build in the same invocation (both are write operations on the same target).

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| selection scope for this job (--select / --exclude or none = full project) | `ask_user` | Must ask which models/tags/paths this job should build unless the user already described it in the request (e.g. 'run the marts models nightly'). Never guess a broad default for a production job. |
| target / environment | `have` | In dbt Cloud, environment is chosen by which Environment the job is attached to (dev/staging/prod), not typically via a --target flag on the command line. This is set at the job/environment level, which the job-authoring flow already captures — do not also ask for --target unless the user explicitly wants a CLI override of the environment's default target. |
| account ID / project ID / environment ID for dbt-jobs-as-code | `memory` | Pull from stored project/account defaults (jobs.yml context, prior job specs) rather than asking every time, per this repo's existing job-authoring skill conventions. |
| whether full-refresh is needed | `ask_user` | This changes incremental model behavior destructively (full rebuild); must be explicit, should default to off/omitted for routine scheduled runs. |
| vars values | `ask_user` | Only needed if the project's models reference custom vars for this run; ask what values are needed, don't fabricate business dates/config. |
| threads | `memory` | Usually left at the environment/profile default; only override if user/org has a known standing preference (e.g. warehouse concurrency limits) captured in memory. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Restrict the run to a specified set of models via graph selection syntax (names, tags, paths, +/@ graph operators, resource type selectors).
- **Data effect:** Does not change read/write nature (still a warehouse write) but changes the SCOPE of what gets written - fewer/more warehouse objects touched.
- **Info needed:** Which models/tags this job targets. Must ask_user unless already specified in the natural-language request.
- **When to include:** Include whenever the job should not build the entire project (virtually all production scheduled jobs use --select for stability/cost). Omit only for full-project rebuild jobs.
- **Good vs bad:** Good: `--select tag:nightly` scoped to a clear tag keeps the job stable as models are added/removed. Bad: overly broad or fragile selectors (e.g. hardcoding dozens of model names) that silently drift from the intended set as the DAG evolves.

### `--exclude`
- **Purpose:** Removes specified models/tags/paths from an otherwise selected set (often combined with --select or used alone against the full project).
- **Data effect:** Same as --select - narrows the warehouse write scope, no change to read/write classification.
- **Info needed:** Which models to omit; ask_user if not stated.
- **When to include:** Include when there's a known subset to skip (e.g. long-running or WIP models) while otherwise running broadly.
- **Good vs bad:** Good: excluding a known slow/experimental model from a time-sensitive nightly job. Bad: using --exclude as a permanent patch for a broken model instead of fixing or properly re-scoping it - hides technical debt.

### `--target / -t`
- **Purpose:** Overrides which target (from profiles.yml, e.g. dev/prod connection details) dbt uses for this invocation.
- **Data effect:** No change to read/write classification, but determines WHICH warehouse/database/schema is written to - critical safety concern.
- **Info needed:** In dbt Cloud, target is governed by the job's Environment setting, not usually a manual CLI flag; if user explicitly wants a CLI-level override, ask_user which target and confirm it matches the intended environment to avoid writing to the wrong warehouse.
- **When to include:** Rarely included explicitly in dbt Cloud jobs since environment selection already sets this; include only for advanced/explicit override scenarios.
- **Good vs bad:** Good: leaving it unset and relying on the job's Environment binding (avoids accidental cross-environment writes). Bad: hardcoding --target prod in a job command, bypassing the environment abstraction and risking drift if environment connection details change.

### `--full-refresh / -f`
- **Purpose:** Forces incremental models to be dropped and rebuilt from scratch as if they were table models (is_incremental() macro returns false).
- **Data effect:** Warehouse write - and a heavier/destructive one: drops and fully rebuilds tables rather than incrementally merging/appending, which can be slow and costly, and temporarily removes existing data during rebuild.
- **Info needed:** Whether a full rebuild is actually needed now (schema change, backfill, data quality fix) - always ask_user; never default this on for routine runs.
- **When to include:** Include only as a deliberate, occasional/manual step (e.g. a separate manual job or an ad hoc run) after a logic/schema change to incremental models - not as a standing flag on a recurring schedule.
- **Good vs bad:** Good: a one-off manual trigger of full-refresh after fixing incremental logic. Bad: baking --full-refresh permanently into a nightly scheduled job, which wastes compute/cost every run and defeats the purpose of incremental materialization.

### `--vars`
- **Purpose:** Passes a YAML/JSON dictionary of variables into the Jinja context, overriding vars defined in dbt_project.yml for that invocation.
- **Data effect:** No inherent warehouse read/write change itself, but model logic may branch on these vars, indirectly affecting what data is written (e.g. date ranges, feature flags).
- **Info needed:** Exact variable names expected by the project's models/macros and the values needed; must ask_user for business-specific values (dates, environment flags) - don't assume from memory since these are typically job-run-specific, not stored defaults.
- **When to include:** Include only if the project's models actually consume custom vars for this run; omit otherwise (no need to pass vars models don't reference).
- **Good vs bad:** Good: passing a run-specific date window var when a model needs one for backfills. Bad: passing --vars with hardcoded values that should instead live in dbt_project.yml or environment variables, making the job command brittle and undocumented.

### `--threads`
- **Purpose:** Sets the number of concurrent threads dbt uses to execute models in parallel (overrides the profile/connection default).
- **Data effect:** No change to read/write classification; affects execution concurrency, which can affect warehouse load/concurrency limits but not what data ends up written.
- **Info needed:** Whether the org/warehouse has a known concurrency constraint or preference; typically pull from memory (standing environment/connection default) rather than asking per job.
- **When to include:** Usually omit and rely on the connection/environment default; include only when a specific job needs more/less parallelism (e.g. warehouse rate limits, or a job with many independent lightweight models that benefits from higher threads).
- **Good vs bad:** Good: bumping threads for a job with many small independent models to reduce runtime, within known warehouse limits. Bad: cranking threads very high without checking warehouse concurrency/credit limits, causing throttling or query queuing failures.

## Best practices

- **Scope every scheduled dbt run with --select/--exclude (by tag, path, or subgraph) rather than running the whole project unselected.**
  - Why: Keeps runtime and warehouse cost predictable and prevents an unrelated model failure or an experimental/WIP model from blocking or bloating a production schedule.
- **Prefer dbt build over a bare dbt run when the job's purpose is to build and validate models together.**
  - Why: dbt run only builds models and skips tests/seeds/snapshots, so a bare dbt run without following it with dbt test can silently ship broken data; dbt build interleaves tests immediately after each model in DAG order, catching failures earlier and closer to the source.

## Anti-patterns

- **Hardcoding --full-refresh on every scheduled/recurring run.**
  - Why: It forces full table rebuilds every time, discarding the performance/cost benefit of incremental materializations and needlessly increasing warehouse spend and runtime; full-refresh should be a deliberate, occasional action, not a standing schedule flag.
- **Running dbt run alone (without a paired dbt test step) as the only step in a CI or production job.**
  - Why: dbt run performs warehouse writes with no built-in data quality validation; without tests running afterward, broken or incorrect data can be materialized into production tables undetected.

## Overlaps with

- dbt build (superset: run + test + seed + snapshot in one DAG-ordered pass; most dbt Cloud jobs default to build instead of run)
- dbt test (commonly paired immediately after dbt run since run itself does not test)
- dbt seed (separate command for loading CSV seed files, not included in run)
- dbt snapshot (separate command for snapshots, not included in run)
- dbt compile (run implicitly compiles models first; compile alone does not execute against the warehouse)
- dbt source freshness (separate command/checkbox, not covered by run or build)
- dbt docs generate (separate command/checkbox typically run after run/build to refresh documentation artifacts)
- dbt run-operation (used for invoking standalone macros, distinct execution path from model materialization)
