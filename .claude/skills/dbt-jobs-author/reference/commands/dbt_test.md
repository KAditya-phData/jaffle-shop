# dbt test

## What it does

Runs data tests (schema tests like unique/not_null/relationships/accepted_values plus singular SQL tests) and unit tests defined on models, sources, snapshots, and seeds. It queries the warehouse to evaluate each test's assertion (e.g. run a SELECT that returns failing rows) and reports pass/fail/warn/error per test; it assumes the underlying objects already exist (built via a prior `dbt run`/`dbt build`/`dbt seed`/`dbt snapshot`).

## Effect on warehouse data

**Classification:** `read-only`

dbt test issues SELECT-style queries against existing warehouse objects to evaluate assertions; it does not create, alter, or drop tables/views and does not write rows to the warehouse in the default case. Exception: if a test has store_failures: true configured, dbt WILL create/replace a table of failing rows in the configured schema. Otherwise dbt test only writes local artifacts (target/run_results.json, manifest.json) plus dbt Cloud run logs/metadata — no warehouse tables/views/rows are modified.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** yes
- **Available as a job parameter/toggle instead:** no. Unlike 'Generate docs on run' or 'Run source freshness' (dedicated job toggles mapping to `dbt docs generate` / `dbt source freshness` as implicit steps), `dbt test` is NOT a toggle; it must be an explicit command in execute_steps (or bundled implicitly via `dbt build`, which interleaves run+test).
- **Notes:** Add as a normal execute_steps entry, e.g. 'dbt test' or 'dbt test --select ...'. Commonly placed after 'dbt run'/'dbt seed'/'dbt snapshot' in deploy jobs, or as the core validation step in a CI job (often replaced entirely by a scoped 'dbt build').

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| command position in execute_steps | `have` | Agent decides ordering (after run/seed/snapshot) based on job type; standard convention, no need to ask. |
| account_id / project_id / environment_id | `memory` | Pulled from stored dbt Cloud connection/memory config, not re-asked per command. |
| --select scope | `ask_user` | Whether to test everything or scope to specific models/tags/packages depends on the job's purpose (full refresh vs CI vs targeted) — ask unless user already specified a selection for the job. |
| --exclude scope | `ask_user` | Only needed if user wants to skip known-flaky or slow tests; ask if relevant, otherwise omit. |
| --vars values | `ask_user` | Only needed if the project's tests/models are conditioned on vars; most jobs won't need this — ask only if the user mentions variable-driven behavior. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Scope the test run to a subset of the DAG (by model name, tag, path, package, test_type:data|unit, resource_type, etc.), with indirect selection pulling in tests attached to selected models.
- **Data effect:** None — purely narrows which read-only test queries run.
- **Info needed:** Which models/tags to target; ask the user unless they've already stated the job scope (e.g. 'test only the finance mart').
- **When to include:** Include whenever the job should validate a specific subset (e.g. CI jobs scoped to modified/changed models, or deploy jobs scoped to one mart) rather than the whole project.
- **Good vs bad:** Good: `dbt test --select state:modified+ --defer --state ...` in CI to test only changed models and downstream. Bad: omitting quotes around multi-part selectors, causing shell globbing issues on some OSes.

### `--exclude`
- **Purpose:** Remove a subset of nodes from the selected test set; same syntax as --select. Test exclusion is greedy: if any parent is excluded, the test is excluded too.
- **Data effect:** None — read-only scoping only.
- **Info needed:** Which known-flaky/slow/irrelevant tests or models to skip; ask the user only if they mention wanting exclusions.
- **When to include:** Include when specific tests are known-flaky, long-running, or intentionally out of scope for a given job (e.g. exclude source-freshness-dependent tests in a fast CI job).
- **Good vs bad:** Good: excluding a slow/expensive singular test from a frequent CI job while still running it nightly via a separate job. Bad: excluding failing tests permanently to silence CI noise instead of fixing the underlying data/test issue.

### `--vars`
- **Purpose:** Pass a YAML dict of variables into the project, overriding dbt_project.yml vars, for tests/models that branch on variable values.
- **Data effect:** None directly on the warehouse, but can change which rows/logic a test evaluates if models or tests are conditioned on vars.
- **Info needed:** Exact variable names/values used by the project; must ask the user or check dbt_project.yml since these are project-specific and not guessable.
- **When to include:** Include only if the project's tests or referenced models actually consume vars (e.g. a threshold or environment flag); most jobs omit this entirely.
- **Good vs bad:** Good: `--vars '{min_row_count: 100}'` to parameterize a custom test threshold per environment. Bad: hardcoding environment-specific secrets/values via --vars instead of using dbt Cloud environment variables.

## Best practices

- **Run `dbt test` (or `dbt build`) immediately after the models/seeds/snapshots it depends on, scoped with --select to match what was just built.**
  - Why: Tests assume the objects exist and are fresh; running unscoped or out of order wastes warehouse compute or produces false failures on stale/missing tables.
- **In CI jobs, scope tests to modified + downstream nodes using state comparison (state:modified+) rather than testing the whole project.**
  - Why: Keeps CI fast and cheap while still catching regressions introduced by the PR; full-project tests belong in scheduled deploy jobs, not every CI run.

## Anti-patterns

- **Relying on `dbt test` alone as the only quality gate without also running `dbt build`/`dbt run` first in the same job.**
  - Why: dbt test does not build/refresh objects; testing stale data silently validates yesterday's numbers and can mask real regressions in today's run.
- **Adding --exclude for tests that are failing just to get the job green, without investigation.**
  - Why: Turns the test suite into a rubber stamp and lets real data-quality regressions ship silently to consumers of the warehouse data.

## Overlaps with

- dbt build (interleaves run+test+seed+snapshot, so a separate dbt test step is redundant if dbt build is used)
- dbt run
- dbt seed
- dbt snapshot
- dbt source freshness (separate command/job toggle, not covered by dbt test)
- dbt compile / dbt ls (share the same --select/--exclude/--vars node-selection syntax)
