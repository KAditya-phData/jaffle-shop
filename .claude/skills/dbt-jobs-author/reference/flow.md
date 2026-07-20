# Orchestration flow

One-time setup (prereq check, dbt Cloud environment resolution, `dbt-jobs-as-code` install check) runs automatically via a `PreToolUse` hook (`scripts/run_setup.py`, wired in `.claude/settings.json`) before this skill executes — see [setup.md](setup.md). What follows is the per-job pipeline, run for every new job request.

---

## Per-job pipeline

On every retry loop (steps 4, 8, 10, 11): **3-iteration cap**. After 3 failures:
- Engineer persona → ask the user directly.
- Business persona → escalate per `<project>/.claude/escalation_policy.yml`.

`error_interpreter.py` drives all retry decisions — run it on every non-OK result before looping.

### 1. Parse prompt + detect persona
```bash
python scripts/spec_parser.py "<user prompt>"
```
Returns `{persona, spec, missing}`. Persona is `business` or `engineer` and governs language register for every step below.

### 2. Apply memory defaults
```bash
python scripts/memory_io.py defaults <group>     # schedule, notification, target defaults
python scripts/memory_io.py ids <account> <env>  # account_id, project_id, environment_id
```
Fill these into the spec — the user is never asked for raw IDs.

### 3. Clarify missing fields
Use the question banks in [personas.md](personas.md). Ask only for fields still in `missing`. Business users never see selectors, flags, YAML, or IDs.

### 4. Choose environment + guard
Collect the target environment from the user (DEV/STG/QA — never PROD):
```bash
python scripts/env_guard.py <chosen_env> --persona <persona> --project <name>
```
Returns `{"decision": "allow|deny|ask|escalate", "reason": "..."}`. PROD is **always denied**. If the allowed-env list is unknown: engineer gets `ask`, business gets `escalate`.

### 5. Verify connection
```bash
python scripts/connection_check.py \
  --account-id N --project-id N --environment-id N \
  [--token-env DBT_API_KEY] [--max-age-hours 24] [--force]
```
Creates a throwaway test job in the chosen environment, confirms it exists, then deletes it. Returns `{"ok": true, "created_and_deleted": true}` on success or `{"status": "skipped", "reason": "..."}` when token/tool is absent.

A successful check is cached in `memory/global/setup_cache.yml` under `connection_checks.<account_id>:<project_id>:<environment_id>`. On the next job against the same account/project/environment, if the cached check is younger than `--max-age-hours` (default 24), the live API round-trip is skipped and `{"ok": true, "status": "cached", "verified_at": "..."}` is returned instead. Pass `--force` to bypass the cache.

### 6. Resolve selection
```bash
# Business — dashboard phrase to upstream selector
python scripts/resolve_selection.py dashboard <group> "<phrase>" [--project-dir PATH]

# Engineer — explicit model(s) to upstream selector
python scripts/resolve_selection.py upstream <model> [<model> ...] [--project-dir PATH]
```
Tries the deterministic mapping in `memory/groups/<group>/models.yml` first. Falls back to parsing `target/manifest.json`, then `dbt ls --select +<model>`. Returns:
```json
{"status": "resolved", "primary_models": [...], "selector": "+m1 +m2", "upstream": [...]}
```
or, when mapping is missing:
```json
{"status": "escalate", "reason": "no dashboard->table mapping"}
```
Business persona: escalate to data analysts to add the dashboard→table entry to `models.yml`. Engineer persona: may pass an explicit selector and skip the mapping.

Present the resolved models back to the user in their language before locking the selector.

### 7. Choose command(s) + flags
Decide which dbt command(s) and options become the job's `execute_steps`. Walk [commands/decision_tree.md](commands/decision_tree.md) from the user's intent down to a command, then **load `commands/<command>.md` only for the command(s) you land on** — each per-command file carries the exact warehouse read/write effect, option-by-option decisions, and good/bad practices. The catalog + toggle-vs-step split is in [commands/index.md](commands/index.md). Do not preload every command file; that's the point of the split.

Key defaults from the research: most jobs are a single `dbt build`; CI jobs are `dbt build --select state:modified+`; `--full-refresh` is never a standing schedule flag; `dbt docs generate` / `dbt source freshness` are job toggles unless you want hard-fail semantics; `dbt retry`/`dbt clean`/`dbt deps`/`dbt docs serve` are never job steps.

### 8. Build + validate
```bash
python scripts/yaml_builder.py <spec.json>
python scripts/validate.py <jobs.yml>
```
Returns `{valid: true/false, ...}`. On failure: run `error_interpreter.py`, adjust spec, retry (3-iteration cap).

### 9. Describe + confirm
```bash
python scripts/natural_language_describer.py <spec.json> --persona <persona>
```
Show the description and key fields. **Get explicit user confirmation before proceeding.** A passing dry run is also required — do not skip to persist.

### 10. Dry-run stage 1 (local dbt --empty)
```bash
python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 1
```
Runs `dbt build/run <selection> --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}' --empty` in `--project-dir`. Returns `{ok, stage, error_category, messages}`. On failure: run `error_interpreter.py` to classify and get a follow-up action; retry (3-iteration cap). Most common failure: `NoNodesForSelectionCriteria` → re-run step 6.

### 11. Dry-run stage 2 (sync --no-update)
```bash
python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 2
```
Runs `dbt-jobs-as-code sync --config <project>/jobs/jobs.yml --no-update`. On failure: `error_interpreter.py` → retry (3-iteration cap).

### 12. Ask permission
Explicitly ask the user: "Dry runs passed. Proceed with the full run?" Do not continue without confirmation.

### 13. Full run
Execute the job against the chosen DEV/STG/QA environment.

### 14. Verify
```bash
python scripts/verify_run.py --models m1,m2 --project-dir PATH
```
Parses `target/run_results.json` (falls back to `dbt run-operation` against information_schema). Reports 2–3 example tables with their update times. Returns `{"ok": true, "validated": [...], "examples": [...]}`.

### 15. Persist
```bash
python scripts/memory_io.py append-job <group> <job_key> <job_config_json> --project-dir PATH
```
Writes the final job to `<project>/jobs/jobs.yml`. Edit-scope guard enforced: raises if the write path is outside `<project>/jobs/`.

### 16. Commit path
```bash
python scripts/commit_path.py --persona <persona> --project-dir PATH
```
Detects current branch via `git rev-parse --abbrev-ref HEAD`. Returns:
- `{"decision": "branch_commit_push", "note": "ask user to test the job on dbt Cloud once before promoting to prod"}` — for main-like branches or business persona.
- `{"decision": "ask", "question": "commit directly or create a branch?"}` — for engineer on a feature branch.

Summarize what was created and where. Optionally suggest opening a PR so CI runs `dbt-jobs-as-code plan`/`sync` via `.github/workflows/cd_prod.yml`.
