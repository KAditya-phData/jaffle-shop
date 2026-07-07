# dbt compile

## What it does

Generates executable/compiled SQL from source, model, test, analysis, function, and snapshot files by resolving Jinja (refs, sources, macros) into raw SQL, and writes the output to the target/ directory (compiled_code.sql, manifest.json, run_results.json). It requires a live data platform connection because it runs introspective queries (e.g. macros like run_query, get_columns_in_relation) needed to resolve some Jinja logic. It does NOT materialize anything: no tables/views are created, dropped, or replaced, and no rows are inserted or modified. It is not a prerequisite for dbt run/build (those compile internally); its main uses are debugging/previewing SQL, or as an early step to warm/refresh manifest.json so a later CI or docs job has fresh compiled artifacts.

## Effect on warehouse data

**Classification:** `writes-artifacts-only`

dbt compile does not write to warehouse tables/views/rows -- it is not a materialization command. However it is NOT purely read-only either in the strict sense: because it needs a data platform connection and runs introspective queries against the warehouse (metadata queries, cache population, macros like run_query), it executes SQL a macro author wrote, which in principle could have side effects if a macro is poorly written (e.g. run_query calling a stored procedure). In the normal/expected case it only reads metadata from the warehouse and writes local artifacts (target/compiled_code.sql, manifest.json, run_results.json) -- it does not create/alter/drop objects or write rows.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no -- unlike 'Generate docs on run' or 'Run source freshness' (which are job-level toggles/checkboxes in dbt Cloud), dbt compile is only added as an explicit command step in the job's execute_steps list (or CLI/GitHub Actions step). There is no dedicated UI toggle for it.
- **Notes:** Legitimate uses as a command step in dbt-jobs-as-code YAML (execute_steps: - dbt compile): (1) a lightweight 'merge job' step run on merge to main to refresh environment manifest.json quickly so PR/CI jobs diff against fresh state without waiting for a full build; (2) appended after a build job to refresh compiled SQL/docs artifacts. It is rarely useful as a standalone scheduled production job by itself since it produces no warehouse-visible output -- usually paired with dbt docs generate or as a manifest-refresh step; some teams substitute the lighter 'dbt ls' or 'dbt parse --no-partial-parse' for the same manifest-refresh purpose since those are faster / don't require the same introspection.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| target environment / connection (account_id, project_id, environment_id) | `memory` | Standard dbt Cloud job fields the agent already has from stored account/environment defaults; needed because compile requires a live warehouse connection. |
| --select node selection (optional) | `ask_user` | Only needed if scoping compile to a subset of models; ask which models/tags they want compiled, otherwise default to whole project (no --select). |
| purpose of the compile step (manifest refresh vs. debug/preview SQL) | `ask_user` | Determines whether this belongs in a merge/CI job vs. an ad-hoc/debug run; if unclear, ask why they want this step since it has no warehouse-visible effect. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Scope compilation to a specific set of resources (models, tests, snapshots, analyses) using dbt's standard node-selection syntax, e.g. --select "stg_orders+".
- **Data effect:** None on warehouse data -- still only compiles SQL and writes artifacts for the selected nodes; still runs introspective queries against the warehouse if the selected nodes require them.
- **Info needed:** Which models/tags/paths to include -- ask the user if this job step is meant to be scoped rather than compiling the whole project.
- **When to include:** Include when the goal is to preview/debug a specific model's compiled SQL, or to speed up a targeted manifest refresh; omit (compile whole project) when the purpose is a full manifest refresh for downstream CI comparisons.
- **Good vs bad:** Good: `dbt compile --select stg_orders+` to preview downstream impact of one staging model's SQL before merging. Bad: omitting --select on a huge monorepo project just to check one model, wasting introspection time on unrelated nodes.

### `--exclude`
- **Purpose:** Exclude a set of resources from compilation, using the same node-selection syntax as --select.
- **Data effect:** None on warehouse data -- selection/exclusion only affects which SQL is compiled.
- **Info needed:** Which resources to exclude -- ask user only if they need to skip specific broken/slow models.
- **When to include:** Include only if the user has a known model/tag they want left out of the compile step; rarely needed for compile since it's low-cost.
- **Good vs bad:** Good: excluding a known-broken WIP model tagged `wip` so a merge-job manifest refresh doesn't fail on it. Bad: using --exclude defensively everywhere 'just in case' without a concrete node to skip.

### `--no-introspect`
- **Purpose:** Disables introspective queries entirely; dbt will error if a resource's definition requires one.
- **Data effect:** Reduces warehouse interaction to none/minimal -- makes the command effectively local/offline for resources that don't need introspection.
- **Info needed:** Whether the project relies on introspective macros (run_query, get_columns_in_relation, etc.) -- if unsure, don't set this flag since it can cause failures.
- **When to include:** Include in fast, CI-triggered manifest-refresh steps where the project is known not to need introspection, to speed up the job and avoid unnecessary warehouse load; skip if any selected models use introspective macros.
- **Good vs bad:** Good: adding --no-introspect on a manifest-refresh merge job for a project with no run_query-based macros, cutting warehouse round-trips. Bad: blindly adding it to a project using dbt_utils.get_column_values or similar, causing hard failures.

### `--no-populate-cache`
- **Purpose:** Disables dbt's initial relational cache population (a metadata query dbt normally runs upfront); cache misses are resolved lazily instead.
- **Data effect:** None on warehouse data written; only changes read/metadata-query timing/pattern against the warehouse.
- **Info needed:** None needed from user -- purely a performance flag.
- **When to include:** Include when compiling a small/targeted --select where the upfront full-project cache population is unnecessary overhead; skip for full-project compiles where the cache benefits multiple nodes.
- **Good vs bad:** Good: `dbt compile --no-populate-cache --select my_model` for a quick single-model check. Bad: using it on a full-project compile where many nodes would each trigger cache misses, net-slower than populating upfront.

### `--inline`
- **Purpose:** Compiles an arbitrary ad-hoc dbt-SQL string/query passed on the command line instead of project files, useful for one-off debugging.
- **Data effect:** None on warehouse data (still just compiles, doesn't execute the resulting SQL against tables).
- **Info needed:** The literal SQL/Jinja string to compile -- must come from the user; not something a scheduled job would use.
- **When to include:** Never include in a scheduled/CI job step -- this is an interactive CLI/debugging-only flag, not something to template into jobs-as-code YAML.
- **Good vs bad:** Good: developer runs `dbt compile --inline "select * from {{ ref('raw_orders') }}"` locally to sanity-check a ref. Bad: hardcoding an --inline query into a scheduled job step, which is a debugging tool, not a job-safe pattern.

### `--vars`
- **Purpose:** Supplies variables to the Jinja context at compile time (same as other dbt commands).
- **Data effect:** None on warehouse data directly, though vars can affect which introspective macros run.
- **Info needed:** Specific var key/value pairs the project's macros expect -- ask user or pull from job/environment defaults if the project requires them.
- **When to include:** Include only if the project's compilation depends on runtime vars (common pattern for conditional logic); otherwise omit.
- **Good vs bad:** Good: passing --vars '{run_date: 2026-07-02}' when a macro branches compiled SQL on a date var. Bad: passing unused vars 'just in case', adding noise to the job step with no compile-time effect.

## Best practices

- **Use dbt compile (or the lighter dbt parse --no-partial-parse / dbt ls) as a small, fast merge-triggered job to refresh an environment's manifest.json, so downstream CI/PR jobs diff against current state without waiting on a full build.**
  - Why: Keeps deferral/state comparisons for CI jobs accurate and fast without incurring the cost of a full dbt build.
- **Scope with --select when the only goal is to preview or debug a specific model's generated SQL, rather than compiling the whole project.**
  - Why: Reduces unnecessary warehouse introspection and time when you only care about one model's logic.

## Anti-patterns

- **Relying on dbt compile as a standalone scheduled production job that's expected to 'do the run'.**
  - Why: It never materializes anything in the warehouse -- no tables/views are built or refreshed, so downstream consumers see no new data, giving a false sense that data was updated.
- **Adding dbt compile as a redundant step immediately before/after dbt run or dbt build in the same job.**
  - Why: run/build already compile internally as part of their execution, so a separate compile step is wasted time and an extra warehouse connection/introspection round-trip for no benefit.

## Overlaps with

- dbt run
- dbt build
- dbt parse
- dbt ls
- dbt docs generate
