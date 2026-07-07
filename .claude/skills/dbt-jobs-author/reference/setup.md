# One-time setup

Run these steps once per machine/project before authoring any jobs. All outputs are cached in `memory/global/setup_cache.yml` (token never stored). See [flow.md](flow.md) Phase A for the programmatic sequence.

---

## §3.1 Install dbt-jobs-as-code

```bash
pip install dbt-jobs-as-code
# or, from the lockfile:
pip install -r requirements.txt
```

---

## §3.2 Authenticate against dbt Cloud

Import existing dbt Cloud jobs as the starting point (better than writing config from scratch):

```bash
dbt-jobs-as-code import --account-id <your_account_id> --output-file jobs/jobs.yml
```

You need a dbt Cloud API token. Either:
- Reuse a `token-value` from `~/.dbt/dbt_cloud.yml` (from the dbt Cloud CLI setup) for the right account, **or**
- Generate a dedicated service token (Account Settings → Service Tokens; needs **Job Admin** permission).

Set it as an environment variable — do not hardcode:

```bash
export DBT_API_TOKEN=<token>
```

---

## §3.3 Sync changes back to dbt Cloud

After editing `<project>/jobs/jobs.yml`:

```bash
dbt-jobs-as-code sync --config jobs/jobs.yml
```

Always dry-run first:

```bash
dbt-jobs-as-code sync --config jobs/jobs.yml --no-update
```

The `--no-update` flag is what `dry_run.py --stage 2` uses internally.

---

## §3.4 Optional: wire into CI

Add a step to `.github/workflows/cd_prod.yml` that runs `dbt-jobs-as-code sync` on merge to `main`, so `jobs/jobs.yml` becomes the source of truth instead of manual dbt Cloud UI edits. This file is the only permitted edit location outside `<project>/jobs/` within the project.

Example step:

```yaml
- name: Sync dbt jobs
  run: dbt-jobs-as-code sync --config jobs/jobs.yml
  env:
    DBT_API_TOKEN: ${{ secrets.DBT_API_TOKEN }}
```

---

## §3.5 Environment resolution

The Python script `scripts/dbt_cloud_env.py` is the primary tool. It reads `~/.dbt/dbt_cloud.yml`, resolves the active project's account/host/token, and lists environments via the dbt Cloud API:

```bash
python scripts/dbt_cloud_env.py
# or with an explicit config path:
python scripts/dbt_cloud_env.py --config ~/.dbt/dbt_cloud.yml
```

Output:
```json
{
  "account_id": 1,
  "project_id": "my-project",
  "host": "cloud.getdbt.com",
  "environments": [{"id": 10, "name": "DEV", "type": "development"}, ...]
}
```

Token is never printed. If the config or token is missing, returns `{"status": "unavailable", "reason": "..."}` and the orchestrator skips gracefully.

### Shell reference (use only if Python is unavailable)

**Linux / macOS:**

```bash
#!/usr/bin/env bash
set -euo pipefail

CONFIG="${HOME}/.dbt/dbt_cloud.yml"
[ -f "$CONFIG" ] || { echo "Not found: $CONFIG" >&2; exit 1; }

ACTIVE_PROJECT=$(grep -m1 'active-project:' "$CONFIG" | sed -E 's/.*"([^"]+)".*/\1/')

eval "$(awk -v RS='  - project-name:' -v pid="\"${ACTIVE_PROJECT}\"" '
  NR > 1 && index($0, "project-id: " pid) {
    match($0, /account-id: "[^"]*"/);   acct = substr($0, RSTART, RLENGTH); gsub(/account-id: "|"/, "", acct)
    match($0, /account-host: "[^"]*"/); host = substr($0, RSTART, RLENGTH); gsub(/account-host: "|"/, "", host)
    match($0, /token-value: "[^"]*"/);  tok  = substr($0, RSTART, RLENGTH); gsub(/token-value: "|"/, "", tok)
    print "HOST=" host
    print "ACCOUNT_ID=" acct
    print "TOKEN=" tok
    exit
  }
' "$CONFIG")"
PROJECT_ID="$ACTIVE_PROJECT"

[ -n "${HOST:-}" ] || { echo "Could not resolve active project $ACTIVE_PROJECT in $CONFIG" >&2; exit 1; }

curl --silent --request GET \
  --url "https://${HOST}/api/v3/accounts/${ACCOUNT_ID}/projects/${PROJECT_ID}/environments/" \
  --header "Authorization: Token ${TOKEN}" \
  --header "Content-Type: application/json"
```

**Windows (PowerShell):**

```powershell
$Config = Join-Path $HOME ".dbt\dbt_cloud.yml"
if (-not (Test-Path $Config)) { Write-Error "Not found: $Config"; exit 1 }

$content = Get-Content $Config -Raw
$activeMatch = [regex]::Match($content, 'active-project:\s*"([^"]+)"')
if (-not $activeMatch.Success) { Write-Error "Could not find active-project in $Config"; exit 1 }
$activeProject = $activeMatch.Groups[1].Value

$blocks = [regex]::Split($content, '(?=\s+- project-name:)')
$block = $blocks | Where-Object { $_ -match [regex]::Escape("project-id: `"$activeProject`"") } | Select-Object -First 1
if (-not $block) { Write-Error "Could not resolve active project $activeProject in $Config"; exit 1 }

$accountId   = [regex]::Match($block, 'account-id:\s*"([^"]+)"').Groups[1].Value
$accountHost = [regex]::Match($block, 'account-host:\s*"([^"]+)"').Groups[1].Value
$token       = [regex]::Match($block, 'token-value:\s*"([^"]+)"').Groups[1].Value

$uri = "https://$accountHost/api/v3/accounts/$accountId/projects/$activeProject/environments/"
Invoke-RestMethod -Uri $uri -Method Get -Headers @{
    "Authorization" = "Token $token"
    "Content-Type"  = "application/json"
}
```
