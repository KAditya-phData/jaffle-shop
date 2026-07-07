# Orchestration flow

Two phases: **A — one-time setup** (run once per machine/project), **B — per-job pipeline** (run for every new job request).

---

## Phase A — One-time setup

### A1. Prereq check
```bash
# Linux/Mac
bash scripts/env_check.sh

# Windows
pwsh scripts/env_check.ps1
```
Checks for `dbt` and `python` (or `python3`). **Stops immediately if either is missing** — do not proceed until both are present. Then runs `python3 --version`, `dbt --version`, `dbt debug`.

### A2. Resolve dbt Cloud environments
```bash
python scripts/dbt_cloud_env.py
# or with explicit config:
python scripts/dbt_cloud_env.py --config ~/.dbt/dbt_cloud.yml
```
Reads `active-project` from the dbt Cloud config, calls the dbt Cloud API, and returns:
```json
{"account_id": 1, "project_id": 2, "host": "...", "environments": [...]}
```
Token is never printed. If config or token is missing, returns `{"status": "unavailable", "reason": "..."}` and the orchestrator continues without the environment list.

### A3. Install check
```bash
python scripts/install_check.py --persona business
# or
python scripts/install_check.py --persona engineer
```
Checks `dbt-jobs-as-code` availability. Business persona receives a plain-language recommendation; engineer persona receives install/setup steps pointing at [setup.md](setup.md) §3.1–3.2.

### A4. Cache setup outputs
Call `memory_io.save_setup_cache(data)` to write resolved account ID, project ID, host, environment list, and tool versions to `memory/global/setup_cache.yml`. Never cache the token.

---

## Phase B — Per-job pipeline

On every retry loop (steps B4, B7, B9, B10): **3-iteration cap**. After 3 failures:
- Engineer persona → ask the user directly.
- Business persona → escalate per `<project>/.claude/escalation_policy.yml`.

`error_interpreter.py` drives all retry decisions — run it on every non-OK result before looping.

### B1. Parse prompt + detect persona
```bash
python scripts/spec_parser.py "<user prompt>"
```
Returns `{persona, spec, missing}`. Persona is `business` or `engineer` and governs language register for every step below.

### B2. Apply memory defaults
```bash
python scripts/memory_io.py defaults <group>     # schedule, notification, target defaults
python scripts/memory_io.py ids <account> <env>  # account_id, project_id, environment_id
```
Fill these into the spec — the user is never asked for raw IDs.

### B3. Clarify missing fields
Use the question banks in [personas.md](personas.md). Ask only for fields still in `missing`. Business users never see selectors, flags, YAML, or IDs.

### B4. Choose environment + guard
Collect the target environment from the user (DEV/STG/QA — never PROD):
```bash
python scripts/env_guard.py <chosen_env> --persona <persona> --project <name>
```
Returns `{"decision": "allow|deny|ask|escalate", "reason": "..."}`. PROD is **always denied**. If the allowed-env list is unknown: engineer gets `ask`, business gets `escalate`.

### B5. Verify connection
```bash
python scripts/connection_check.py \
  --account-id N --project-id N --environment-id N \
  [--token-env DBT_API_TOKEN] [--max-age-hours 24] [--force]
```
Creates a throwaway test job in the chosen environment, confirms it exists, then deletes it. Returns `{"ok": true, "created_and_deleted": true}` on success or `{"status": "skipped", "reason": "..."}` when token/tool is absent.

A successful check is cached in `memory/global/setup_cache.yml` under `connection_checks.<account_id>:<project_id>:<environment_id>`. On the next job against the same account/project/environment, if the cached check is younger than `--max-age-hours` (default 24), the live API round-trip is skipped and `{"ok": true, "status": "cached", "verified_at": "..."}` is returned instead. Pass `--force` to bypass the cache.

### B6. Resolve selection
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

### B6.5. Choose command(s) + flags
Decide which dbt command(s) and options become the job's `execute_steps`. Walk [commands/decision_tree.md](commands/decision_tree.md) from the user's intent down to a command, then **load `commands/<command>.md` only for the command(s) you land on** — each per-command file carries the exact warehouse read/write effect, option-by-option decisions, and good/bad practices. The catalog + toggle-vs-step split is in [commands/index.md](commands/index.md). Do not preload every command file; that's the point of the split.

Key defaults from the research: most jobs are a single `dbt build`; CI jobs are `dbt build --select state:modified+`; `--full-refresh` is never a standing schedule flag; `dbt docs generate` / `dbt source freshness` are job toggles unless you want hard-fail semantics; `dbt retry`/`dbt clean`/`dbt deps`/`dbt docs serve` are never job steps.

### B7. Build + validate
```bash
python scripts/yaml_builder.py <spec.json>
python scripts/validate.py <jobs.yml>
```
Returns `{valid: true/false, ...}`. On failure: run `error_interpreter.py`, adjust spec, retry (3-iteration cap).

### B8. Describe + confirm
```bash
python scripts/natural_language_describer.py <spec.json> --persona <persona>
```
Show the description and key fields. **Get explicit user confirmation before proceeding.** A passing dry run is also required — do not skip to persist.

### B9. Dry-run stage 1 (local dbt --empty)
```bash
python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 1
```
Runs `dbt build/run <selection> --warn-error-options '{"error":["NoNodesForSelectionCriteria"]}' --empty` in `--project-dir`. Returns `{ok, stage, error_category, messages}`. On failure: run `error_interpreter.py` to classify and get a follow-up action; retry (3-iteration cap). Most common failure: `NoNodesForSelectionCriteria` → re-run B6.

### B10. Dry-run stage 2 (sync --no-update)
```bash
python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 2
```
Runs `dbt-jobs-as-code sync --config <project>/jobs/jobs.yml --no-update`. On failure: `error_interpreter.py` → retry (3-iteration cap).

### B11. Ask permission
Explicitly ask the user: "Dry runs passed. Proceed with the full run?" Do not continue without confirmation.

### B12. Full run
Execute the job against the chosen DEV/STG/QA environment.

### B13. Verify
```bash
python scripts/verify_run.py --models m1,m2 --project-dir PATH
```
Parses `target/run_results.json` (falls back to `dbt run-operation` against information_schema). Reports 2–3 example tables with their update times. Returns `{"ok": true, "validated": [...], "examples": [...]}`.

### B14. Persist
```bash
python scripts/memory_io.py append-job <group> <job_key> <job_config_json> --project-dir PATH
```
Writes the final job to `<project>/jobs/jobs.yml`. Edit-scope guard enforced: raises if the write path is outside `<project>/jobs/`.

### B15. Commit path
```bash
python scripts/commit_path.py --persona <persona> --project-dir PATH
```
Detects current branch via `git rev-parse --abbrev-ref HEAD`. Returns:
- `{"decision": "branch_commit_push", "note": "ask user to test the job on dbt Cloud once before promoting to prod"}` — for main-like branches or business persona.
- `{"decision": "ask", "question": "commit directly or create a branch?"}` — for engineer on a feature branch.

Summarize what was created and where. Optionally suggest opening a PR so CI runs `dbt-jobs-as-code plan`/`sync` via `.github/workflows/cd_prod.yml`.
