# dbt retry

## What it does

Re-executes the immediately preceding dbt invocation starting from the point of failure, skipping nodes that already succeeded. It determines where to resume by reading the run_results.json artifact from the prior run. Supported underlying commands are build, compile, clone, docs generate, seed, snapshot, test, run, and run-operation. If the prior invocation succeeded, retry is a no-op; if the prior invocation failed before any node executed (e.g. a connection/parse error), retry has nothing to resume and effectively does nothing useful.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

dbt retry itself has no independent read/write semantics — it re-invokes whichever underlying command failed (run, build, seed, snapshot, test, etc.) for only the remaining/failed nodes. If that underlying command materializes models, loads seeds, or runs snapshots, retry performs the same warehouse writes (tables/views/rows) that command would have made. It is read-only only in the narrow case where the resumed command was itself read-only (e.g. compile, or a pure-test invocation). It also reads/depends on the local artifact run_results.json (local state, not a warehouse write).

## Use in a dbt Cloud job

- **Can run as a step:** no
- **Should run:** no
- **Available as a job parameter/toggle instead:** Not exposed as a job parameter/toggle either. Retry is surfaced as a dbt Cloud UI action ('Rerun' -> 'Rerun from start' or 'Rerun from failure') on a completed/errored job run's Run page, and as the 'Retry Failed Run' dbt Cloud API v2 endpoint. It is not a selectable step type in a jobs-as-code job definition (no dbt-jobs-as-code / dbt Cloud jobs.yml field for it).
- **Notes:** Retry only makes sense against the run_results.json of one specific prior run, so it is inherently a post-hoc action taken against an already-executed job run, not something pre-authored as a step inside that same job's command list. Authoring 'dbt retry' as a literal step in jobs.yml would be meaningless on a fresh scheduled/CI invocation since there is no prior failed run_results.json to resume from in a new run context.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| N/A - not applicable as a job step | `have` | No jobs-as-code field exists for this. If the user wants 'retry failed jobs automatically', that requires dbt Cloud's job-level rerun/retry action (UI or API), not a command step in the job's steps list. |
| Whether user actually means job-level rerun-on-failure behavior | `ask_user` | Clarify whether they want dbt Cloud's built-in Rerun-from-failure triggered manually, via API, or via CI orchestration webhook — this is a separate mechanism from authoring job steps and should be redirected accordingly. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `(none applicable - no job-step flags)`
- **Purpose:** Not applicable; dbt retry cannot be authored as a jobs-as-code command step
- **Data effect:** N/A
- **Info needed:** N/A
- **When to include:** Never include as a literal step in jobs.yml; direct the user to dbt Cloud's Rerun UI or Retry Failed Run API instead
- **Good vs bad:** Bad usage: attempting to add 'dbt retry' as a command in a job's steps list — there is no prior run_results.json in a fresh scheduled/CI invocation for it to resume, so it does nothing useful or errors.

### `--threads / --vars (CLI-only, local or dbt Cloud CLI usage)`
- **Purpose:** Override thread count or job variables when manually resuming a failed local/CLI invocation of dbt retry
- **Data effect:** No independent effect; inherits the write behavior of whichever underlying command (run/build/seed/etc.) is being resumed
- **Info needed:** Only relevant to local/CLI ad-hoc retry usage, not to jobs-as-code job authoring
- **When to include:** Irrelevant to job-step authoring; do not surface these as configurable job options
- **Good vs bad:** Not applicable to job authoring; these only matter for someone manually invoking dbt retry from a terminal or dbt Cloud CLI against a local run_results.json.

## Best practices

- **Use dbt Cloud's native 'Rerun from failure' button on the Run page, or the Retry Failed Run API endpoint, to resume a specific errored run rather than trying to script 'dbt retry' as a job step.**
  - Why: Retry depends on the run_results.json of that exact prior run; it is a per-run recovery action, not a reusable pipeline step that belongs in a job definition.
- **If automatic retry-on-transient-failure is desired for a scheduled job, implement it via external CI/CD orchestration (e.g. call the Retry Failed Run API after a failure webhook/alert) rather than trying to bake retry logic into the job's command list.**
  - Why: dbt Cloud jobs-as-code has no native step or parameter for retry; the capability only exists at the run level via UI/API, outside the job spec itself.

## Anti-patterns

- **Adding 'dbt retry' as a command step inside a scheduled/CI job definition.**
  - Why: On a fresh run there is no prior run_results.json for that invocation to resume from, so the step is meaningless or fails; retry only works when re-invoked against an already-failed run's artifacts, not within the same run that would produce them.
- **Relying on repeated retries to paper over persistent (non-transient) failures.**
  - Why: If the underlying error is not transient (e.g. a genuine SQL/logic bug), retry deterministically reproduces the same failure each time, wasting warehouse compute on repeated partial writes without addressing the root cause.

## Overlaps with

- dbt run
- dbt build
- dbt test
- dbt seed
- dbt snapshot
- dbt compile
- dbt clone
- dbt docs generate
- dbt run-operation
