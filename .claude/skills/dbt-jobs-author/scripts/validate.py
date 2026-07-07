"""Validate generated config against the dbt-jobs-as-code JSON schema.

Validates a YAML or JSON config (or a JobSpec, by building both variants first)
against reference/load_job_schema.json. Also asserts the flag invariants:
  - dry-run steps contain `--empty`; final steps do not
  - every step carries the permanent warn-error flag

Usage:
    python validate.py --spec spec.json            # build + validate both variants
    python validate.py --config some_jobs.yml      # validate an existing config
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml_builder

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    jsonschema = None

SCHEMA_PATH = Path(__file__).parent.parent / "reference" / "load_job_schema.json"
WARN_ERROR = "NoNodesForSelectionCriteria"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return a list of error strings (empty == valid)."""
    if jsonschema is None:  # pragma: no cover
        return ["jsonschema not installed; run: pip install jsonschema"]
    validator = jsonschema.Draft7Validator(load_schema())
    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(config)]


def check_flag_invariants(config: dict[str, Any], dry_run: bool) -> list[str]:
    errs: list[str] = []
    for key, job in config.get("jobs", {}).items():
        for step in job.get("execute_steps", []):
            if WARN_ERROR not in step:
                errs.append(f"{key}: step missing warn-error flag: {step!r}")
            has_empty = "--empty" in step.split()
            if dry_run and not has_empty:
                errs.append(f"{key}: dry-run step missing --empty: {step!r}")
            if not dry_run and has_empty:
                errs.append(f"{key}: final step must NOT contain --empty: {step!r}")
    return errs


def _report(label: str, errs: list[str]) -> bool:
    if errs:
        print(f"  [FAIL] {label}")
        for e in errs:
            print(f"         - {e}")
        return False
    print(f"  [PASS] {label}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate dbt-jobs-as-code config / JobSpec.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="JobSpec JSON: build + validate both variants.")
    g.add_argument("--config", help="Existing config YAML/JSON to validate as-is.")
    args = ap.parse_args(argv)

    ok = True
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        final_cfg = yaml_builder.job_spec_to_config(spec, dry_run=False)
        dry_cfg = yaml_builder.job_spec_to_config(spec, dry_run=True)
        ok &= _report("final: schema", validate_config(final_cfg))
        ok &= _report("final: flag invariants", check_flag_invariants(final_cfg, dry_run=False))
        ok &= _report("dry_run: schema", validate_config(dry_cfg))
        ok &= _report("dry_run: flag invariants", check_flag_invariants(dry_cfg, dry_run=True))
    else:
        text = Path(args.config).read_text(encoding="utf-8")
        config = yaml.safe_load(text) if args.config.endswith((".yml", ".yaml")) else json.loads(text)
        ok &= _report("config: schema", validate_config(config))

    print("VALID" if ok else "INVALID")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
