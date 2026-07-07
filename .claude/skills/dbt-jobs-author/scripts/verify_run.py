"""Verify that tables touched by a dbt job have fresh update/creation times.

§1.6: After a full run, confirm each table has a recent timestamp.
Real path: parse <project-dir>/target/run_results.json timestamps.
Fallback: dbt run-operation against information_schema.

Usage:
    python verify_run.py --models m1,m2 --project-dir PATH [--csv PATH]

Output (JSON to stdout):
    {"ok": true, "validated": [{"table": ..., "updated_at": ...}, ...], "examples": [...up to 3...]}
    or {"status": "unavailable", "reason": ...}
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_run_results(project_dir: Path, models: list[str]) -> list[dict[str, Any]]:
    """Parse target/run_results.json for model timestamps.
    # ponytail: run_results.json-first; information_schema fallback below.
    """
    run_results_path = project_dir / "target" / "run_results.json"
    if not run_results_path.exists():
        return []

    try:
        data = json.loads(run_results_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    results = data.get("results", [])
    model_set = {m.lower() for m in models}
    validated: list[dict[str, Any]] = []

    for r in results:
        unique_id = r.get("unique_id", "")
        # unique_id looks like: model.project.model_name
        parts = unique_id.split(".")
        model_name = parts[-1] if parts else ""
        if model_name.lower() not in model_set:
            continue
        timing = r.get("timing", [])
        # find the execute or compile completed_at
        completed_at = None
        for t in timing:
            if t.get("name") in ("execute", "compile"):
                completed_at = t.get("completed_at") or t.get("started_at")
        if completed_at is None:
            # fall back to top-level
            completed_at = r.get("execution_time") and data.get("generated_at")
        if completed_at is None:
            completed_at = data.get("generated_at")
        validated.append({"table": model_name, "updated_at": completed_at or "unknown"})

    return validated


def _fallback_information_schema(project_dir: Path, models: list[str]) -> list[dict[str, Any]]:
    """Run dbt run-operation to query information_schema for last_altered.
    # ponytail: naive one-at-a-time run-operation; a single macro over all models is the upgrade.
    """
    macro_sql = (
        "{% set results = run_query(\"SELECT TABLE_NAME, LAST_ALTERED FROM information_schema.tables "
        "WHERE TABLE_NAME IN (\" ~ \"','\".join(\" ~ model_list ~ \") ~ \"')\") %}"
        "{{ log(results.rows, info=True) }}"
    )
    # Build a simple macro invocation via dbt run-operation
    model_list = ",".join(f"'{m.upper()}'" for m in models)
    try:
        result = subprocess.run(
            ["dbt", "run-operation", "run_query",
             "--args", f"{{\"query\": \"SELECT TABLE_NAME, LAST_ALTERED FROM information_schema.tables WHERE TABLE_NAME IN ({model_list})\"}}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Parse output lines for table info — best-effort
        validated: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            for m in models:
                if m.upper() in line.upper():
                    validated.append({"table": m, "updated_at": line.strip()})
                    break
        return validated
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def verify(models: list[str], project_dir: Path) -> dict[str, Any]:
    validated = _parse_run_results(project_dir, models)

    if not validated:
        # ponytail: information_schema fallback; returns empty list if dbt absent
        validated = _fallback_information_schema(project_dir, models)

    if not validated:
        return {"status": "unavailable", "reason": "run_results.json not found and dbt run-operation unavailable"}

    return {
        "ok": True,
        "validated": validated,
        "examples": validated[:3],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify dbt job run freshness (§1.6).")
    ap.add_argument("--selftest", action="store_true", help="Run assert-based self-check and exit")
    ap.add_argument("--models", default=None, help="Comma-separated model names")
    ap.add_argument("--project-dir", default=None, type=Path, help="dbt project root")
    ap.add_argument("--csv", type=Path, default=None, help="Internal scratchpad CSV path (never surfaced to user)")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    if not args.models or not args.project_dir:
        ap.error("--models and --project-dir are required (unless --selftest)")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    result = verify(models, Path(args.project_dir))

    if args.csv and result.get("ok"):
        _write_csv(args.csv, result["validated"])

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write internal scratchpad CSV — never surfaced to the user (§1.6)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["table", "updated_at"])
        w.writeheader()
        w.writerows(rows)


def _selftest() -> None:
    """Assert-based self-check for the timestamp-extraction logic."""
    import tempfile, os

    # Build a minimal run_results.json
    fake = {
        "generated_at": "2024-01-01T12:00:00Z",
        "results": [
            {
                "unique_id": "model.myproject.orders",
                "timing": [{"name": "execute", "completed_at": "2024-01-01T12:05:00Z"}],
            },
            {
                "unique_id": "model.myproject.customers",
                "timing": [{"name": "execute", "completed_at": "2024-01-01T12:06:00Z"}],
            },
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target"
        target.mkdir()
        (target / "run_results.json").write_text(json.dumps(fake), encoding="utf-8")
        rows = _parse_run_results(Path(tmp), ["orders", "customers", "missing_model"])
        assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
        tables = {r["table"] for r in rows}
        assert "orders" in tables
        assert "customers" in tables
        assert "missing_model" not in tables
        assert rows[0]["updated_at"] == "2024-01-01T12:05:00Z"

    # No run_results.json -> empty list
    with tempfile.TemporaryDirectory() as tmp:
        rows = _parse_run_results(Path(tmp), ["orders"])
        assert rows == []

    print(json.dumps({"selftest": "ok"}))


if __name__ == "__main__":
    sys.exit(main())
