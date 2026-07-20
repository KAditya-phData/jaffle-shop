"""Check whether dbt-jobs-as-code is installed.

Usage:
    python install_check.py --persona {business,engineer}

Output (stdout, JSON):
    {"installed": bool, "message": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from venv_bin import find_executable  # noqa: E402


def check_installed() -> bool:
    if find_executable("dbt-jobs-as-code"):
        return True
    try:
        import dbt_jobs_as_code  # noqa: F401  type: ignore
        return True
    except ImportError:
        return False


def build_message(installed: bool, persona: str) -> str:
    if installed:
        return "dbt-jobs-as-code is installed and available."
    if persona == "business":
        return (
            "dbt-jobs-as-code is not installed — ask your data engineering team to install it "
            "following the setup guide in reference/setup.md."
        )
    # engineer
    return (
        "dbt-jobs-as-code is not installed. Install it by following §3.1–3.2 in "
        "reference/setup.md:\n"
        "  1. pip install dbt-jobs-as-code\n"
        "  2. dbt-jobs-as-code import --account-id <id> --output-file jobs/jobs.yml\n"
        "  3. export DBT_API_KEY=<token>  (see §3.2 for token options)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check dbt-jobs-as-code installation.")
    ap.add_argument("--persona", choices=["business", "engineer"], required=True)
    args = ap.parse_args(argv)
    installed = check_installed()
    print(json.dumps({"installed": installed, "message": build_message(installed, args.persona)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
