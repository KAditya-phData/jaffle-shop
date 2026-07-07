# dbt docs serve

**Aliases:** docs serve

## What it does

Starts a local, non-persistent HTTP webserver that serves the static dbt documentation site (index.html plus the manifest.json/catalog.json artifacts already produced by 'dbt docs generate') from the target/ directory, and by default opens it in the user's local web browser. It requires 'dbt docs generate' to have been run first — 'serve' does not generate anything itself, it only displays pre-built artifacts. It runs indefinitely as a foreground process until manually stopped (Ctrl+C), making it fundamentally an interactive, local-machine-only tool.

## Effect on warehouse data

**Classification:** `read-only`

dbt docs serve performs NO warehouse interaction at all — it does not connect to the data warehouse/database. It simply starts a local HTTP webserver (default port 8000; some older docs say 8080) that serves the already-generated static files (index.html, manifest.json, catalog.json) from the target/ directory in a browser. It writes nothing new, not even artifacts — those are produced beforehand by 'dbt docs generate', which itself only writes local JSON files (manifest.json, catalog.json) and does query the warehouse read-only (for catalog metadata) but never writes/modifies warehouse tables, views, or rows.

## Use in a dbt Cloud job

- **Can run as a step:** no
- **Should run:** no
- **Available as a job parameter/toggle instead:** Not directly — the analogous/intended job feature is the 'Generate docs on run' checkbox under a dbt Cloud job's Execution Settings, but that toggle maps to 'dbt docs generate', not 'dbt docs serve'. There is no dbt Cloud job parameter for 'serve' because serving requires a persistent reachable process, which is incompatible with dbt Cloud's ephemeral run model.
- **Notes:** Technically the CLI would accept the command in a run step, but it starts a webserver that never terminates on its own, opens a local browser (meaningless in a headless CI runner), and binds to localhost only — inaccessible to anyone outside the ephemeral job container. It would just hang until the job step/run timeout killed it, wasting run minutes and likely failing the job. This command belongs exclusively to local development workflows, never to jobs-as-code definitions.

## Info needed to add it (decision inputs)

| Field | Source | Notes |
|---|---|---|
| N/A — command should not be added to a job | `have` | The agent already has enough information to refuse/redirect: 'dbt docs serve' has no valid use inside a dbt Cloud job. If a user asks for 'docs' in a scheduled job, the agent should map that intent to the 'Generate docs on run' job toggle (or a 'dbt docs generate' command step) instead, and should ask the user only if it's ambiguous whether they want docs generated at all as part of the job. |

> `have` = agent already knows it · `memory` = pull from stored account/env/group defaults · `ask_user` = must ask.

## Options / flags

### `--port <PORT>`
- **Purpose:** Sets the TCP port the local webserver listens on (default 8000, historically documented as 8080 in some places)
- **Data effect:** None — purely a local network binding setting, no warehouse interaction
- **Info needed:** Port number; agent would use a sensible default if this command were ever used interactively, but never needs to ask since this command isn't used in jobs
- **When to include:** N/A for jobs-as-code; only relevant for local dev troubleshooting (e.g., port already in use)
- **Good vs bad:** Good: use --port 8001 locally when 8000 is occupied by another process. Bad: trying to configure this for a dbt Cloud job step — there's no reachable network endpoint for job runners to expose a port to.

### `--host <HOST>`
- **Purpose:** Sets the network interface the server binds to (default 127.0.0.1/localhost as of a dbt-core security fix; previously defaulted to 0.0.0.0)
- **Data effect:** None — network binding only, no warehouse effect
- **Info needed:** Host/IP; not applicable in dbt Cloud jobs context
- **When to include:** Only relevant for local dev when you need the docs server reachable from another machine on your network (e.g., a shared dev box) — use with caution since it was made more restrictive for security reasons
- **Good vs bad:** Good: leave default (127.0.0.1) for personal local use. Bad: setting --host 0.0.0.0 casually, since it re-exposes the docs server (which can include schema/column metadata) to the whole network.

## Best practices

- **Never put 'dbt docs serve' in a scheduled/CI job; use it only for local development to preview docs before pushing**
  - Why: It's designed as a throwaway local preview server (opens a browser, binds to localhost), not a service — dbt Cloud already hosts generated docs for teams via the Explore/docs UI, making a self-hosted local server redundant and non-functional in CI.
- **For job-based documentation, use 'dbt docs generate' (or the 'Generate docs on run' job toggle) in the production/main build job rather than trying to serve docs from a job**
  - Why: Generate is the artifact-producing half of the docs workflow and is safe/appropriate for jobs (it writes local JSON files then exits); serving is a separate, interactive concern handled by dbt Cloud's hosting layer, not by job steps.

## Anti-patterns

- **Adding 'dbt docs serve' as a run-step/command in a dbt Cloud job**
  - Why: It starts a long-running local webserver bound to 127.0.0.1 and never exits — a job step running it would hang until timeout and produce no usable artifact for other users; dbt Cloud jobs are non-interactive, ephemeral, and not reachable on arbitrary ports, so nobody could ever open the URL it serves.
- **Relying on 'Generate docs on run' / dbt docs generate as your documentation hosting solution instead of dbt Cloud's built-in Explore/docs site**
  - Why: Generate only produces catalog.json/manifest.json artifacts; without dbt Cloud's hosted docs site (or your own static hosting), those artifacts aren't viewable by anyone, and generation is skipped if any step in the run fails, silently leaving docs stale.

## Overlaps with

- dbt docs generate (the artifact-producing predecessor step; serve just displays what generate produced)
- dbt Cloud job Execution Settings toggle 'Generate docs on run' (the correct, job-native way to produce docs artifacts on a schedule — maps to 'dbt docs generate', not 'dbt docs serve')
- dbt Cloud's hosted Documentation/Explore site (the production replacement for locally serving docs — this is what teams should actually use instead of 'dbt docs serve')
- dbt compile --write-index (used with the newer dbt Docs v2 / Fusion engine workflow, paired with 'dbt docs serve' for local preview only)
