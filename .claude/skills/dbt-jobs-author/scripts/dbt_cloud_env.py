"""Resolve the active dbt Cloud project and list its environments.

Reads ~/.dbt/dbt_cloud.yml, extracts account-id / account-host / token for the
active project, then calls the dbt Cloud v3 environments API.

Usage:
    python dbt_cloud_env.py [--config PATH]

Output (stdout, JSON):
    {"account_id":..., "project_id":..., "host":..., "environments":[{id,name,type,...}]}
    or {"status":"unavailable","reason":"..."} when config/token are missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_CONFIG = Path.home() / ".dbt" / "dbt_cloud.yml"


def _parse_yaml(text: str) -> dict[str, Any]:
    if yaml is not None:
        return yaml.safe_load(text) or {}
    # ponytail: regex fallback mirroring the ps1 in prompt.md §3.5 — handles
    # simple quoted YAML values; upgrade to PyYAML if nested structures needed.
    return {}


def _regex_field(text: str, key: str) -> str:
    m = re.search(rf'{re.escape(key)}:\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def load_config(config_path: Path) -> dict[str, Any]:
    """Parse dbt_cloud.yml; return dict or raise FileNotFoundError."""
    text = config_path.read_text(encoding="utf-8")
    data = _parse_yaml(text)
    if data:
        return data
    # regex fallback
    result: dict[str, Any] = {}
    active = _regex_field(text, "active-project")
    if active:
        result["active-project"] = active
    # extract project blocks (very simplified)
    result["_raw"] = text
    return result


def resolve_active_project(data: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return (project_id, account_id, host, token) for the active project."""
    raw = data.get("_raw", "")  # regex path
    if yaml is not None and "_raw" not in data:
        # active-project may live at top level or nested under 'context'
        active = data.get("active-project") or (data.get("context") or {}).get("active-project", "")
        active = str(active)
        projects = data.get("projects", []) or []
        for proj in projects:
            if str(proj.get("project-id", "")) == str(active):
                return (
                    str(active),
                    str(proj.get("account-id", "")),
                    str(proj.get("account-host", "")),
                    str(proj.get("token-value", "")),
                )
        raise ValueError(f"Active project '{active}' not found in config")
    # regex fallback — mirrors prompt.md §3.5 ps1 logic
    active = _regex_field(raw, "active-project")
    if not active:
        raise ValueError("Could not find active-project in config")
    # split on project blocks and find the matching one
    blocks = re.split(r'(?=\s*-\s*project-name:)', raw)
    for block in blocks:
        if f'project-id: "{active}"' in block:
            account_id = _regex_field(block, "account-id")
            host = _regex_field(block, "account-host")
            token = _regex_field(block, "token-value")
            if account_id and host and token:
                return active, account_id, host, token
    raise ValueError(f"Could not resolve active project '{active}' in config")


def fetch_environments(host: str, account_id: str, project_id: str, token: str) -> list[dict]:
    url = f"https://{host}/api/v3/accounts/{account_id}/projects/{project_id}/environments/"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("data", [])


def run(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {"status": "unavailable", "reason": f"Config not found: {config_path}"}
    try:
        data = load_config(config_path)
        project_id, account_id, host, token = resolve_active_project(data)
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)}
    if not token:
        return {"status": "unavailable", "reason": "token-value missing from config"}
    try:
        envs = fetch_environments(host, account_id, project_id, token)
    except urllib.error.HTTPError as exc:
        return {"status": "unavailable", "reason": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)}
    # ponytail: token is NEVER included in output
    return {
        "account_id": account_id,
        "project_id": project_id,
        "host": host,
        "environments": [
            {k: v for k, v in env.items() if k in ("id", "name", "type", "state", "dbt_version")}
            for env in envs
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="List dbt Cloud environments for the active project.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to dbt_cloud.yml")
    args = ap.parse_args(argv)
    print(json.dumps(run(args.config), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
