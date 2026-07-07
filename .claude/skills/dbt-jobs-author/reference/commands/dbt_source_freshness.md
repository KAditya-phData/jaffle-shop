# dbt source freshness

**Aliases:** dbt source snapshot-freshness (legacy alias, deprecated)

## What it does

Checks how stale each selected source table is by comparing the most recent record's loaded_at_field (or a loaded_at_query) against the current time, and compares that age to the warn_after/error_after thresholds defined in the source's freshness config. It queries the warehouse (read-only SELECT/metadata queries) to compute max(loaded_at_field) per source table, then writes a pass/warn/error status to stdout and to a local JSON artifact (target/sources.json by default). It does not build, test, or modify any warehouse objects.

## Effect on warehouse data

**Classification:** `read-only`

It only issues read queries against source tables (e.g. SELECT MAX(loaded_at_field) or a custom loaded_at_query) to determine recency. It writes zero tables/views/rows to the warehouse. Its only 'write' is a local artifact file (target/sources.json, or wherever --target-path points) plus run_results.json/console output — i.e. writes-artifacts-only, not warehouse data.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** Yes — dbt Cloud exposes a 'Run source freshness' checkbox in Deploy job and CI job Execution Settings that runs `dbt source freshness` as an implicit first step. This checkbox behaves differently than adding the command as an explicit step: if the checkbox-driven freshness step fails, the job can still continue and succeed on subsequent steps; if `dbt source freshness` is added as an explicit numbered command step, it participates in the normal chained execute_steps and a failure (non-zero exit) halts the rest of the job.
- **Notes:** In dbt-jobs-as-code YAML, the checkbox equivalent is the job-level boolean field `run_generate_sources` (true/false) — not a line in execute_steps. It can ALSO be added as an explicit string in execute_steps (e.g. "dbt source freshness --select source:my_source") if the author wants a failure to block downstream steps. Note dbt build does NOT include source freshness checks, so if freshness gating is wanted alongside dbt build it must be added separately (checkbox or step).

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| which mechanism: checkbox (run_generate_sources) vs explicit execute_steps command | `ask_user` | Determines failure-blocking behavior — must ask whether a stale-source failure should halt the rest of the job (explicit step) or just be surfaced without blocking (checkbox). |
| --select scope (which sources/source tables to check) | `ask_user` | Default checks all sources with a freshness block; user/job author should confirm if only specific sources are relevant (e.g. source:snowplow or source:snowplow.event) especially in CI where scope should match modified sources. |
| sources.yml freshness block already defined (loaded_at_field / loaded_at_query, warn_after, error_after) | `ask_user` | Freshness only works for sources that have a freshness config; agent cannot assume this exists — must confirm in the project or it will silently skip/no-op for unconfigured sources. |
| environment_id / project_id / account_id for the job | `memory` | Standard job scaffolding info the job-authoring flow already collects/stores, not specific to this command. |
| position in step order (before/after run+test) | `ask_user` | Conventionally step 1, before dbt build/run, so stale data is caught before wasting compute on transforms; confirm with user if they want it elsewhere. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s (also --exclude)`
- **Purpose:** Restrict the freshness check to a subset of sources using selector syntax, e.g. --select "source:snowplow" for all tables in a source or --select "source:snowplow.event" for one table.
- **Data effect:** None — still read-only, just narrows which source tables are queried for max(loaded_at).
- **Info needed:** Need to know which source(s) the user cares about; if unspecified, default behavior checks all sources with a freshness block. Ask the user only if they want a narrower/CI-scoped check; otherwise default to no --select (check everything).
- **When to include:** Include when the job should only check specific sources (e.g. a CI job for one team's sources, or to avoid checking huge/expensive sources on every run). Omit for a full nightly freshness sweep.
- **Good vs bad:** Good: use --select "source:snowplow" in a CI job scoped to code touching only that source, cutting warehouse query volume. Bad: omitting --select in a project with hundreds of sources when only a handful actually matter for the job's purpose, causing unnecessary query load and longer runtime.

### `-o / --output (DEPRECATED)`
- **Purpose:** Previously overrode the destination path of the sources.json artifact (default target/sources.json).
- **Data effect:** None on warehouse data; only affects local artifact file location.
- **Info needed:** None to ask — this flag is deprecated with no direct replacement; --target-path can relocate all artifacts if needed.
- **When to include:** Do not include; remove from any existing jobs per dbt's deprecation guidance.
- **Good vs bad:** Bad: leaving -o/--output in an existing job step, which will trigger deprecation warnings and eventually break. Good: strip it out and rely on default target/sources.json (or --target-path if the whole artifacts directory needs to move).

### `--target-path`
- **Purpose:** Global dbt flag (not source-freshness-specific) that changes where ALL run artifacts (including sources.json) are written for this invocation.
- **Data effect:** None on warehouse data; local artifact path only.
- **Info needed:** Only relevant if the job's CI/CD tooling needs a custom artifacts directory (e.g. to avoid collision when running freshness and build in parallel). Ask user only if they have a custom artifacts pipeline.
- **When to include:** Skip by default; include only if downstream tooling (e.g. custom artifact upload step) expects a non-default path.
- **Good vs bad:** Good: set --target-path when running freshness and a build step in parallel to avoid target/ directory clobbering. Bad: setting it without updating the artifact-consuming step, causing 'artifact not found' failures.

### `global flags: --target, --vars, --profiles-dir`
- **Purpose:** Standard dbt global flags can be layered onto the freshness command like any other dbt invocation (e.g. to pick a target/environment or pass vars used in a custom loaded_at_query).
- **Data effect:** None on warehouse writes; may change which connection/credentials/schema are used to run the read queries.
- **Info needed:** Only needed if the job runs against non-default targets/environments; typically inherited from the dbt Cloud job's environment settings, so usually already known (memory), not asked per-command.
- **When to include:** Include only if this job step must diverge from the environment's default target.
- **Good vs bad:** Good: rely on the job's Environment settings rather than hardcoding --target in the step. Bad: hardcoding a --target that conflicts with the job's configured deployment environment, causing it to check freshness against the wrong warehouse/schema.

## Best practices

- **Run source freshness as an early, explicit step (or checkbox) before dbt build/run in deploy jobs, scoped with --select to the sources that feed critical models.**
  - Why: Front-loads a cheap read-only check so the job fails fast (or the checkbox surfaces staleness) before spending compute building/testing on data that's already known to be stale, and dbt build itself won't check freshness so it must be added deliberately.
- **Choose the explicit execute_steps command (not just the checkbox) when a stale source should legitimately block downstream transforms/exposures.**
  - Why: The checkbox's freshness step can fail without stopping the job, which is fine for monitoring/alerting but wrong when staleness should hard-block a business-critical deploy; the difference is easy to get backwards and silently ship on stale data.

## Anti-patterns

- **Running `dbt source freshness` with no freshness blocks configured in sources.yml, or with the deprecated -o/--output flag left in the step.**
  - Why: Without loaded_at_field/warn_after/error_after configured per source, the command silently has nothing to check (false sense of coverage); -o is deprecated and will eventually error, breaking the job for no benefit.
- **Running source freshness against very large/expensive source tables on every single CI run without --select scoping.**
  - Why: It issues a real warehouse query (e.g. MAX() over a huge, unclustered table) each run; unscoped, frequent CI-triggered freshness checks can add meaningful warehouse compute cost for a read-only status check.

## Overlaps with

- dbt build (does NOT include freshness checks — common misconception)
- dbt run
- dbt test
- dbt Cloud 'Run source freshness' job checkbox / run_generate_sources job-as-code field
- dbt snapshot (unrelated 'snapshot' terminology overlap, different purpose: SCD history vs recency check)
- dbt freshness (proposed future unified command per dbt-core epic #12719, would replace/alias this)
