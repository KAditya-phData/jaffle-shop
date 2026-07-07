# dbt-jobs-as-code YAML examples & flag semantics

## The two variants

Every job is generated in two forms. They differ **only** in the dbt command
strings inside `execute_steps`.

### Final variant (what gets persisted)
The permanent warn-error flag stays so the job **fails loudly** if its selector
ever stops matching anything, instead of silently doing nothing.

```yaml
execute_steps:
  - dbt build --select marts.sales_exec_summary+ --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'
```

### Dry-run variant (what gets tested first)
Same flag plus `--empty`, so dbt builds the DAG and checks selectors/SQL
without materializing data.

```yaml
execute_steps:
  - dbt build --select marts.sales_exec_summary+ --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}' --empty
```

## Full job example (final)

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/dbt-labs/dbt-jobs-as-code/main/src/dbt_jobs_as_code/schemas/load_job_schema.json
jobs:
  sales_exec_weekday:
    account_id: 43791
    project_id: 176941
    environment_id: 134459
    name: "Sales Executive Dashboard - Weekday Refresh [[exec_sales_weekday]]"
    job_type: scheduled
    settings:
      target_name: prod
      threads: 4
    execution:
      timeout_seconds: 0
    run_generate_sources: false
    execute_steps:
      - dbt build --select marts.sales_exec_summary+ --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'
    generate_docs: false
    triggers:
      github_webhook: false
      git_provider_webhook: false
      schedule: true
      on_merge: false
    schedule:
      cron: "0 10 * * 1-5"
    identifier: exec_sales_weekday
    cost_optimization_features:
      - state_aware_orchestration
```

## Schema rules worth remembering
- Required per job: `account_id`, `project_id`, `environment_id`, `name`,
  `settings`, `run_generate_sources`, `execute_steps`, `generate_docs`, `triggers`.
- `schedule` is required unless `job_type` is `ci` or `merge`.
- `custom_environment_variables` keys must start with `DBT_`.
- `identifier` is appended to the name as `[[identifier]]` to distinguish
  managed jobs from UI-created ones.

## JobSpec contract (input to yaml_builder.py)
```json
{
  "job_key": "sales_exec_weekday",
  "name": "Sales Executive Dashboard - Weekday Refresh",
  "identifier": "exec_sales_weekday",
  "business_group": "sales",
  "description": "...",
  "account_id": 43791,
  "environment": {"target": "prod", "project_id": 176941, "environment_id": 134459},
  "schedule": {"cron": "0 10 * * 1-5", "human": "weekday mornings 6am ET"},
  "selection": {"nl_text": "executive sales dashboard", "dbt_selector": "marts.sales_exec_summary+"},
  "command": {"base": "dbt build", "extra_flags": []},
  "job_type": "scheduled",
  "run_generate_sources": false,
  "generate_docs": false,
  "cost_optimization_features": ["state_aware_orchestration"]
}
```
`command.steps` (a list) may be supplied instead of `command.base`+selection
when a job needs multiple commands; the warn-error/`--empty` flags are appended
to each step automatically.
