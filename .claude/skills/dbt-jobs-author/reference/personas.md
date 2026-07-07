# Persona detection & question banks

## Detection

`spec_parser.detect_persona` flags **engineer** when the prompt uses dbt/CLI jargon (`tag:`, `--select`, `dbt build/run/test`, `+model`, `cron`, `--full-refresh`, model prefixes like `fct_`/`dim_`/`stg_`). Otherwise **business**. When ambiguous, ask directly:

> For how I explain things, do you prefer:
> A) Plain business language, or
> B) dbt/YAML terminology (I'm comfortable with that)?

---

## Business persona

Business users describe work in terms of dashboards and reports. They never see selectors, flags, YAML, or raw IDs at any step.

**Clarification questions (plain language):**
- **What to refresh:** "Which dashboard or report should stay up-to-date? Describe it in plain language — I'll map it to the right tables."
- **Timing:** "Roughly what time should this run, and in which time zone?"
- **Failure contact:** "If an update fails, who should be notified (email or Slack)?"
- **Environment:** "Should this run in your development, staging, or QA environment?" (Never offer PROD as an option.)

**Selection resolution (§1.4):**
1. Map the dashboard to its primary tables using `memory/groups/<group>/models.yml`.
2. Resolve **all upstream tables** of those primary tables via `resolve_selection.py dashboard`.
3. If the dashboard→table mapping is missing: **escalate to the data analysts** to add the mapping to `models.yml`. Do not guess. Do not ask the user to provide a selector. File the escalation per `<project>/.claude/escalation_policy.yml`. The primary tables for dashboards are usually `marts` layer models.

**On any unrecoverable step failure** (after 3 iterations): escalate per `<project>/.claude/escalation_policy.yml`. Do not ask the user to debug dbt errors.

**Install check (§1.7):** If `dbt-jobs-as-code` is not installed, recommend installing it in one plain sentence. Do not show install commands.

---

## Engineer persona

Engineers are comfortable with dbt terminology and can interpret errors themselves.

**Clarification questions (dbt terms):**
- **Selection:** "Which selector — `tag:…`, `+model`, `path:`? Or an explicit model list?"
- **Command:** "`dbt build` vs `dbt run` vs `dbt test` / source freshness?"
- **State/flags:** "State-aware or raw selector? Any extra flags like `--full-refresh`, `--defer`, `--state`?"
- **Schedule:** "Cron expression and timezone?"
- **Environment:** "Which DEV, STG, or QA environment?" (PROD is never an option — promote manually.)

**Selection resolution:** May skip the dashboard→table mapping entirely and pass an explicit selector directly to `resolve_selection.py upstream`. If `resolve_selection.py` returns `escalate`, the engineer is shown the reason and asked how to proceed.

**On step failure** (after 3 iterations): ask the user directly for guidance.

**Install check (§1.7):** If `dbt-jobs-as-code` is not installed, return the full install and setup steps pointing at [setup.md](setup.md) §3.1–3.2.

---

## Always confirm before writing

Regardless of persona, show the description from `natural_language_describer.py` and get explicit confirmation. A passing dry run (both stages) is required before persisting.

---

## Field → question map

| Missing field | Business question | Engineer question |
|---|---|---|
| `business_group` | "Which team is this for (Sales, Marketing, Finance)?" | same |
| `selection.dbt_selector` | "Which dashboard or report should this refresh?" | "Which selector or model list?" |
| `schedule.cron` | "What time and timezone?" | "Cron expression and timezone?" |
| `environment.*` | "Development, staging, or QA?" (IDs from memory — never ask for IDs) | "Which DEV/STG/QA environment?" |
| `notifications.on_failure` | "Who should be notified if it fails (email or Slack)?" | same |
