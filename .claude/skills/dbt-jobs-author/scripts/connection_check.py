"""Verify dbt Cloud connection by creating and immediately deleting a throwaway test job.

Usage:
    python connection_check.py --account-id N --project-id N --environment-id N
                               [--token-env DBT_API_TOKEN] [--max-age-hours 24] [--force]

Output (stdout, JSON):
    {"ok": true, "created_and_deleted": true, "job_id": N}
    or {"ok": true, "status": "cached", "verified_at": "..."} when a prior check is still fresh
    or {"status": "skipped", "reason": "..."} when token/tool is absent.

Result of a successful live check is cached in memory/global/setup_cache.yml
(keyed by account/project/environment) so repeat jobs against the same
environment within --max-age-hours skip the live API round-trip. Pass
--force to bypass the cache.

# ponytail: real path is dbt Cloud Admin API v2 jobs create+delete; falls back to
# {"status":"skipped"} when DBT_API_TOKEN is absent so the orchestrator can proceed
# gracefully in offline/CI environments. Upgrade path: swap the urllib calls below for
# the dbt-jobs-as-code SDK if it gains a programmatic create/delete API.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import memory_io


_JOB_PAYLOAD = {
    "name": "__connection_check_DELETE_ME__",
    "execute_steps": ["dbt debug"],
    "dbt_version": None,
    "triggers": {"github_webhook": False, "git_provider_webhook": False, "schedule": False, "on_merge": False},
    "settings": {"threads": 1, "target_name": "default"},
    "run_generate_sources": False,
    "generate_docs": False,
    "schedule": {"cron": "0 * * * *"},
}


def _api_url(host: str, account_id: int) -> str:
    # host may or may not include protocol
    h = host.rstrip("/")
    if not h.startswith("http"):
        h = f"https://{h}"
    return f"{h}/api/v2/accounts/{account_id}/jobs/"


def _cache_key(account_id: int, project_id: int, environment_id: int) -> str:
    return f"{account_id}:{project_id}:{environment_id}"


def _get_cached(account_id: int, project_id: int, environment_id: int, max_age_hours: float) -> dict | None:
    checks = memory_io.get_setup_cache().get("connection_checks", {})
    entry = checks.get(_cache_key(account_id, project_id, environment_id))
    if not entry or not entry.get("ok"):
        return None
    verified_at = datetime.fromisoformat(entry["verified_at"])
    if datetime.now(timezone.utc) - verified_at > timedelta(hours=max_age_hours):
        return None
    return entry


def _set_cached(account_id: int, project_id: int, environment_id: int) -> None:
    cache = memory_io.get_setup_cache()
    checks = cache.setdefault("connection_checks", {})
    checks[_cache_key(account_id, project_id, environment_id)] = {
        "ok": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    memory_io.save_setup_cache(cache)


def _request(method: str, url: str, token: str, payload: dict | None = None) -> Any:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def run(account_id: int, project_id: int, environment_id: int, token: str, host: str = "cloud.getdbt.com") -> dict:
    base = _api_url(host, account_id)
    payload = {**_JOB_PAYLOAD, "account_id": account_id, "project_id": project_id, "environment_id": environment_id}
    try:
        created = _request("POST", base, token, payload)
        job_id = created.get("data", {}).get("id")
        if not job_id:
            return {"ok": False, "reason": "Created job but got no ID back", "raw": created}
        # delete immediately
        _request("DELETE", f"{base}{job_id}/", token)
        return {"ok": True, "created_and_deleted": True, "job_id": job_id}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "reason": f"HTTP {exc.code}: {exc.reason}", "detail": body[:400]}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify dbt Cloud connection via throwaway test job.")
    ap.add_argument("--account-id", type=int, required=True)
    ap.add_argument("--project-id", type=int, required=True)
    ap.add_argument("--environment-id", type=int, required=True)
    ap.add_argument("--token-env", default="DBT_API_TOKEN", help="Env var name holding the API token")
    ap.add_argument("--host", default="cloud.getdbt.com", help="dbt Cloud hostname")
    ap.add_argument("--max-age-hours", type=float, default=24, help="Skip live check if a prior success is younger than this")
    ap.add_argument("--force", action="store_true", help="Bypass the cache and run the live check")
    args = ap.parse_args(argv)

    if not args.force:
        cached = _get_cached(args.account_id, args.project_id, args.environment_id, args.max_age_hours)
        if cached:
            print(json.dumps({"ok": True, "status": "cached", "verified_at": cached["verified_at"]}, indent=2))
            return 0

    token = os.environ.get(args.token_env, "")
    if not token:
        # ponytail: skip gracefully when token absent; orchestrator checks status==skipped
        print(json.dumps({
            "status": "skipped",
            "reason": f"No token found in env var '{args.token_env}'. Set it to run connection check.",
        }, indent=2))
        return 0

    result = run(args.account_id, args.project_id, args.environment_id, token, args.host)
    if result.get("ok"):
        _set_cached(args.account_id, args.project_id, args.environment_id)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") or result.get("status") == "skipped" else 1


if __name__ == "__main__":
    sys.exit(main())
