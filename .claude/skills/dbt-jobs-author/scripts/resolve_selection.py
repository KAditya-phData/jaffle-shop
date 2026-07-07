"""Resolve a business phrase or dashboard name to a dbt selector + upstream models.

Folds dbt-semantic-search + dbt-lineage into one dbt-driven script. No MCP.

Subcommands:
  dashboard <group> "<phrase>" [--project-dir PATH]
  upstream  <model> [<model> ...] [--project-dir PATH]

Outputs JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# import resolve_phrase from memory_io (same dir)
sys.path.insert(0, str(Path(__file__).parent))
import memory_io


# ---------------------------------------------------------------------------
# Upstream resolution
# ---------------------------------------------------------------------------

def _upstream_from_manifest(models: list[str], project_dir: Path) -> list[str]:
    """Parse target/manifest.json parent_map to find all ancestors."""
    manifest_path = project_dir / "target" / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    # manifest v9+ uses parent_map; older versions use nodes[x].depends_on.nodes
    parent_map: dict[str, list[str]] = manifest.get("parent_map", {})

    def _all_ancestors(node_id: str, seen: set[str]) -> None:
        for parent in parent_map.get(node_id, []):
            if parent not in seen and parent.startswith("model."):
                seen.add(parent)
                _all_ancestors(parent, seen)

    # Find node IDs for requested models (model name -> node id)
    nodes: dict[str, Any] = manifest.get("nodes", {})
    name_to_id: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.get("resource_type") == "model":
            name_to_id[node.get("name", "")] = node_id

    ancestors: set[str] = set()
    for m in models:
        node_id = name_to_id.get(m)
        if node_id:
            _all_ancestors(node_id, ancestors)

    # return just model names
    result: list[str] = []
    for nid in ancestors:
        node = nodes.get(nid, {})
        name = node.get("name")
        if name:
            result.append(name)
    return sorted(set(result))


def _upstream_from_dbt_ls(models: list[str], project_dir: Path) -> list[str]:
    """Fallback: run `dbt ls --select +<model> --resource-type model` for each model."""
    # ponytail: dbt-ls fallback when manifest absent; manifest-first is the fast path
    all_upstream: set[str] = set()
    for m in models:
        try:
            result = subprocess.run(
                ["dbt", "ls", "--select", f"+{m}", "--resource-type", "model", "--quiet"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                # dbt ls output is "project.model_name" or just "model_name"
                name = line.split(".")[-1] if "." in line else line
                if name and name != m:
                    all_upstream.add(name)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return sorted(all_upstream)


def resolve_upstream(models: list[str], project_dir: Path | None) -> dict[str, Any]:
    """Resolve upstream models; manifest-first, dbt ls fallback."""
    upstream: list[str] = []
    if project_dir:
        upstream = _upstream_from_manifest(models, project_dir)
        if not upstream:
            upstream = _upstream_from_dbt_ls(models, project_dir)

    selector = " ".join(f"+{m}" for m in models)
    return {"selector": selector, "upstream": upstream}


# ---------------------------------------------------------------------------
# Dashboard subcommand
# ---------------------------------------------------------------------------

def resolve_dashboard(group: str, phrase: str, project_dir: Path | None) -> dict[str, Any]:
    """Resolve phrase -> primary models -> upstream selector."""
    primary_models = memory_io.resolve_phrase(group, phrase)

    if not primary_models:
        return {
            "status": "escalate",
            "reason": "no dashboard->table mapping",
            "group": group,
            "phrase": phrase,
            "message": (
                "No dashboard-to-table mapping found in models.yml for this phrase. "
                "Business users: escalate to data analysts to add the dashboard<->table "
                "mapping to memory/groups/<group>/models.yml. "
                "Engineers: pass an explicit selector with the `upstream` subcommand."
            ),
        }

    upstream_result = resolve_upstream(primary_models, project_dir)
    all_upstream = list(dict.fromkeys(primary_models + upstream_result["upstream"]))

    return {
        "status": "resolved",
        "primary_models": primary_models,
        "selector": upstream_result["selector"],
        "upstream": all_upstream,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve dbt model selection from a phrase or dashboard.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dashboard", help="Resolve phrase/dashboard to models + selector")
    d.add_argument("group")
    d.add_argument("phrase")
    d.add_argument("--project-dir", type=Path, default=None)

    u = sub.add_parser("upstream", help="Resolve upstream models for given model names")
    u.add_argument("models", nargs="+")
    u.add_argument("--project-dir", type=Path, default=None)

    args = ap.parse_args(argv)

    if args.cmd == "dashboard":
        out = resolve_dashboard(args.group, args.phrase, args.project_dir)
    else:
        out = resolve_upstream(args.models, args.project_dir)

    print(json.dumps(out, indent=2))
    return 0


def _selftest() -> None:
    # deterministic path: sales group with no models.yml -> escalate
    result = resolve_dashboard("sales", "executive sales", None)
    assert result["status"] in ("resolved", "escalate"), f"unexpected status: {result}"

    # upstream with no project dir -> empty list
    result2 = resolve_upstream(["orders"], None)
    assert "selector" in result2
    assert result2["selector"] == "+orders"
    assert result2["upstream"] == []
    print("selftest passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(main())
