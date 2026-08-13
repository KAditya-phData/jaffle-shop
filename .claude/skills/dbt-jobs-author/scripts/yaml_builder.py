"""Project a JobSpec dict into dbt-jobs-as-code YAML.

Emits two variants of every job (the core requirement):
  - FINAL:   permanent --warn-error-options flag, no --empty
  - DRY_RUN: same warn-error flag plus --empty on every dbt step

The JobSpec dict is the serialized contract passed across the skill/subagent
boundary. Its shape is documented in jobspec.py of the dbt-jobs-author skill.

Usage:
    python yaml_builder.py spec.json --variant final     # prints YAML
    python yaml_builder.py spec.json --variant dry_run
    python yaml_builder.py spec.json --variant both       # prints both, labeled
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

WARN_ERROR_FLAG = """--warn-error-options '{"error":["NoNodesForSelectionCriteria"]}'"""
SCHEMA_HEADER = (
    "# yaml-language-server: $schema=https://raw.githubusercontent.com/dbt-labs/"
    "dbt-jobs-as-code/main/src/dbt_jobs_as_code/schemas/load_job_schema.json"
)


def build_execute_steps(spec: dict[str, Any], dry_run: bool) -> list[str]:
    """Build the execute_steps command strings for a spec.

    A spec may carry an explicit `command.steps` list (each a base command +
    selector) or a single command/selection pair. We always append the
    permanent warn-error flag, and `--empty` only for the dry-run variant.
    """
    command = spec.get("command", {})
    selection = spec.get("selection", {})
    selector = selection.get("dbt_selector", "").strip()
    extra_flags = command.get("extra_flags", [])

    raw_steps = command.get("steps")
    if not raw_steps:
        base = command.get("base", "dbt build").strip()
        step = base
        if selector:
            step += f" --select {selector}"
        raw_steps = [step]

    steps: list[str] = []
    for raw in raw_steps:
        parts = [raw.strip()]
        parts.extend(f for f in extra_flags if f)
        parts.append(WARN_ERROR_FLAG)
        if dry_run:
            parts.append("--empty")
        steps.append(" ".join(parts))
    return steps


def _job_name(spec: dict[str, Any]) -> str:
    name = spec["name"]
    identifier = spec.get("identifier")
    if identifier and f"[[{identifier}]]" not in name:
        return f"{name} [[{identifier}]]"
    return name


def job_spec_to_config(spec: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Return the full {jobs: {...}} config dict for one spec."""
    env = spec.get("environment", {})
    job_type = spec.get("job_type", "scheduled")

    job: dict[str, Any] = {
        "account_id": int(spec["account_id"]),
        "project_id": int(env["project_id"]),
        "environment_id": int(env["environment_id"]),
        "name": _job_name(spec),
        "job_type": job_type,
        "settings": {
            "target_name": env.get("target", "default"),
            "threads": int(spec.get("threads", 4)),
        },
        "execution": {"timeout_seconds": int(spec.get("timeout_seconds", 0))},
        "run_generate_sources": bool(spec.get("run_generate_sources", False)),
        "execute_steps": build_execute_steps(spec, dry_run),
        "generate_docs": bool(spec.get("generate_docs", False)),
        "triggers": spec.get(
            "triggers",
            {
                "github_webhook": False,
                "git_provider_webhook": False,
                "schedule": job_type == "scheduled",
                "on_merge": job_type == "merge",
            },
        ),
    }

    if spec.get("description"):
        job["description"] = spec["description"]
    if spec.get("identifier"):
        job["identifier"] = spec["identifier"]
    if spec.get("dbt_version"):
        job["dbt_version"] = spec["dbt_version"]
    if spec.get("deferring_environment_id") is not None:
        job["deferring_environment_id"] = int(spec["deferring_environment_id"])
    if spec.get("triggers_on_draft_pr") is not None:
        job["triggers_on_draft_pr"] = bool(spec["triggers_on_draft_pr"])
    if spec.get("run_lint") is not None:
        job["run_lint"] = bool(spec["run_lint"])
    if spec.get("errors_on_lint_failure") is not None:
        job["errors_on_lint_failure"] = bool(spec["errors_on_lint_failure"])
    if spec.get("run_compare_changes") is not None:
        job["run_compare_changes"] = bool(spec["run_compare_changes"])
    if spec.get("compare_changes_flags"):
        job["compare_changes_flags"] = spec["compare_changes_flags"]

    # schedule is required unless job_type is ci/merge
    if job_type not in ("ci", "merge"):
        cron = spec.get("schedule", {}).get("cron")
        if not cron:
            raise ValueError(f"job_type '{job_type}' requires schedule.cron")
        job["schedule"] = {"cron": cron}

    cof = spec.get("cost_optimization_features")
    if cof:
        job["cost_optimization_features"] = cof

    cev = spec.get("custom_environment_variables")
    if cev:
        job["custom_environment_variables"] = cev

    return {"jobs": {spec.get("job_key", "job1"): job}}


def to_yaml(config: dict[str, Any]) -> str:
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required to emit YAML. pip install pyyaml")
    body = yaml.safe_dump(config, sort_keys=False, default_flow_style=False, width=10_000)
    return f"{SCHEMA_HEADER}\n{body}"


def job_spec_to_yaml(spec: dict[str, Any]) -> str:
    return to_yaml(job_spec_to_config(spec, dry_run=False))


def job_spec_to_dry_run_yaml(spec: dict[str, Any]) -> str:
    return to_yaml(job_spec_to_config(spec, dry_run=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build dbt-jobs-as-code YAML from a JobSpec JSON.")
    ap.add_argument("spec", help="Path to JobSpec JSON file (or '-' for stdin).")
    ap.add_argument("--variant", choices=["final", "dry_run", "both"], default="both")
    args = ap.parse_args(argv)

    text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = json.loads(text)

    if args.variant in ("final", "both"):
        if args.variant == "both":
            print("# ===== FINAL VARIANT =====")
        print(job_spec_to_yaml(spec))
    if args.variant in ("dry_run", "both"):
        if args.variant == "both":
            print("# ===== DRY-RUN VARIANT =====")
        print(job_spec_to_dry_run_yaml(spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
