# dbt show

## What it does

Compiles and executes the SQL for a single selected model (or an ad-hoc --inline query) against the warehouse and previews the result set in the terminal/logs. It always compiles and runs the query fresh from source — it does NOT select from an already-materialized relation, even if the model was just run.

## Effect on warehouse data

**Classification:** `read-only`

dbt show issues a SELECT-style query (wrapped with a LIMIT n) against the warehouse and only returns rows for display in logs/terminal/--output json. It does not create, replace, or write to any table/view, and does not persist results to any file by default. The only way it writes anything is if the user's --inline SQL itself contains DDL/DML (a footgun, not the intended use), or if the warehouse role has elevated permissions — dbt's own docs recommend a read-only role/profile for running it. It is classified alongside dbt parse as a 'read' command in dbt's parallel-execution model, safe to run alongside write commands like dbt build.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** no
- **Available as a job parameter/toggle instead:** no — unlike dbt docs generate ("Generate docs on run" checkbox) or dbt source freshness ("Run source freshness" checkbox), dbt show has no dedicated job-level toggle/parameter in dbt Cloud. It can only be added as a manual command step in the Commands list.
- **Notes:** It can technically be added as a command step in a dbt Cloud job, but it is fundamentally an interactive/ad-hoc preview tool meant for CLI development (e.g., checking a model's output during iteration). It selects only a single node (no multi-node selectors, no graph operators like + or @), so it can't preview a set of models. In a scheduled/CI job it produces no artifact of lasting value beyond log text — there's nothing downstream can consume, and a step failure would block the rest of the job for no operational benefit.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| single node --select target (model/source/seed name) | `ask_user` | dbt show only supports selecting exactly one node; the agent must ask the user which single model/query they want previewed — this is not something to default or infer, since including it in a recurring job is unusual in the first place. |
| --limit row count | `ask_user` | Optional; defaults to 5 if not given. Only ask if the user cares about a specific preview size. |
| account_id / project_id / environment_id / job placement | `memory` | Standard dbt Cloud job scaffolding info (account, project, environment) the job-authoring agent already holds from stored memory/config, same as for any other command step. |
| warehouse credentials/role permissions | `have` | Not something the job step itself configures — it inherits the job's connection; the agent doesn't need to ask, but should flag that a read-only role is recommended if --inline is used. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--select / -s`
- **Purpose:** Chooses which single resource (model, source, seed, snapshot) to compile and preview.
- **Data effect:** No write effect; determines which SELECT query is run.
- **Info needed:** Ask the user for the exact single node name — dbt show explicitly does not support multi-node selectors, graph operators (+, @, tag:), or set operations; only one resolved node is allowed.
- **When to include:** Always required (or use --inline instead) since dbt show needs exactly one target to preview.
- **Good vs bad:** Good: `dbt show --select stg_orders` to sanity-check one model's shape during development. Bad: expecting `dbt show --select tag:nightly+` to preview a whole tag set — multi-node selection is not supported and will error.

### `--limit`
- **Purpose:** Controls how many rows are retrieved and displayed; default is 5.
- **Data effect:** Still read-only, but changes the actual SQL sent to the warehouse — dbt wraps the query in a subquery/CTE with a SQL LIMIT n clause, so the warehouse only computes/returns n rows (a real performance/cost optimization, not just client-side truncation).
- **Info needed:** Ask the user only if they want a non-default preview size; otherwise leave at default 5.
- **When to include:** Include only when the user wants more/fewer sample rows than the default; irrelevant for automation value in a scheduled job.
- **Good vs bad:** Good: `--limit 20` to eyeball more sample rows without scanning the full table, since the LIMIT is pushed into the SQL itself. Bad: `--limit -1` (unlimited) on a huge model just to 'be safe' — defeats the cost-saving purpose and can trigger a full table scan.

### `--inline`
- **Purpose:** Runs an ad-hoc raw SQL string instead of a compiled model/node.
- **Data effect:** Read-only for a normal SELECT, but since it's raw SQL, nothing stops a user from putting DDL/DML in it — dbt does not sanitize it. This is the one path where dbt show could write to the warehouse if misused.
- **Info needed:** Ask the user for the exact SQL text; warn if it looks like DDL/DML.
- **When to include:** Avoid in scheduled/CI jobs entirely — there's no legitimate automation case for ad-hoc inline SQL preview in a non-interactive pipeline.
- **Good vs bad:** Good: `dbt show --inline "select 1"` as a quick interactive connection/debug check from the CLI. Bad: piping user-supplied or dynamically-generated SQL into `--inline` inside an automated job — an unaudited path to run arbitrary statements against the warehouse.

## Best practices

- **If you must include it (e.g., a one-off diagnostic job), pair it with a read-only warehouse role/profile.**
  - Why: Since --inline allows arbitrary SQL and dbt does not restrict it to SELECT, a read-only credential is the actual safety boundary the docs recommend, not the command itself.
- **Keep --limit small and always use --select with a single concrete node.**
  - Why: Because --limit is pushed into the SQL itself, a small limit keeps warehouse compute/cost minimal for what is purely a diagnostic/log-preview step with no durable output.

## Anti-patterns

- **Adding dbt show as a step in a recurring scheduled or CI job.**
  - Why: It only supports a single node, produces no artifact usable by later steps, and a failure blocks/fails the rest of the job chain for a step whose only output is human-readable log text — there is no automation value, only added fragility.
- **Using --inline with dynamic/user-supplied SQL inside a job.**
  - Why: dbt does not validate that inline SQL is read-only; combined with a non-read-only job connection, this turns an intended 'preview' step into an unaudited path for arbitrary warehouse writes.

## Overlaps with

- dbt compile (both compile the SQL; show additionally executes and returns rows)
- dbt run / dbt build (show explicitly does NOT read from the materialized relation these commands produce — it recompiles from source every time)
- dbt docs generate (both are 'preview/inspect' style commands with no warehouse writes, but docs generate is exposed as a job checkbox/parameter while show is not)
- dbt source freshness (also a read-oriented diagnostic command that IS exposed as a job checkbox, unlike show)
