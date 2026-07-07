# dbt clean

## What it does

Deletes local file-system paths listed in the `clean-targets` config in `dbt_project.yml` (by default the `target/` compiled-artifacts directory, and optionally `dbt_packages`/`packages-install-path` if added to clean-targets). It is a housekeeping utility for clearing stale local build artifacts, not a data or dbt-graph operation — it does not read the warehouse, does not compile/parse the project, and does not touch dbt Cloud's run history or artifacts storage.

## Effect on warehouse data

**Classification:** `writes-artifacts-only`

dbt clean only deletes local files (target/, and whatever else is listed in clean-targets, e.g. dbt_packages) inside the project's working directory. It never issues SQL, never touches warehouse tables/views/rows, and has no read step at all — it's a filesystem `rm -rf` scoped by config, nothing more.

## Use in a dbt Cloud job

- **Can run as a step:** no
- **Should run:** no
- **Available as a job parameter/toggle instead:** no — there is no dbt Cloud job toggle for this; it isn't surfaced as a parameter like "Generate docs" or "Run source freshness" are
- **Notes:** dbt Cloud jobs run each invocation in a fresh, ephemeral, isolated file system/container that dbt Cloud provisions and tears down per run, so there is no persistent target/ or dbt_packages/ directory to accumulate cruft between runs — the problem dbt clean solves locally doesn't exist in dbt Cloud's execution model. The official docs also explicitly warn the command 'does not work when interfacing with the RPC server that powers the Studio IDE' due to permissions/deletion risk on the remote file system, and note dbt deps already cleans before reinstalling packages automatically. Net: dbt clean is a local-CLI/dev-workflow command; it should not be added as a command step in a dbt-jobs-as-code job spec. If a job-author agent sees a request for 'dbt clean' as a job step, it should decline/omit it and explain why rather than adding it.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| n/a — command should not be added to a job | `have` | No account/env/project info is needed because this command is not applicable as a job step. If the user insists, the agent should explain the ephemeral-filesystem reasoning and the RPC/permissions warning from docs.getdbt.com rather than collecting parameters for it. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--clean-project-files-only (default)`
- **Purpose:** Restricts deletion to paths inside the project directory as listed in clean-targets; this is the default behavior and exists to prevent a misconfigured clean-targets entry from deleting files elsewhere on the filesystem.
- **Data effect:** writes-artifacts-only (local files only, scoped to project dir); no warehouse effect.
- **Info needed:** None needed from the user; it's the default.
- **When to include:** Irrelevant for job authoring since the base command itself isn't added to jobs. If ever used locally, leave as default (safer).
- **Good vs bad:** Good: leaving this as default when running dbt clean locally avoids accidentally deleting files outside the project.

### `--no-clean-project-files-only`
- **Purpose:** Allows dbt clean to delete every path in clean-targets even if those paths resolve outside the current project directory (pre-Fusion/v2 behavior of the classic clean-targets deletion).
- **Data effect:** writes-artifacts-only, but with a wider blast radius on the local/remote filesystem (can delete files outside the project directory) — still never touches warehouse data.
- **Info needed:** Would need the user to confirm clean-targets contents and confirm they understand the widened deletion scope — high-risk flag.
- **When to include:** Never appropriate in a dbt Cloud job (no persistent/shared filesystem risk to manage this way, and dbt Cloud's job runner isn't where you'd want broad filesystem deletion). Even locally, only use if you deliberately configured clean-targets with external paths and know what you're doing.
- **Good vs bad:** Bad: using this flag with an absolute/external path in clean-targets risks deleting files outside the project that you cannot easily restore.

## Best practices

- **Do not add dbt clean as a job step at all — rely on dbt Cloud's per-run ephemeral environment**
  - Why: Each dbt Cloud job run gets a fresh checkout/container, so there is no accumulated target/ or dbt_packages/ cruft to clean between scheduled runs; adding the step is a no-op that just burns run time.
- **If cleaning stale artifacts is ever truly needed, do it locally or in your own CI runner (not dbt Cloud), and keep clean-targets scoped to the project directory (the default)**
  - Why: The docs explicitly warn against using clean in contexts with a shared/remote file system due to permission and accidental-deletion risk outside the project; local dev is the safe, intended use case.

## Anti-patterns

- **Adding 'dbt clean' as a command step before 'dbt build'/'dbt run' in a dbt Cloud job 'just to be safe'**
  - Why: It's dead weight: dbt Cloud jobs don't reuse a persistent target directory across runs, so there's nothing meaningful to clean, and the step adds latency and a false sense of causing 'fresher' runs for no actual effect.
- **Using --no-clean-project-files-only or a clean-targets config with absolute/external paths in any automated/shared execution context**
  - Why: This can delete files outside the project directory without the ability to easily restore them, which is precisely the 'complex permissions issues... deleting crucial aspects of the remote file system' scenario the dbt docs warn about.

## Overlaps with

- dbt deps (auto-cleans dbt_packages/ before reinstalling, making a separate dbt clean step redundant for package cleanliness)
- dbt build / dbt run / dbt compile (these regenerate target/ contents each run in dbt Cloud's fresh environment, so no manual clean is needed beforehand)
- dbt Cloud job artifact/run-history management (unrelated system-level mechanism, not something dbt clean interacts with — dbt Cloud retains run artifacts server-side regardless of local target/ state)
