# dbt build

## What it does

Runs models, tests, snapshots, and seeds (and, from dbt Core 1.11/Fusion, user-defined functions) together in a single DAG-ordered execution. For each node dbt builds it and immediately runs any tests that depend on it before moving to dependents, so a failing test on an upstream resource causes downstream resources to be skipped rather than run against bad data. It writes one combined manifest.json and run_results.json artifact covering everything selected. It does NOT run source freshness checks or generate docs — those are separate commands/toggles.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

This is the primary write workload of a dbt job: it creates/replaces views and tables (models), inserts rows into snapshot tables, loads seed CSVs into tables, and executes test queries (tests are read-only SELECTs, but everything else in build materializes objects and rows in the warehouse). --full-refresh additionally drop-cascades and rebuilds incremental models/snapshots from scratch. Separately, dbt always writes local artifacts (target/manifest.json, target/run_results.json) regardless of warehouse effects — that is run metadata, not warehouse data.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** yes
- **Available as a job parameter/toggle instead:** no — dbt build is a command step itself, not a toggle. (Contrast with 'Run source freshness' and 'Generate docs on run', which ARE separate job-level checkboxes for dbt source freshness / dbt docs generate, not part of build.)
- **Notes:** dbt build is in fact the DEFAULT first command dbt Cloud pre-populates when you create a new job's command list. It is the standard, recommended single step for most deploy jobs (replaces the older run+test+snapshot+seed sequence) and is also commonly used in CI jobs against a deferred/sliced selection.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| target/environment to run against | `memory` | Usually implicit from the dbt Cloud job's assigned Environment (which fixes the target); only need explicit --target if overriding within a job, which is unusual. |
| which job (and its environment/connection) to attach this command to | `ask_user` | Job name, project, and target environment are typically user-provided or already established earlier in the authoring conversation. |
| selection scope (full project vs subset) | `ask_user` | Whether to build everything or a --select/--exclude subset is a business decision the agent cannot infer; default for scheduled jobs is usually full build (no selection), but ask if the user wants a partial run. |
| whether this is a CI job (state-based deferral) vs scheduled job | `ask_user` | Determines whether --select 'state:modified+' and deferral flags should be paired with build; changes recommended flag set substantially. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Restrict the DAG-ordered build to a chosen set of nodes (models/tests/seeds/snapshots) using names, tags, paths, graph operators (+), or methods like state:modified+, resource_type:.
- **Data effect:** Narrows which warehouse objects get created/refreshed — does not change read/write nature, only scope.
- **Info needed:** Ask the user which models/tags/packages they mean, or infer 'state:modified+' automatically for CI jobs (in which case still confirm with user).
- **When to include:** Include whenever the job should target a subset rather than the whole project (e.g. CI jobs, a single mart, a team's models). Omit for full scheduled production builds.
- **Good vs bad:** Good: CI job using --select state:modified+ to only build/test changed models and their downstream. Bad: hardcoding a large explicit model list that silently misses new models added later — prefer tags/state selectors.

### `--exclude`
- **Purpose:** Remove specific nodes from an otherwise larger selection (often combined with --select).
- **Data effect:** Same as --select — scoping only, no change to read/write semantics.
- **Info needed:** Ask the user which models/tags to omit (e.g. long-running or known-flaky models).
- **When to include:** Include when excluding a known-expensive or quarantined model from a broad build; skip if there's nothing to exclude.
- **Good vs bad:** Good: excluding a heavy historical-backfill model from the nightly build and running it separately/weekly. Bad: using --exclude to permanently hide a broken model instead of fixing or removing it from the project.

### `--target / -t`
- **Purpose:** Override which profile/target (warehouse connection, schema) dbt connects to, distinct from the target baked into the dbt Cloud environment.
- **Data effect:** Changes WHERE writes land (which warehouse/database/schema) — does not change the fact that build writes.
- **Info needed:** In dbt Cloud, the environment already fixes the target; only ask the user if they explicitly need an override, which is atypical and often a sign the job is misconfigured for its environment.
- **When to include:** Usually omit in dbt Cloud jobs — the job's Environment setting is the intended mechanism for target selection. Include only for advanced multi-target patterns within one environment.
- **Good vs bad:** Good: rare cases of a custom target defined for a special credential set. Bad: using --target to point a 'CI' job at production to save setup effort — bypasses environment isolation and risks writing to prod from CI.

### `--full-refresh / -f`
- **Purpose:** Forces dbt to drop-and-rebuild incremental models and snapshots from scratch, ignoring their incremental logic.
- **Data effect:** Heavier warehouse write: drops (cascade) and fully rebuilds tables, not just incremental inserts/merges — can be far more expensive and briefly disruptive (drop/recreate) versus a normal incremental run.
- **Info needed:** Ask the user explicitly — this is a destructive, cost-and-availability-impacting choice, never assume it. Confirm which models it should apply to (usually paired with --select) and whether it should run on every schedule or only be a manual/occasional job.
- **When to include:** Never include by default on every scheduled run. Include only as an occasional, deliberately-scheduled or manually-triggered job (e.g. weekly/monthly full-refresh job, or after a schema/logic change to incremental models).
- **Good vs bad:** Good: a separate, infrequent 'full-refresh' job scoped with --select to just the incremental models that changed logic. Bad: adding --full-refresh to the main nightly build permanently — turns every run into a full rebuild, wasting warehouse compute and losing incremental benefits.

### `--vars`
- **Purpose:** Passes a YAML/JSON dict of variables into the Jinja context at runtime, overriding dbt_project.yml vars.
- **Data effect:** Indirect — vars can change model logic (e.g. date filters, environment switches) that in turn changes what gets written, but the flag itself doesn't write anything.
- **Info needed:** Ask the user what variables their project expects and what values are needed for this job run (e.g. is_incremental overrides, date ranges, environment flags) — this is project-specific and cannot be assumed.
- **When to include:** Include only if the dbt project actually defines/uses vars that need a non-default value for this job. Omit otherwise — most jobs need none.
- **Good vs bad:** Good: passing --vars '{run_date: ...}' for a backfill job that needs a specific date window. Bad: hardcoding secrets or environment-specific values via --vars instead of using dbt Cloud environment variables ({{ env_var(...) }}).

### `--threads`
- **Purpose:** Overrides the number of concurrent paths dbt uses to execute independent nodes in the DAG.
- **Data effect:** Affects execution parallelism/speed and warehouse concurrent-query load, not what gets written.
- **Info needed:** Ask only if the user has a specific concurrency constraint (warehouse concurrency limits, credit/cost concerns) or wants faster runs; otherwise the project/profile default (or dbt Cloud environment default) is fine.
- **When to include:** Omit unless there's a known need to raise/lower parallelism (e.g. small warehouse tier struggling with default threads, or wanting faster CI turnaround with a bigger warehouse).
- **Good vs bad:** Good: lowering threads for a job on a small/shared warehouse to avoid queuing contention. Bad: cranking threads very high without warehouse sizing to match, causing queueing or throttling that makes the run slower/costlier, not faster.

### `--fail-fast / -x`
- **Purpose:** Stops the run immediately on the first node failure instead of continuing to run/skip remaining independent nodes.
- **Data effect:** No direct warehouse write effect, but changes how much gets written/attempted before stopping — fewer partial writes on failure since it exits early.
- **Info needed:** No external info needed beyond a yes/no preference; safe default decision the agent can make, though worth confirming preference for CI vs scheduled jobs.
- **When to include:** Good fit for CI jobs where a fast, clear failure signal is wanted. Consider omitting on large scheduled production builds where you'd rather let independent branches finish (partial success) and see the full picture of what failed.
- **Good vs bad:** Good: CI job using --fail-fast to give quick feedback on PRs without waiting for the whole DAG. Bad: using --fail-fast on a large nightly build where stakeholders depend on unrelated marts still being refreshed even if one unrelated model fails.

## Best practices

- **Use dbt build as the default single command for most scheduled jobs instead of chaining separate dbt run + dbt test + dbt snapshot + dbt seed steps.**
  - Why: Build interleaves tests right after each model so failures are caught and downstream models skipped before wasting compute on bad data, and it produces one unified run_results/manifest artifact — simpler and safer than manual chaining.
- **Scope CI jobs with --select state:modified+ (and optionally --fail-fast) rather than building the whole project.**
  - Why: Keeps CI fast and cheap by only building/testing what changed and its downstream dependents, and fails fast to give quick PR feedback.

## Anti-patterns

- **Adding --full-refresh permanently to a recurring scheduled job's command.**
  - Why: Forces every run to drop-cascade and fully rebuild incremental models/snapshots, multiplying warehouse compute cost and runtime for no ongoing benefit — full-refresh should be a deliberate, occasional/manual action.
- **Relying on dbt build to catch stale source data.**
  - Why: build does not check source freshness at all; teams sometimes assume a passing build means data is fresh, but freshness requires the separate dbt source freshness command/job checkbox.

## Overlaps with

- dbt run (build supersedes/subsumes running models alone)
- dbt test (build subsumes running tests, but interleaved rather than as a separate pass)
- dbt seed (build subsumes seeding)
- dbt snapshot (build subsumes snapshotting)
- dbt source freshness (NOT included in build — must be added separately or via the 'Run source freshness' job checkbox)
- dbt docs generate (NOT included in build — separate command or the 'Generate docs on run' job checkbox)
- dbt compile (build compiles as part of execution but compile-only runs are a distinct read-only command)
