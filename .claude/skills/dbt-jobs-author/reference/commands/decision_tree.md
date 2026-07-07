# dbt command decision tree

Use this to go from *what the user wants the job to do* → *which command(s) + options belong in the job*. Load the referenced `commands/<file>.md` for the chosen command(s) before writing the step.

**Start: What does the user want this job to do?**

- **"Build/refresh/transform my data on a schedule"** (the vast majority of deploy jobs)
  - → Single step: `dbt build` (load commands/dbt_build.md). Add `--select`/`--exclude` only if the user wants a subset; never add `--full-refresh` to the recurring schedule (make that a separate, deliberately-triggered job/step instead).
  - Does the project depend on **SCD/history tracking** for mutable sources? → Add a separate `dbt snapshot` step (load commands/dbt_snapshot.md), scheduled at a cadence matching source change rate, generally *before* `dbt build` if downstream models select from the snapshot.
  - Does the job need to **guard against stale source data**? → Add source freshness. Ask: should staleness just be visible/monitored, or should it block the run?
    - Monitoring only → enable the `run_generate_sources` job toggle (job-parameter, not a step).
    - Must hard-block downstream steps → add an explicit `dbt source freshness --select ...` step as the first command, before `dbt build` (load commands/dbt_source_freshness.md).
  - Does the job need **documentation refreshed**? → Prefer the `generate_docs` job toggle (job-parameter) on the one canonical production job. Only add an explicit `dbt docs generate` command step if you need `--no-compile`/`--select` or want a docs failure to hard-fail the job (load commands/dbt_docs_generate.md). Never `dbt docs serve` in any job.
  - Does the project have **seed CSVs** that must refresh on this schedule? → `dbt build` already includes seeds; only add a standalone `dbt seed` step if seeding needs to run on a different cadence/scope than the rest of the build (load commands/dbt_seed.md).

- **"This is a CI/PR job — validate proposed changes before merge"**
  - → `dbt build --select state:modified+` (+ `--fail-fast` for quick PR feedback) (load commands/dbt_build.md). This is the standard CI pattern — it replaces separate run+test steps.
  - Want to see exactly what the selector resolves to before trusting it? → Optionally add a preceding `dbt ls --select state:modified+ --output json` debug/log step (load commands/dbt_list.md) — informational only, not required.
  - Need a fast, always-fresh manifest for the deferred/state comparison? → That's a *separate*, merge-triggered job whose only step is `dbt parse --no-partial-parse` (or `dbt compile`) (load commands/dbt_parse.md / commands/dbt_compile.md) — not a step inside the CI job itself.

- **"I need a one-off/occasional destructive or maintenance action"** (full-refresh, grants, cleanup, cloning)
  - Full rebuild of incrementals/snapshots → separate, manually-triggered or infrequent scheduled job: `dbt build --select <scope> --full-refresh` (load commands/dbt_build.md). Never bake into the nightly job.
  - Grants/cleanup/custom maintenance logic → `dbt run-operation <macro> --args '{...}'` using a tested, version-controlled macro (load commands/dbt_run_operation.md). Confirm what the macro does — treat as a potential write. Avoid `--sql` ad hoc strings in recurring jobs.

- **"I want to preview/debug something, not run a real job"**
  - Preview one model's output → `dbt show` — CLI/local only, never add to a job (load commands/dbt_show.md).
  - Preview generated docs → `dbt docs serve` — local only, never in a job (load commands/dbt_docs_serve.md).
  - Check what a selector matches → `dbt ls` — CLI/CI-log debug only (load commands/dbt_list.md).
  - Validate project syntax / see compiled SQL → `dbt compile` or `dbt parse` — CLI/local or the narrow merge-triggered manifest-refresh job case only (load commands/dbt_compile.md, commands/dbt_parse.md).

- **"A run failed, I want to resume/retry it"**
  - → Not a job step at all. Use dbt Cloud's "Rerun from failure" UI action or the Retry Failed Run API against that specific run (load commands/dbt_retry.md). Never author `dbt retry` inside jobs.yml.

- **"Should I add dbt deps / dbt clean?"**
  - → No. dbt Cloud runs `dbt deps` automatically before every job; every job run gets a fresh ephemeral filesystem so `dbt clean` has nothing to do (load commands/dbt_deps.md, commands/dbt_clean.md).

**Universal flag pass, once the core step(s) are chosen** (applies mainly to build/run/test/seed/snapshot):
- `--select`/`--exclude`: ask the user for scope; default full-project for scheduled prod jobs, `state:modified+` for CI.
- `--full-refresh`: only via explicit user confirmation, only as an occasional/manual job, never a standing schedule flag.
- `--target`: leave unset; rely on the dbt Cloud job's Environment binding. Only override for a rare, explicit, explained reason.
- `--vars`: only if the project's models/macros actually consume custom vars for this run; ask for exact key/values, never fabricate.
- `--threads`/`--fail-fast`: optional performance/CI-feedback tuning; not required by default.

## Reconciled overlap notes

- dbt build subsumes dbt run + dbt test + dbt seed + dbt snapshot in one DAG-ordered pass with interleaved testing; it is the default recommended step and all four research entries agree run/test/seed/snapshot are redundant standalone steps once build is used for that same scope.
- dbt build never includes dbt source freshness or dbt docs generate — every agent independently flagged this as a common misconception; both must be added separately (toggle or explicit step) regardless of whether build is used.
- dbt compile and dbt parse overlap heavily (both produce manifest-style artifacts without materializing anything) but differ: parse never touches the warehouse at all (fastest, pure local validation), while compile runs introspective queries against the warehouse (needed when Jinja logic requires run_query/get_columns_in_relation). Prefer parse for pure CI manifest-refresh; use compile only if introspection is required.
- dbt show and dbt ls are both read-only preview/debug tools with zero legitimate scheduled-job use, but they differ in scope: dbt ls does static, no-warehouse-connection listing of many nodes via selectors; dbt show compiles+executes exactly one node's SQL against the warehouse. Neither belongs in a job's command list.
- dbt docs generate and dbt docs serve are sequential halves of one workflow (generate produces artifacts, serve previews them locally) but only generate has any place in dbt Cloud (as a job toggle); serve is exclusively local-dev and must never appear in a job.
- dbt retry, dbt run-operation, and dbt clean/deps all surfaced 'is this a job step at all' confusion across agents — reconciled as: run-operation IS a legitimate step (macro-dependent write risk), but retry/clean/deps are NOT job steps (retry has no jobs-as-code field and needs a prior run's artifacts; deps runs automatically pre-job; clean has nothing to clean in an ephemeral filesystem).
- --full-refresh appears as a flag on build/run/seed/snapshot and every agent independently warned against ever defaulting it on for a recurring schedule — reconciled into one universal safety rule rather than four separate command-specific ones.
- --select/--exclude/--vars/--target/--threads are shared global flags repeated near-identically across build/run/test/seed/snapshot/compile/parse/source-freshness research entries — consolidated into one 'universal flag pass' in the decision tree instead of repeating per-command guidance.
