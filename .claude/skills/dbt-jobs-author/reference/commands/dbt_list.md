# dbt list

**Aliases:** dbt ls

## What it does

Lists resources (models, seeds, tests, sources, snapshots, exposures, semantic_models, metrics, functions, etc.) in the dbt project that match a given node-selection criteria. It reads the connection profile to resolve target-specific/env-aware logic (e.g. target.name conditionals, source database names) but never opens a database connection or issues any queries — it is purely a manifest/parse-time operation. Commonly used to preview/debug what a --select expression will resolve to before running it for real.

## Effect on warehouse data

**Classification:** `read-only`

dbt ls performs no warehouse I/O at all — it does not connect to the database or execute SQL. It only parses the project graph (compiling Jinja/config as needed) and prints node names/paths/JSON to stdout (or a manifest.json/run_results style artifact if --output is redirected). No tables, views, or rows are created, modified, or read in the warehouse; nothing beyond local target/ artifacts and stdout is written.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no — dbt Cloud has no checkbox/toggle for dbt ls (unlike 'Run source freshness' -> dbt source freshness, or 'Generate docs on run' -> dbt docs generate). It must be added manually as a command step.
- **Notes:** It CAN be added as a command step in a dbt Cloud job (deploy or CI), and dbt-jobs-as-code supports arbitrary command strings in a job's execute_steps/steps list. However it is rarely useful as a scheduled production step since it produces no build/test side effects — its main value is local/CI debugging of selectors, or as a lightweight step to log/verify what a subsequent build/test/run step will select (e.g., piping output to logs, or using --output json for a downstream script/CI gate). It does not fail the job on 'nothing selected' in the same way build/run steps might be expected to.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| --select expression | `ask_user` | The job author must specify what to list; agent should ask the user for the selection criteria (models/tags/paths/state) unless it's mirroring a selector already used elsewhere in the same job (in which case reuse it, don't ask twice). |
| --resource-type | `ask_user` | Only needed if the user wants to restrict output to a specific resource type (e.g. test, source, model); default includes all types except analysis. Ask only if ambiguous or if the user's intent implies filtering (e.g. 'list the tests that will run'). |
| --output format | `ask_user` | Ask only if the output will be consumed downstream (e.g. json for scripting); default (name) is fine for a simple visibility/debug step. |
| account/environment/job IDs, connection profile | `memory` | Standard dbt Cloud job scaffolding (account_id, project_id, environment_id) comes from stored memory/defaults already used for other steps in the job, not from re-asking the user. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s SELECTION_ARG`
- **Purpose:** Filters which nodes are listed, using the standard dbt node-selection syntax (graph operators, tags, paths, state:modified, etc.)
- **Data effect:** None — selection only changes what's printed, not any warehouse behavior.
- **Info needed:** Must ask the user what they want listed/validated unless it's copied from another step's selector in the same job.
- **When to include:** Include whenever the step's purpose is to preview or gate on a specific subset of the DAG; omit (list everything) only for a full-project inventory dump.
- **Good vs bad:** Good: dbt ls --select state:modified+ --output json in CI to log the exact impacted node set before a slim build runs.

### `--resource-type`
- **Purpose:** Restricts results to one or more resource types (model, test, source, seed, snapshot, exposure, metric, semantic_model, function, analysis, default, all).
- **Data effect:** None — purely a filter on the listing output.
- **Info needed:** Ask the user only if they want a type-specific list (e.g., 'just show me the tests tagged nightly'); otherwise leave default.
- **When to include:** Include when the user's ask is type-specific (e.g. 'list sources for freshness check' or 'list tests that would run'); skip for a general model listing.
- **Good vs bad:** Good: dbt ls --select tag:nightly --resource-type test to confirm exactly which tests a nightly job will execute.

### `--exclude`
- **Purpose:** Removes matching selectors from the result set returned by --select/default selection.
- **Data effect:** None.
- **Info needed:** Ask the user if they need to carve out exceptions (e.g., exclude deprecated models) from an otherwise broad --select.
- **When to include:** Include only when the user explicitly needs an exclusion; don't add speculatively.
- **Good vs bad:** Bad: adding --exclude defensively with no concrete model in mind, producing an untraceable/undocumented filter.

### `--output {json,name,path,selector}`
- **Purpose:** Controls output format: name (default, node names), json (full node metadata), path (file paths), selector (a reusable selector string).
- **Data effect:** None on the warehouse; changes only the shape of stdout/artifact text.
- **Info needed:** Ask the user only if output will be piped into another tool/script/CI gate (then json or selector is likely needed); default name is fine for human-readable log checks.
- **When to include:** Use json when a downstream script parses the list; use path/selector for advanced selector-reuse workflows; default name otherwise.
- **Good vs bad:** Good: --output json feeding a CI script that posts the impacted-models list as a PR comment.

### `--output-keys`
- **Purpose:** When --output json, controls which node properties (name, resource_type, description, etc.) are included per node.
- **Data effect:** None.
- **Info needed:** Only relevant if --output json is used and the user/downstream consumer needs specific fields; ask only in that advanced case.
- **When to include:** Include only alongside --output json for a scripted consumer; otherwise omit.
- **Good vs bad:** Bad: specifying --output-keys without --output json, which has no effect and signals a misunderstanding of the flag.

## Best practices

- **Use dbt ls as a pre-flight/debug step (locally or in CI logs) to confirm a --select expression resolves to the intended node set before wiring that same selector into the job's real build/run/test step.**
  - Why: Selector syntax (tags, graph operators, state:modified) is easy to get subtly wrong; verifying the resolved list catches an empty selection or an over-broad match before it silently runs (or skips) the wrong models in production.
- **Use --output json with --select state:modified+ in CI jobs to log exactly which nodes a slim/deferred run will touch.**
  - Why: Gives auditable visibility into what a CI job is about to build/test, which is valuable for debugging failed or unexpectedly large CI runs without needing warehouse access.

## Anti-patterns

- **Adding dbt ls as a standalone scheduled production job step that isn't feeding any downstream logic or log review.**
  - Why: It performs no warehouse work, so as a lone scheduled step it just burns a job run slot/compute for output nobody reads — pure waste with no build/test/freshness value.
- **Relying on dbt ls succeeding as a proxy for 'the real build step will succeed'.**
  - Why: dbt ls only validates that the selector parses and resolves nodes at compile time; it does not catch SQL compilation errors against the warehouse, permission issues, or runtime failures, so a green dbt ls step gives false confidence about the subsequent run/build/test step.

## Overlaps with

- dbt run
- dbt build
- dbt test
- dbt compile (also read-only/no warehouse connection, similar parse-time scope)
- dbt source freshness (separate toggle-driven command, not overlapping in mechanics but often confused as a 'listing' step)
- node-selection syntax shared across run/build/test/snapshot/seed --select and --exclude flags
