"""Classify dbt / dbt-jobs-as-code error output into a category plus a
persona-appropriate explanation and follow-up.

Categories: NoNodesForSelectionCriteria, compile_error, connection_error,
permission_error, schema_invalid, unknown.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

_PATTERNS = [
    ("NoNodesForSelectionCriteria", re.compile(r"NoNodesForSelectionCriteria|no nodes? (were )?selected", re.I)),
    ("compile_error", re.compile(r"Compilation Error|Parsing Error|Database Error.*syntax", re.I)),
    ("connection_error", re.compile(r"could not connect|connection (refused|timed out)|Could not.*authenticate", re.I)),
    ("permission_error", re.compile(r"permission denied|insufficient privileges|not authorized|403", re.I)),
    ("schema_invalid", re.compile(r"schema|required property|is not valid under", re.I)),
    ("escalation_required", re.compile(r"escalat(e|ion)|no dashboard.{0,20}table mapping|mapping not found", re.I)),
]

_EXPLANATIONS = {
    "NoNodesForSelectionCriteria": {
        "business": (
            "The labels we guessed for this dashboard don't match any tables anymore. "
            "Let's confirm the names of the reports or tables behind it."
        ),
        "engineer": (
            "The selector matched zero nodes. With --warn-error-options this fails by design. "
            "Re-check the selector (tag/model/path) against the current manifest."
        ),
        "followup": "Which dashboard, report, or model(s) should this job actually cover?",
    },
    "compile_error": {
        "business": "One of the underlying data models has an error and couldn't be prepared.",
        "engineer": "dbt failed to compile/parse. Inspect the failing model's SQL/Jinja.",
        "followup": "Want me to surface the failing model and its compile error?",
    },
    "connection_error": {
        "business": "We couldn't reach the data platform to test this job.",
        "engineer": "Connection/auth to dbt Cloud or the warehouse failed. Check host/token/creds.",
        "followup": "Should I retry, or do the credentials/environment need updating?",
    },
    "permission_error": {
        "business": "This account doesn't have access to run that update.",
        "engineer": "Insufficient privileges. Check the service token / role grants.",
        "followup": "Which role/token should this job run under?",
    },
    "schema_invalid": {
        "business": "The job definition is missing some required details.",
        "engineer": "The generated config failed schema validation. See the listed field errors.",
        "followup": "I'll fill the missing fields — can you confirm the environment/schedule?",
    },
    "escalation_required": {
        "business": (
            "This step requires input from your data team — the dashboard-to-table mapping "
            "is missing or an unrecoverable condition was reached. "
            "Please escalate to your data analysts."
        ),
        "engineer": (
            "Escalation triggered: a required mapping or condition could not be resolved automatically. "
            "Check <project>/.claude/escalation_policy.yml for the escalation contact and channel."
        ),
        "followup": (
            "Review <project>/.claude/escalation_policy.yml for escalation contacts and next steps."
        ),
    },
    "unknown": {
        "business": "Something went wrong while testing the job.",
        "engineer": "Unrecognized error. See raw output.",
        "followup": "Want me to show the raw error output?",
    },
}


def classify(output: str) -> str:
    for category, pat in _PATTERNS:
        if pat.search(output or ""):
            return category
    return "unknown"


def interpret(output: str, persona: str = "business") -> dict:
    category = classify(output)
    info = _EXPLANATIONS[category]
    return {
        "category": category,
        "explanation": info[persona if persona in info else "business"],
        "followup": info["followup"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interpret dbt/CLI error output.")
    ap.add_argument("--persona", choices=["business", "engineer"], default="business")
    ap.add_argument("--text", help="Error text (else read stdin).")
    args = ap.parse_args(argv)
    text = args.text if args.text is not None else sys.stdin.read()
    print(json.dumps(interpret(text, args.persona), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
