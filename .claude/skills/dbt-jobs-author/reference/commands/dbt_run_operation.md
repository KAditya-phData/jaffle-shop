# dbt run-operation

## What it does

Invokes a named macro (or, in dbt Core 1.12+, an ad hoc SQL/Jinja string via --sql) directly against the target database, outside the normal model/test/seed/snapshot build graph. dbt compiles the macro with any supplied --args and executes it; unlike hooks, the macro must explicitly run a query (via a statement block or run_query) or it just returns a string without executing anything. It exits after the macro completes — it is not part of node selection or the DAG.

## Effect on warehouse data

**Classification:** `writes-warehouse-data`

Not read-only by default and not artifact-only: the actual effect is entirely defined by the macro (or --sql string) being invoked. It can be pure metadata/read (e.g. a macro that only logs or queries information_schema), or it can DDL/DML directly against the warehouse (grants, drop table, clone schema, delete stale rows, apply masking policies, vacuum/optimize commands, etc.) with no dbt-managed rollback or lineage tracking. Because dbt cannot introspect what a macro does, a job-author agent must treat every run-operation step as a potential warehouse write and ask what the macro does before assuming it's safe.

## Use in a dbt Cloud job

- **Can run as a step:** yes
- **Should run:** situational
- **Available as a job parameter/toggle instead:** no - unlike 'Generate docs on run' or 'Run source freshness' (which are job-level toggles), run-operation is always an explicit execute_steps command line, e.g. "dbt run-operation macro_name --args '{...}'"
- **Notes:** Fully supported as a job step in both the dbt Cloud UI and dbt-jobs-as-code YAML (execute_steps list). Commonly placed as a pre-hook-like first step (e.g. clone_all_product, grant_select) or a post-run cleanup step (e.g. clean_stale_models). Whether it SHOULD run depends entirely on what the macro does — safe for idempotent maintenance macros, risky for destructive one-off macros in an unattended scheduled job.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| macro name | `ask_user` | Agent cannot know which project-specific macro to invoke; must ask, and ideally confirm the macro exists in the project and inspect what it does (read vs write) before adding it to a job. |
| args (--args) key/values the macro expects | `ask_user` | Macro-specific keyword arguments; agent has no way to infer these without seeing the macro definition or being told by the user. |
| whether to use --sql instead of a macro | `ask_user` | Only relevant on dbt Core 1.12+; ask if the user wants an ad hoc statement vs a version-controlled macro (macro is generally preferred for recurring/scheduled jobs). |
| position in execute_steps (before/after builds) | `ask_user` | Depends on intent, e.g. pre-clean vs post-cleanup vs grants-after-build; agent should ask or infer from stated purpose. |
| target/environment ID, project ID | `memory` | Standard job-authoring context (account/project/environment defaults) already handled by the jobs-as-code memory/config, not specific to this command. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--args`
- **Purpose:** Supplies a YAML-formatted dictionary of keyword arguments that dbt maps onto the macro's parameters, e.g. --args '{days: 7, dry_run: True}'.
- **Data effect:** No effect by itself — it only parameterizes the macro call. The read/write outcome is determined by what the macro does with those args (e.g. a 'days' arg controlling how many days of stale objects get dropped).
- **Info needed:** Must know the exact parameter names/types the target macro expects; almost always must ask the user or read the macro source, since these are project-specific and not guessable.
- **When to include:** Include whenever the macro requires parameters (most non-trivial macros do); omit only for zero-arg macros.
- **Good vs bad:** Good: dbt run-operation clean_stale_models --args '{days: 7, dry_run: True}' makes the retention window explicit and reviewable. Bad: passing positional-looking or guessed key names that don't match the macro's actual signature, causing a Jinja undefined-variable failure at runtime.

### `--sql`
- **Purpose:** Executes an ad hoc SQL/Jinja string directly against the warehouse without needing a predefined macro (dbt Core 1.12+ only). Cannot be combined with a macro name or --args.
- **Data effect:** Direct warehouse write/DDL risk is high and explicit — commonly used for one-off DROP TABLE, GRANT, or data-fix statements run straight against the target database.
- **Info needed:** Need the exact SQL/Jinja string and confirmation of intent; because it bypasses version-controlled macros, must ask the user to confirm this is intentional for a recurring job (usually a red flag for scheduled/CI use).
- **When to include:** Avoid in recurring scheduled/CI jobs — appropriate mainly for genuine one-off manual runs, not something to hardcode into a repeating job definition. If the same statement needs to recur, prefer converting it to a macro.
- **Good vs bad:** Good: a one-time manual invocation like dbt run-operation --sql "DROP TABLE IF EXISTS my_schema.old_table" for a documented cleanup task, never checked into a recurring job. Bad: baking a --sql DROP/GRANT statement into a scheduled job step, so an untracked destructive statement silently re-runs on every schedule with no code review trail.

### `[macro] (positional macro name)`
- **Purpose:** Specifies which macro to invoke; required unless --sql is used, mutually exclusive with --sql.
- **Data effect:** Indirect — determined entirely by the macro body.
- **Info needed:** Must ask the user which macro, and ideally confirm it is already defined/tested in the project's macros directory.
- **When to include:** Always required for the classic (non --sql) form of this command.
- **Good vs bad:** Good: referencing a macro that's already reviewed and used elsewhere (e.g. grant_select) so behavior is known and version-controlled. Bad: inventing/assuming a macro name that doesn't exist in the project, which fails the job step immediately.

## Best practices

- **Only add run-operation steps for macros that are idempotent and already tested outside the scheduled job (e.g. run manually or in a dev environment first).**
  - Why: Because dbt cannot show what the macro does, an unattended scheduled/CI run of an untested macro can silently drop, alter, or corrupt warehouse objects with no dbt-native rollback.
- **Prefer macros over --sql for anything that will run more than once, and keep the macro version-controlled in the project's macros/ folder.**
  - Why: Ad hoc --sql strings in a job step aren't reviewed/tested the way a checked-in macro is, and drift silently from what's in source control.

## Anti-patterns

- **Hardcoding a destructive one-off maintenance macro (e.g. a full schema clone/drop) as a permanent step in a recurring scheduled job.**
  - Why: What was meant as a single manual fix keeps re-running on every scheduled execution, potentially repeating destructive operations against production data every run.
- **Adding a run-operation step with --args values guessed or copied from an unrelated example without confirming the macro's actual parameter names/types.**
  - Why: Mismatched args cause the macro to fail at runtime (breaking the whole job) or, worse, silently apply wrong values (e.g. wrong retention window) to a destructive macro.

## Overlaps with

- dbt build/run/test/seed/snapshot (run-operation macros often replace or supplement pre/post-hooks that would otherwise be attached to these)
- dbt source freshness (some teams implement custom freshness/alerting logic as a run-operation macro instead)
- dbt clone (clone-style macros invoked via run-operation, e.g. clone_all_product, overlap with dbt's native clone command)
- on-run-start/on-run-end hooks (same macro-invocation mechanism, but hooks fire automatically around other commands whereas run-operation is explicit)
