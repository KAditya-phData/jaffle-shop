"""Read/write the file-backed memory for the dbt-jobs-author skill.

Layout (relative to the skill's memory/ dir):
  global/{accounts.yml, environments.yml, naming_conventions.yml, setup_cache.yml}
  groups/<group>/{jobs.yml, vars_*.yml, memory.yml, models.yml}

Provides:
  - account/environment ID lookup (so the user isn't asked for raw IDs)
  - per-group defaults (schedule, notifications, target)
  - deterministic business-phrase -> model resolution (checked BEFORE semantic search)
  - appending a finished job into <project_dir>/jobs/jobs.yml
  - setup cache (resolved account/project/host, env list, tool versions — no tokens)

Usage (CLI helpers, also importable):
    python memory_io.py defaults sales
    python memory_io.py resolve-phrase sales "executive sales"
    python memory_io.py ids acme prod
    python memory_io.py setup-cache
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

MEMORY_DIR = Path(__file__).resolve().parents[1] / "memory"
SCHEMA_HEADER = (
    "# yaml-language-server: $schema=https://raw.githubusercontent.com/dbt-labs/"
    "dbt-jobs-as-code/main/src/dbt_jobs_as_code/schemas/load_job_schema.json"
)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _group_dir(group: str) -> Path:
    return MEMORY_DIR / "groups" / group


# --- global lookups --------------------------------------------------------


def account_id(account: str) -> int | None:
    data = _read_yaml(MEMORY_DIR / "global" / "accounts.yml")
    return (data.get("accounts", {}).get(account) or {}).get("account_id")


def environment_ids(account: str, env: str) -> dict[str, Any]:
    data = _read_yaml(MEMORY_DIR / "global" / "environments.yml")
    return (data.get("environments", {}).get(account, {}) or {}).get(env, {})


def naming_conventions() -> dict[str, Any]:
    return _read_yaml(MEMORY_DIR / "global" / "naming_conventions.yml").get("naming", {})


# --- group memory ----------------------------------------------------------


def group_defaults(group: str) -> dict[str, Any]:
    return _read_yaml(_group_dir(group) / "memory.yml")


def resolve_phrase(group: str, phrase: str) -> list[str]:
    """Deterministic phrase -> model list from models.yml (case-insensitive,
    substring match). Returns [] when no curated mapping exists so the caller
    falls back to semantic search."""
    models = _read_yaml(_group_dir(group) / "models.yml")
    p = phrase.strip().lower()
    # exact dashboard match
    for name, info in (models.get("dashboards", {}) or {}).items():
        if name.replace("_", " ") in p or p in name.replace("_", " "):
            return list(info.get("primary_models", []))
    # phrase table
    hits: list[str] = []
    for entry in models.get("phrases", []) or []:
        ph = str(entry.get("phrase", "")).lower()
        if ph and (ph in p or p in ph):
            hits.extend(entry.get("models", []))
    return hits


def list_groups() -> list[str]:
    base = MEMORY_DIR / "groups"
    return sorted([d.name for d in base.iterdir() if d.is_dir()]) if base.exists() else []


# --- setup cache -----------------------------------------------------------

_SETUP_CACHE_PATH = MEMORY_DIR / "global" / "setup_cache.yml"


def get_setup_cache() -> dict[str, Any]:
    """Read the setup cache (never contains tokens)."""
    return _read_yaml(_SETUP_CACHE_PATH)


def save_setup_cache(data: dict[str, Any]) -> None:
    """Persist setup cache to memory/global/setup_cache.yml. Token values are stripped."""
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML required to write setup_cache.yml")
    # safety: never store anything that looks like a token
    safe = {k: v for k, v in data.items() if "token" not in k.lower()}
    _SETUP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETUP_CACHE_PATH.write_text(
        yaml.safe_dump(safe, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# --- writing jobs ----------------------------------------------------------


def append_job(group: str, job_key: str, job_config: dict[str, Any], project_dir: str | Path) -> Path:
    """Merge a single job (the inner dict under jobs.<key>) into
    <project_dir>/jobs/jobs.yml, preserving the schema header.

    Enforces that the write path is under <project_dir>/jobs/ (edit-scope guard).
    Returns the file path written.
    """
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML required to write jobs.yml")

    jobs_dir = Path(project_dir).resolve() / "jobs"
    path = jobs_dir / "jobs.yml"

    # edit-scope guard: must be under <project_dir>/jobs/
    try:
        path.resolve().relative_to(jobs_dir.resolve())
    except ValueError:
        raise ValueError(f"Write path {path} is not under {jobs_dir} — refusing write.")

    jobs_dir.mkdir(parents=True, exist_ok=True)
    current = _read_yaml(path)
    current.setdefault("jobs", {})
    current["jobs"][job_key] = job_config
    body = yaml.safe_dump(current, sort_keys=False, default_flow_style=False, width=10_000)
    path.write_text(f"{SCHEMA_HEADER}\n{body}", encoding="utf-8")
    return path


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dbt-jobs-author memory helpers.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("defaults"); d.add_argument("group")
    r = sub.add_parser("resolve-phrase"); r.add_argument("group"); r.add_argument("phrase")
    i = sub.add_parser("ids"); i.add_argument("account"); i.add_argument("env")
    sub.add_parser("groups")
    sub.add_parser("setup-cache")
    args = ap.parse_args(argv)

    if args.cmd == "defaults":
        out: Any = group_defaults(args.group)
    elif args.cmd == "resolve-phrase":
        out = {"group": args.group, "phrase": args.phrase, "models": resolve_phrase(args.group, args.phrase)}
    elif args.cmd == "ids":
        out = {"account_id": account_id(args.account), **environment_ids(args.account, args.env)}
    elif args.cmd == "setup-cache":
        out = get_setup_cache()
    else:
        out = {"groups": list_groups()}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
