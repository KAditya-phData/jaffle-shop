# dbt parse

## What it does

Parses and validates the dbt project's Jinja/YAML/SQL files (models, macros, tests, sources, etc.) without connecting to the data warehouse, and writes/returns a manifest.json artifact describing dbt's understanding of every resource in the project (no compiled SQL is included since no warehouse connection is made). It also emits a perf_info artifact with detailed parse-timing info, useful for diagnosing slow-parsing large projects. It is the recommended way to validate project syntax or produce a manifest for introspection (e.g., dbt list) when a warehouse connection isn't needed/wanted.

## Effect on warehouse data

**Classification:** `writes-artifacts-only`

dbt parse never connects to the warehouse, so it cannot read or write any table/view/row data. It only writes local run artifacts: target/manifest.json (project resource graph, uncompiled), target/partial_parse.msgpack (internal parse cache), and a perf_info timing file. In dbt Cloud, the manifest.json artifact from this run is stored as part of the run's artifacts (useful as a fast, warehouse-free source for state comparison / node introspection), but that is job-run metadata, not warehouse data.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no - unlike 'Generate docs on run' or 'Run source freshness' (dedicated job-level checkboxes), dbt parse is not surfaced as a job setting/toggle. It is only invocable as an explicit command step in execute_steps.
- **Notes:** Runs fine as a job step (fast, no warehouse round-trip). Typical legitimate use case per dbt's own CI docs: a dedicated lightweight 'refresh comparison manifest' job (e.g., merge-triggered on the deferral environment) whose only step is `dbt parse --no-partial-parse`, giving CI jobs a fresh state:modified manifest to defer/compare against without waiting on a full dbt build. Adding it as an extra step inside a normal build/test job is redundant, since every dbt command parses the project as a prerequisite anyway.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| which job / environment this parse-only step belongs to | `ask_user` | Need to know if this is a new lightweight 'refresh manifest' job or an addition to an existing job; confirm intent since it's an unusual step to add. |
| account_id / project_id / environment_id for the dbt-jobs-as-code YAML | `memory` | Standard job-scoping IDs the job-authoring skill already stores/retrieves per account/environment defaults. |
| whether --no-partial-parse is desired | `ask_user` | Default is partial parse (fast); only needed if the user explicitly wants a guaranteed full re-parse, e.g. for a state-comparison manifest refresh job. |
| trigger type (schedule vs. git merge webhook) for a parse-only job | `ask_user` | The common use case (refreshing the CI deferral manifest) is triggered on merge to the deferred branch, not a cron schedule - confirm explicitly. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--no-partial-parse / --partial-parse`
- **Purpose:** Forces a full re-parse of every file in the project from scratch instead of reusing the cached partial_parse.msgpack to only reparse changed files.
- **Data effect:** None on warehouse data; only affects how thoroughly local files are re-read and how the manifest.json artifact is regenerated.
- **Info needed:** Just a yes/no preference from the user; no IDs needed.
- **When to include:** Include --no-partial-parse when parse is used specifically to produce a trustworthy, from-scratch manifest (e.g., CI deferral/state-comparison refresh jobs, or after upgrading dbt versions / suspected partial-parse bugs). Omit (default partial parse) for routine/frequent parse steps where speed matters more. Note: deprecated/unsupported on the newer Fusion engine (logs warning dbt1700) - flag this if the account is on Fusion.
- **Good vs bad:** Good: use --no-partial-parse in the merge-triggered 'refresh comparison manifest' job so a stale partial-parse cache doesn't produce an incorrect state:modified diff in downstream CI jobs.

### `--static-parser / --no-static-parser`
- **Purpose:** Toggles dbt's tree-sitter-based static analysis of model files (extracting ref()/source()/config() without full Jinja rendering) versus always doing a full Jinja render.
- **Data effect:** None on warehouse data; purely a local parsing performance/compatibility setting.
- **Info needed:** None from the user typically; a power-user/debugging flag.
- **When to include:** Leave default (static parser on) in essentially all cases - it's 3x+ faster and dbt auto-falls-back to Jinja rendering when static parsing fails. Only disable if a user reports parsing bugs traced to the static parser.
- **Good vs bad:** Bad: disabling it by default 'to be safe' with no evidence of a bug just slows every parse/compile/run in the project for no benefit.

### `--show-all-deprecations`
- **Purpose:** When combined with --no-partial-parse, surfaces every occurrence of each deprecation warning across the project instead of only the first occurrence per deprecation type.
- **Data effect:** None on warehouse data; only affects console/log output verbosity.
- **Info needed:** None - a simple diagnostic toggle.
- **When to include:** Include only for one-off/ad hoc audit runs (e.g., pre-Fusion-upgrade deprecation scans), not in routine scheduled/CI jobs where it just adds log noise.
- **Good vs bad:** Good: `dbt parse --show-all-deprecations --no-partial-parse` as a one-time manual run before a Fusion engine upgrade, not as a recurring job step.

### `--threads`
- **Purpose:** Standard global dbt flag controlling parallelism; has minimal effect on parse specifically since parse does little concurrent work compared to run/build.
- **Data effect:** None on warehouse data.
- **Info needed:** None - leave at project/profile default.
- **When to include:** Do not set explicitly for a parse step; not a meaningful lever here.
- **Good vs bad:** Bad: tuning --threads on a parse-only job step, wasting effort optimizing a step that isn't threads-bound.

## Best practices

- **Use `dbt parse` (with --no-partial-parse) as the single step in a small, merge-triggered job whose only purpose is to keep a fresh, accurate manifest.json available for other jobs to defer to / compare state against.**
  - Why: It gives CI jobs an up-to-date comparison manifest almost instantly (no warehouse connection, no model builds), instead of every CI run waiting on or depending on the last full deploy job's manifest.
- **Rely on dbt's automatic parsing inside every other command (run/build/test/compile) rather than adding a redundant explicit `dbt parse` step before them in the same job.**
  - Why: Every dbt invocation parses the project as a prerequisite step anyway; an extra explicit parse step in a build/test job just adds run time without adding information.

## Anti-patterns

- **Adding `dbt parse` as an extra step before `dbt build`/`dbt test` in a normal scheduled production job 'just to check for errors first'.**
  - Why: Pure duplicated work - build/test will parse the project themselves and fail fast on the same Jinja/YAML errors, so the separate parse step only adds latency without catching anything earlier.
- **Using `dbt parse` as a substitute for `dbt compile` when compiled SQL is actually needed (e.g., for linting compiled code or downstream tooling).**
  - Why: parse's manifest never contains compiled SQL since it doesn't touch the warehouse; consumers expecting rendered SQL will get incomplete or wrong artifacts.

## Overlaps with

- dbt compile
- dbt list
- dbt debug
- dbt build
- dbt run
- dbt test
