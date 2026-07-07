"""Gate environment selection to DEV/STG/QA only; always deny PROD.

Usage:
    python env_guard.py <chosen_env> [--allowed DEV,STG,QA] [--persona {business,engineer}] [--project NAME]
    python env_guard.py --selftest

Output (stdout, JSON):
    {"decision": "allow|deny|ask|escalate", "reason": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys

# Environments that are ALWAYS denied regardless of --allowed
_ALWAYS_DENY = {"PROD", "PRODUCTION"}

# Default safe list (case-insensitive)
_DEFAULT_ALLOWED = {"DEV", "STG", "QA"}


def evaluate(chosen: str, allowed: set[str] | None, persona: str) -> dict[str, str]:
    """Pure decision function — testable without CLI."""
    upper = chosen.strip().upper()

    # PROD is always denied
    if upper in _ALWAYS_DENY:
        return {
            "decision": "deny",
            "reason": (
                f"'{chosen}' is a production environment. Please ask the user to promote "
                "the job to prod themselves."
            ),
        }

    effective = {e.upper() for e in allowed} if allowed else _DEFAULT_ALLOWED

    if upper in effective:
        return {"decision": "allow", "reason": f"'{chosen}' is in the allowed list."}

    # Unknown environment — no allowed list configured
    if allowed is None:
        if persona == "business":
            return {
                "decision": "escalate",
                "reason": (
                    f"The accepted environment list for this project is unknown. "
                    "Please escalate to your data engineering team to configure it."
                ),
            }
        return {
            "decision": "ask",
            "reason": (
                f"'{chosen}' is not in the default allowed list (DEV/STG/QA) and no "
                "--allowed list was provided. Please confirm which environments are valid for this project."
            ),
        }

    # Explicit list was given but env not in it
    return {
        "decision": "deny",
        "reason": (
            f"'{chosen}' is not in the allowed list ({', '.join(sorted(effective))}). "
            "Choose one of the allowed environments."
        ),
    }


def _selftest() -> None:
    assert evaluate("PROD", None, "engineer")["decision"] == "deny"
    assert evaluate("prod", None, "business")["decision"] == "deny"
    assert evaluate("DEV", None, "engineer")["decision"] == "allow"
    assert evaluate("dev", None, "business")["decision"] == "allow"
    assert evaluate("QA", None, "engineer")["decision"] == "allow"
    assert evaluate("STAGING", None, "engineer")["decision"] == "ask"
    assert evaluate("STAGING", None, "business")["decision"] == "escalate"
    assert evaluate("STAGING", {"STAGING", "DEV"}, "engineer")["decision"] == "allow"
    assert evaluate("UAT", {"DEV", "STG"}, "engineer")["decision"] == "deny"
    print(json.dumps({"selftest": "passed"}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guard dbt Cloud environment selection.")
    ap.add_argument("chosen_env", nargs="?", help="The environment name to evaluate")
    ap.add_argument("--allowed", help="Comma-separated list of allowed envs (e.g. DEV,STG,QA)")
    ap.add_argument("--persona", choices=["business", "engineer"], default="engineer")
    ap.add_argument("--project", help="Project name (informational)")
    ap.add_argument("--selftest", action="store_true", help="Run assert-based self-check")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    if not args.chosen_env:
        ap.error("chosen_env is required unless --selftest is used")

    allowed = {e.strip() for e in args.allowed.split(",")} if args.allowed else None
    result = evaluate(args.chosen_env, allowed, args.persona)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
