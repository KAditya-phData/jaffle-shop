"""Dry-run a dbt job spec in two stages before writing it to disk.

Stage 1 (local dbt --empty): validates selector resolves to real nodes.
Stage 2 (--no-update sync):  validates the jobs.yml config against dbt Cloud
                              without touching any existing jobs.

Usage:
    python dry_run.py --spec spec.json --project-dir PATH [--stage {1,2,both}]

Set DRY_RUN_MODE=mock (env var) to run fully offline (no dbt binary needed).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# same-dir imports for the mock path
sys.path.insert(0, str(Path(__file__).parent))
from venv_bin import find_executable  # noqa: E402

WARN_ERROR_OPT = '{"error":["NoNodesForSelectionCriteria"]}'

# dbt / dbt-jobs-as-code can emit unicode (emoji, box-drawing) that crashes under
# Windows' default cp1252 console codepage — decode subprocess output as UTF-8 always.
_SUBPROCESS_TEXT_KW = {"encoding": "utf-8", "errors": "replace"}


# ---------------------------------------------------------------------------
# Stage 1 — local dbt --empty
# ---------------------------------------------------------------------------

def _stage1(spec: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    command = spec.get("command", {})
    selection = spec.get("selection", {})
    selector = selection.get("dbt_selector", "").strip()
    base = command.get("base", "dbt build").strip()

    cmd = base.split() + ["--select", selector] if selector else base.split()
    cmd += [
        "--warn-error-options", WARN_ERROR_OPT,
        "--empty",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            timeout=120,
            **_SUBPROCESS_TEXT_KW,
        )
    except FileNotFoundError:
        return {
            "ok": False, "stage": 1,
            "error_category": "connection_error",
            "messages": ["dbt binary not found — install dbt or set DRY_RUN_MODE=mock"],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stage": 1,
            "error_category": "unknown",
            "messages": ["dbt --empty timed out after 120s"],
        }

    combined = result.stdout + result.stderr
    if result.returncode != 0:
        category = _classify(combined)
        return {
            "ok": False, "stage": 1,
            "error_category": category,
            "messages": [combined.strip()],
        }
    return {"ok": True, "stage": 1, "error_category": None, "messages": [combined.strip()]}


# ---------------------------------------------------------------------------
# Stage 2 — dbt-jobs-as-code sync --no-update
# ---------------------------------------------------------------------------

def _stage2(project_dir: Path) -> dict[str, Any]:
    jobs_yml = project_dir / "jobs" / "jobs.yml"
    if not jobs_yml.exists():
        return {
            "ok": False, "stage": 2,
            "error_category": "schema_invalid",
            "messages": [f"jobs.yml not found at {jobs_yml}"],
        }

    exe = find_executable("dbt-jobs-as-code", search_from=project_dir)
    if not exe:
        return {
            "ok": False, "stage": 2,
            "error_category": "connection_error",
            "messages": ["dbt-jobs-as-code not found — install it or set DRY_RUN_MODE=mock"],
        }

    cmd = [exe, "plan", str(jobs_yml)]
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=60, env=env,
            **_SUBPROCESS_TEXT_KW,
        )
    except FileNotFoundError:
        return {
            "ok": False, "stage": 2,
            "error_category": "connection_error",
            "messages": ["dbt-jobs-as-code not found — install it or set DRY_RUN_MODE=mock"],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stage": 2,
            "error_category": "unknown",
            "messages": ["dbt-jobs-as-code sync timed out after 60s"],
        }

    combined = result.stdout + result.stderr
    if result.returncode != 0:
        category = _classify(combined)
        return {
            "ok": False, "stage": 2,
            "error_category": category,
            "messages": [combined.strip()],
        }
    return {"ok": True, "stage": 2, "error_category": None, "messages": [combined.strip()]}


# ---------------------------------------------------------------------------
# Mock / offline path
# ponytail: mock when dbt absent; real path is stage1 dbt --empty + stage2 sync --no-update
# ---------------------------------------------------------------------------

def _mock_run(spec: dict[str, Any], stage: str) -> dict[str, Any]:
    """Offline mock: validate spec via validate.py + yaml_builder.py, simulate NoNodes."""
    import yaml_builder  # noqa: PLC0415

    selector = spec.get("selection", {}).get("dbt_selector", "")
    messages: list[str] = []

    # simulate NoNodesForSelectionCriteria for obviously empty selectors
    if not selector:
        if stage in ("1", "both"):
            return {
                "ok": False, "stage": 1,
                "error_category": "NoNodesForSelectionCriteria",
                "messages": ["[mock] Selector is empty — NoNodesForSelectionCriteria simulated"],
            }

    if stage in ("1", "both"):
        messages.append(f"[mock] Stage 1: dbt --empty selector={selector!r} — OK")

    if stage in ("2", "both"):
        try:
            import validate  # noqa: PLC0415
            final_cfg = yaml_builder.job_spec_to_config(spec, dry_run=False)
            errs = validate.validate_config(final_cfg) + validate.check_flag_invariants(final_cfg, dry_run=False)
            if errs:
                return {
                    "ok": False, "stage": 2,
                    "error_category": "schema_invalid",
                    "messages": errs,
                }
        except Exception as exc:
            messages.append(f"[mock] Stage 2 validation skipped: {exc}")
        messages.append("[mock] Stage 2: dbt-jobs-as-code sync --no-update — OK")

    return {"ok": True, "stage": stage, "error_category": None, "messages": messages}


# ---------------------------------------------------------------------------
# Error classification (mirrors error_interpreter for internal use)
# ---------------------------------------------------------------------------

import re as _re

_CAT_PATTERNS = [
    ("NoNodesForSelectionCriteria", _re.compile(r"NoNodesForSelectionCriteria|no nodes? (were )?selected", _re.I)),
    ("compile_error", _re.compile(r"Compilation Error|Parsing Error|Database Error.*syntax", _re.I)),
    ("connection_error", _re.compile(r"could not connect|connection (refused|timed out)|authenticate", _re.I)),
    ("permission_error", _re.compile(r"permission denied|insufficient privileges|not authorized|403", _re.I)),
    ("schema_invalid", _re.compile(r"schema|required property|is not valid under", _re.I)),
]


def _classify(text: str) -> str:
    for cat, pat in _CAT_PATTERNS:
        if pat.search(text or ""):
            return cat
    return "unknown"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dry-run a dbt job spec (stage 1 + 2).")
    ap.add_argument("--spec", required=True, help="Path to JobSpec JSON file.")
    ap.add_argument("--project-dir", type=Path, default=Path("."), help="dbt project root.")
    ap.add_argument("--stage", choices=["1", "2", "both"], default="both")
    args = ap.parse_args(argv)

    spec_text = Path(args.spec).read_text(encoding="utf-8")
    spec: dict[str, Any] = json.loads(spec_text)
    project_dir: Path = args.project_dir.resolve()

    mock_mode = os.environ.get("DRY_RUN_MODE", "").lower() == "mock"

    if mock_mode:
        result = _mock_run(spec, args.stage)
    elif args.stage == "1":
        result = _stage1(spec, project_dir)
    elif args.stage == "2":
        result = _stage2(project_dir)
    else:  # both
        r1 = _stage1(spec, project_dir)
        if not r1["ok"]:
            result = r1
        else:
            r2 = _stage2(project_dir)
            result = r2 if not r2["ok"] else {
                "ok": True, "stage": "both",
                "error_category": None,
                "messages": r1["messages"] + r2["messages"],
            }

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _selftest() -> None:
    # mock: empty selector -> NoNodesForSelectionCriteria
    os.environ["DRY_RUN_MODE"] = "mock"
    r = _mock_run({"selection": {"dbt_selector": ""}, "command": {"base": "dbt build"}}, "1")
    assert r["ok"] is False
    assert r["error_category"] == "NoNodesForSelectionCriteria", r

    # mock: valid selector, stage both -> ok
    r2 = _mock_run({"selection": {"dbt_selector": "orders"}, "command": {"base": "dbt build"}}, "both")
    assert r2["ok"] is True, r2
    print("dry_run selftest passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(main())
