"""Parse a user prompt into a partial JobSpec and detect persona.

Heuristic-only (no LLM calls) so it's deterministic and testable. The
orchestrating skill uses these as a first pass, then fills the rest through
clarifying questions and the resolver skills.

  - detect_persona(prompt): 'engineer' if dbt/CLI jargon present, else 'business'
  - extract_initial_spec(prompt): best-effort field extraction
  - fill_spec_with_answers(spec, answers): merge clarification answers
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jobspec import JobSpec  # noqa: E402

_ENGINEER_SIGNALS = [
    r"\btag:", r"--select\b", r"\bdbt (build|run|test|seed|snapshot)\b", r"\+\w", r"\bcron\b",
    r"--full-refresh", r"\bselector\b", r"\bmanifest\b", r"\bsource freshness\b", r"\bthreads\b",
    r"\bdefer\b", r"--state\b", r"\benvironment_id\b", r"\bmart\.", r"\bfct_", r"\bdim_",
]

_BUSINESS_SIGNALS = [r"\bdashboard\b", r"\breport\b", r"\bkpi\b", r"\bdon'?t know dbt\b", r"\bbusiness\b"]

_GROUP_WORDS = ["sales", "marketing", "finance", "operations", "ops", "product", "hr"]

_TIME_OF_DAY = {
    "morning": "0 10 * * *",   # ~6am ET -> 10:00 UTC (confirm tz with user)
    "midnight": "0 5 * * *",
    "nightly": "0 6 * * *",
    "hourly": "0 * * * *",
    "daily": "0 6 * * *",
}


def detect_persona(prompt: str) -> str:
    p = prompt.lower()
    eng = sum(bool(re.search(s, p)) for s in _ENGINEER_SIGNALS)
    biz = sum(bool(re.search(s, p)) for s in _BUSINESS_SIGNALS)
    return "engineer" if eng > biz else "business"


def _find_group(p: str) -> str:
    for g in _GROUP_WORDS:
        if re.search(rf"\b{g}\b", p):
            return "operations" if g == "ops" else g
    return ""


def _find_cron(p: str) -> tuple[str | None, str | None]:
    m = re.search(r"\bcron\b[:\s]+([\d*/,\- ]{5,})", p)
    if m:
        return m.group(1).strip(), None
    explicit = re.search(r"\bat\s+(\d{1,2})\s*(am|pm)\b", p)
    if explicit:
        hour = int(explicit.group(1)) % 12 + (12 if explicit.group(2) == "pm" else 0)
        return f"0 {hour} * * *", f"{explicit.group(0)} (timezone unconfirmed)"
    for word, cron in _TIME_OF_DAY.items():
        if word in p:
            human = "weekday " + word if "weekday" in p else word
            cron_val = cron.replace("* * *", "* * 1-5") if "weekday" in p else cron
            return cron_val, human
    return None, None


def _find_selector(p: str) -> str:
    m = re.search(r"--select\s+([^\n]+?)(?:\s--|\s*$)", p)
    if m:
        return m.group(1).strip()
    tags = re.findall(r"tag:\S+", p)
    models = re.findall(r"\b(?:fct_|dim_|stg_|marts?\.)\w+", p)
    return " ".join(tags + models).strip()


def extract_initial_spec(prompt: str) -> JobSpec:
    p = prompt.lower()
    spec = JobSpec()
    spec.persona = detect_persona(prompt)
    spec.business_group = _find_group(p)
    cron, human = _find_cron(p)
    spec.schedule.cron = cron
    spec.schedule.human = human
    spec.selection.nl_text = prompt.strip()
    spec.selection.dbt_selector = _find_selector(prompt)
    if "freshness" in p:
        spec.command.kind = "source_freshness"
        spec.command.base = "dbt source freshness"
    elif re.search(r"\bdbt run\b", p):
        spec.command.kind = "run"
        spec.command.base = "dbt run"
    elif re.search(r"\bdbt test\b", p):
        spec.command.kind = "test"
        spec.command.base = "dbt test"
    if "--full-refresh" in p:
        spec.command.extra_flags.append("--full-refresh")
    return spec


def fill_spec_with_answers(spec: JobSpec, answers: dict) -> JobSpec:
    """Merge a flat dict of clarification answers into the spec. Supports
    dotted keys like 'environment.project_id' and 'schedule.cron'."""
    for key, value in answers.items():
        if value in (None, ""):
            continue
        if "." in key:
            sec, attr = key.split(".", 1)
            target = getattr(spec, sec, None)
            if target is not None and hasattr(target, attr):
                setattr(target, attr, value)
        elif hasattr(spec, key):
            setattr(spec, key, value)
    return spec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse a prompt into a partial JobSpec.")
    ap.add_argument("prompt")
    args = ap.parse_args(argv)
    spec = extract_initial_spec(args.prompt)
    out = {"persona": spec.persona, "spec": spec.to_dict(), "missing": spec.missing_fields()}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
