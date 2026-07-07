---
name: dbt-jobs-author
description: Turn a natural-language request into a validated dbt Cloud job defined with dbt-jobs-as-code. Use when someone describes a recurring dbt workflow or dashboard refresh and wants it created/updated as a scheduled job, for both business users and dbt engineers. Detects persona, asks persona-appropriate questions, verifies the dbt connection, resolves the selection, dry-runs with safety flags, then persists the job to <project>/jobs/jobs.yml.
allowed-tools: Read, Write, Bash
model: inherit
---

# dbt-jobs-author

Authors and updates dbt Cloud jobs (managed via `dbt-jobs-as-code`) from natural-language prompts.
It hides dbt jargon from business users, speaks dbt to engineers, **always dry-runs with safety flags before writing**, verifies connections, guards against PROD writes, and stores jobs as YAML under `<project>/jobs/jobs.yml`.

No MCP servers are used. All logic runs through plain Python scripts under `scripts/`.

See [reference/flow.md](reference/flow.md) for the full programmatic pipeline and [reference/personas.md](reference/personas.md) for per-persona behavior.

---

## One-time setup (§2.1)

Run once per machine/project before authoring any job. Details in [reference/setup.md](reference/setup.md).

1. **Prereq check** — run `scripts/env_check.sh` (Linux/Mac) or `scripts/env_check.ps1` (Windows).
   Stops immediately if `dbt` or `python` is missing.
2. **Resolve dbt Cloud environments** — `python scripts/dbt_cloud_env.py` reads `~/.dbt/dbt_cloud.yml`
   and lists available environments. Result is cached in `memory/global/setup_cache.yml`.
3. **Install check** — `python scripts/install_check.py --persona <persona>` confirms
   `dbt-jobs-as-code` is available. Business persona gets a recommendation; engineer gets install steps.
4. Cache the resolved account, project, host, env list, and tool versions in `memory/global/setup_cache.yml`
   (token is never stored).

---

## Per-job pipeline (§2.2)

Follow [reference/flow.md](reference/flow.md) step by step.

1. **Parse prompt + detect persona** — `python scripts/spec_parser.py "<prompt>"` → `{persona, spec, missing}`.
2. **Apply memory defaults** — `python scripts/memory_io.py defaults <group>` and `python scripts/memory_io.py ids <account> <env>` to fill account/project/environment IDs.
3. **Clarify missing fields** — ask only what is still in `missing`, using the question banks in [reference/personas.md](reference/personas.md). Never ask business users for selectors, flags, or IDs.
4. **Choose environment + guard** — `python scripts/env_guard.py <chosen_env>`. DEV/STG/QA are allowed; **PROD is always denied**. Unknown list → engineer asks user, business escalates.
5. **Verify connection** — `python scripts/connection_check.py --account-id N --project-id N --environment-id N`. Creates and immediately deletes a throwaway test job to confirm permissions. Result is cached for 24h (per account/project/environment) in `memory/global/setup_cache.yml`; a fresh job against the same environment within that window skips the live check. Override with `--max-age-hours` or force a live check with `--force`.
6. **Resolve selection** — `python scripts/resolve_selection.py dashboard <group> "<phrase>"` (business) or `python scripts/resolve_selection.py upstream <model> ...` (engineer). Deterministic mapping from `memory/groups/<group>/models.yml` is tried first; falls back to live dbt. If mapping is unknown for a business user, escalate to data analysts to add the dashboard→table mapping to `models.yml`.
7. **Choose command(s) + flags** — decide which dbt command(s) and options become the job's steps. Walk [reference/commands/decision_tree.md](reference/commands/decision_tree.md) from the user's intent, then **load `reference/commands/<command>.md` only for the command(s) you land on** (progressive disclosure — do not load all of them). See [reference/commands/index.md](reference/commands/index.md) for the catalog + which behaviors are job *toggles* vs *steps*.
8. **Build + validate** — `python scripts/yaml_builder.py <spec.json>` then `python scripts/validate.py <jobs.yml>`.
9. **Describe + confirm** — `python scripts/natural_language_describer.py <spec.json> --persona <persona>`. Show description and get explicit confirmation before writing anything.
10. **Dry-run stage 1** — `python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 1`. Runs `dbt build/run --empty` with the warn-error flag. On error: `python scripts/error_interpreter.py --persona <persona>` drives the retry (3-iteration cap; engineer → ask user; business → escalate).
11. **Dry-run stage 2** — `python scripts/dry_run.py --spec spec.json --project-dir PATH --stage 2`. Runs `dbt-jobs-as-code sync --no-update`.
12. **Ask permission** — get explicit user approval to write and run the real job.
13. **Full run** — execute the job.
14. **Verify** — `python scripts/verify_run.py --models m1,m2 --project-dir PATH`. Checks table update times; reports 2–3 example tables as evidence.
15. **Persist** — `python scripts/memory_io.py` `append_job` writes the final job to `<project>/jobs/jobs.yml`.
16. **Commit path** — `python scripts/commit_path.py --persona <persona> --project-dir PATH`. Decides branch vs. direct commit.

---

## Safety invariants (never skip)

- **warn-error flag**: every dbt step carries `--warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'` so a stale selector fails loudly.
- **Dry-run before write**: both stage 1 (`--empty`) and stage 2 (`--no-update`) must pass before any job is written.
- **Env guard — never PROD**: `env_guard.py` blocks all writes to production environments. Users must promote to prod themselves.
- **Verify after run**: `verify_run.py` confirms each target table has a fresh update time.
- **3-iteration cap**: any resolve/retry loop stops after 3 attempts. Engineer persona → ask the user; business persona → escalate via `<project>/.claude/escalation_policy.yml`.
- **Edit scope**: scripts write only to `<project>/jobs/` (enforced by `memory_io.append_job`). The only permitted exception outside that directory is `.github/workflows/cd_prod.yml` for optional CI wiring.
- **No MCP**: all logic runs through plain Python scripts. No MCP servers are invoked.
- **Secrets never printed**: dbt Cloud tokens are read from environment variables only and never appear in stdout, logs, or YAML.

---

## Scripts inventory

| Script | Purpose |
|---|---|
| `scripts/spec_parser.py` | Persona detection + initial spec extraction |
| `scripts/jobspec.py` | JobSpec model (`to_builder_dict()` is the builder contract) |
| `scripts/memory_io.py` | Defaults, ID lookup, phrase→model, append job to `<project>/jobs/jobs.yml`, setup cache |
| `scripts/natural_language_describer.py` | Persona-appropriate job description |
| `scripts/error_interpreter.py` | Classify dbt/dry-run errors → explanation + follow-up action |
| `scripts/resolve_selection.py` | Dashboard phrase / upstream model → dbt selector; escalation when mapping unknown |
| `scripts/yaml_builder.py` | JobSpec → jobs YAML |
| `scripts/validate.py` | Validate jobs YAML against schema |
| `scripts/dry_run.py` | Stage 1 (`dbt --empty`) + stage 2 (`sync --no-update`) dry run |
| `scripts/verify_run.py` | Confirm tables have fresh update times after a full run |
| `scripts/commit_path.py` | Branch vs. direct-commit decision |
| `scripts/env_guard.py` | Block PROD writes; allow DEV/STG/QA only |
| `scripts/connection_check.py` | Create + delete throwaway test job to verify dbt Cloud permissions |
| `scripts/dbt_cloud_env.py` | List dbt Cloud environments from `~/.dbt/dbt_cloud.yml` |
| `scripts/install_check.py` | Check `dbt-jobs-as-code` availability; persona-appropriate guidance |
| `scripts/env_check.sh` | Prereq check (Linux/Mac): dbt, python present? |
| `scripts/env_check.ps1` | Prereq check (Windows): dbt, python present? |

---

## Memory layout

```
memory/
  global/
    accounts.yml          # account IDs, hosts
    environments.yml      # environment IDs and types
    naming_conventions.yml
    setup_cache.yml       # cached setup outputs (no token)
  groups/<group>/
    jobs.yml              # authored jobs for this group
    vars_*.yml            # dbt variable overrides
    memory.yml            # schedule/notification/target defaults
    models.yml            # dashboard → table phrase mappings
```

Job YAML for active projects lives at `<project>/jobs/jobs.yml`, not in `memory/`.
Escalation policy template: [reference/escalation_policy.example.yml](reference/escalation_policy.example.yml) — copy to `<project>/.claude/escalation_policy.yml`.
