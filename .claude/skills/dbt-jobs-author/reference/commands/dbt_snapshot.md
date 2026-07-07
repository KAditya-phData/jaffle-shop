# dbt snapshot

## What it does

Executes snapshot definitions in the dbt project to implement Type-2 Slowly Changing Dimensions (SCD2), capturing the state of mutable source records over time so history isn't lost when source rows are updated/deleted. On each invocation it compares current source data against the existing snapshot table (using the configured 'timestamp' or 'check' strategy and unique_key) and inserts new rows to record changes, updating 'dbt_valid_to' on superseded rows. It only processes snapshots (resources under snapshot-paths, default snapshots/), not models/seeds/tests.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

This is NOT read-only and does not merely write local artifacts. dbt snapshot creates/maintains real snapshot tables in the warehouse (DDL on first run, then DML inserts/updates each run) to persist historical row versions. This is a genuine warehouse-data write, distinct from commands like `dbt docs generate` (writes only local target/*.json/html) or `dbt compile` (writes only target/compiled SQL, metadata-only).

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no — unlike 'Run source freshness' (dbt source freshness) and 'Generate docs on run' (dbt docs generate), which ARE surfaced as dedicated dbt Cloud job checkboxes/YAML fields (run_generate_sources, generate_docs), dbt snapshot has no dedicated toggle. It must be added as an explicit command in the job's execute_steps/commands list (or folded into a `dbt build` step, which also runs snapshots).
- **Notes:** Include it as a normal step string, e.g. "dbt snapshot" or "dbt snapshot --select tag:pii_history". Typically placed early in the job (before downstream models that select from the snapshot) since snapshot tables are often treated like sources for later transformations. Should run on a schedule aligned to how fast the source data changes (dbt docs guidance: between hourly and daily; more frequent is usually unnecessary and wasteful).

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| account_id / project_id / environment_id | `memory` | Standard dbt Cloud job identifiers — resolved from stored account/project/environment defaults, same as any other job step, not specific to this command. |
| snapshot selection (--select value, e.g. specific snapshot name, tag, or all) | `ask_user` | Agent cannot infer which snapshots the user wants run without either the user specifying or the project having only one snapshot; must confirm scope (all snapshots vs a subset) since selection determines what tables get written. |
| whether to run standalone vs bundled into `dbt build` | `ask_user` | Some teams prefer a discrete snapshot step for clearer failure isolation/logging; others fold snapshots into `dbt build`. Ask if not stated, since it changes job structure. |
| schedule/frequency for the job containing this step | `ask_user` | Snapshot cadence should match source data change rate per dbt docs; this is a business/data decision, not inferable. |
| existing snapshot config (strategy, unique_key) in project | `have` | This lives in the project's snapshot YAML/SQL files already, not something the job-author agent sets — job authoring only decides whether/how to invoke the command, not its internal config. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Restrict the run to a subset of snapshots by name, tag, path, or other node-selection syntax (e.g. "dbt snapshot --select tag:daily" or "--select orders_snapshot").
- **Data effect:** Narrows which snapshot tables get written to; does not change the fact that matched snapshots still perform real inserts/updates to the warehouse.
- **Info needed:** Ask the user which snapshots/tags they want covered, unless the project has exactly one snapshot or the user already said "all snapshots." CLI best practice per dbt docs: quote the selector (e.g. --select "tag:pii") for cross-platform reliability.
- **When to include:** Include when the user wants only specific snapshot(s) run rather than the full set, or when snapshots are split across teams/domains and only one domain should run in this job.
- **Good vs bad:** Good: `dbt snapshot --select tag:finance` isolates finance snapshots into their own scheduled cadence separate from other domains. Bad: omitting --select when the project has dozens of unrelated snapshots on very different cadences, forcing all of them onto one schedule.

### `--exclude`
- **Purpose:** Run all snapshots except the ones matching the given selector.
- **Data effect:** Same as --select — governs which tables get written, inverted logic.
- **Info needed:** Ask the user which snapshot(s) to exclude if they describe the job as "run everything except X."
- **When to include:** Use when the easier/shorter selector expression is an exclusion rather than an inclusion list.
- **Good vs bad:** Good: excluding a known-slow or currently-broken snapshot temporarily. Bad: using --exclude with a stale/forgotten list that silently drops new snapshots from being run as the project grows.

### `--threads`
- **Purpose:** Global flag controlling how many snapshots/resources run in parallel.
- **Data effect:** No change to what is written, only execution concurrency against the warehouse.
- **Info needed:** Not required; falls back to project/profile default. Only ask if user has specific warehouse concurrency/cost concerns.
- **When to include:** Rarely needed as an override for a snapshot step specifically; leave default unless warehouse contention is a known issue.
- **Good vs bad:** Good: lowering threads if snapshot tables are large and causing warehouse contention during business hours. Bad: cranking threads up on a small warehouse just to save minutes, risking throttling/concurrency errors.

### `--target`
- **Purpose:** Global flag to select which profile target/connection to run against.
- **Data effect:** Determines which warehouse/schema receives the writes — same command, different destination.
- **Info needed:** In dbt Cloud jobs this is normally controlled by the job's environment, not passed manually; ask only if the user needs a non-default target override.
- **When to include:** Generally omit in dbt Cloud job YAML since environment/connection is already scoped by the job's environment_id.
- **Good vs bad:** Good: leaving it unset and letting the job's environment govern the target. Bad: hardcoding --target in a job step, which can silently point snapshots at the wrong warehouse if environments change.

### `--vars`
- **Purpose:** Passes variables into the Jinja context for the snapshot run (e.g. for parameterized snapshot config).
- **Data effect:** No direct read/write effect itself, but can change snapshot behavior (e.g. conditional logic in snapshot SQL) and thus what gets written.
- **Info needed:** Ask the user only if their snapshots are known to use custom vars; most snapshot configs don't need this.
- **When to include:** Include only if the project's snapshot definitions reference dbt vars that must be supplied at run time.
- **Good vs bad:** Good: passing a var to toggle a backfill mode explicitly and intentionally. Bad: passing ad hoc vars in a scheduled job without documenting why, making the job's behavior non-obvious to other maintainers.

## Best practices

- **Schedule dbt snapshot at a cadence matching how fast the underlying source data actually changes (hourly to daily per dbt guidance), and run it during low-usage/off-peak warehouse windows.**
  - Why: Snapshots only capture the state at execution time — running too infrequently loses history between runs (missed intermediate changes for volatile tables), while running too frequently wastes warehouse compute/cost for data that rarely changes.
- **Use --select/tags to scope snapshot steps by domain/cadence rather than running every snapshot in the project on one schedule.**
  - Why: Different source tables change at different rates and belong to different owners; a single monolithic snapshot step couples unrelated failure domains and forces a one-size-fits-all schedule.

## Anti-patterns

- **Treating dbt snapshot as safe/idempotent to re-run freely or trigger ad hoc in CI/PR jobs.**
  - Why: Every execution can insert new history rows into a real warehouse table; running it unnecessarily (e.g. on every CI build) pollutes snapshot history with spurious versions and cannot be cleanly undone the way a CI job's ephemeral schema can — snapshots are stateful, unlike `dbt build`'s models in a temp schema.
- **Changing an existing snapshot's strategy or unique_key and pushing straight to the production scheduled job without testing in dev/staging first.**
  - Why: dbt docs explicitly warn that a non-unique unique_key or a strategy change on an existing snapshot table produces incorrect row versioning/history that can be hard to detect and expensive to repair after it has already been written into production history.

## Overlaps with

- dbt build (also runs snapshots alongside models/tests/seeds)
- dbt source freshness (separate command, has its own dedicated dbt Cloud toggle, often confused with snapshot but unrelated — freshness only checks source recency, doesn't write SCD history)
- dbt run (does not include snapshots; teams sometimes mistakenly assume run covers them)
- dbt test (can test snapshot resources' data once snapshotted)
