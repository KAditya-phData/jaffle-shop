"""Render a JobSpec into a human-readable description shown before any write.

Two registers:
  - business: plain language, hides selectors/flags, explains the warn-error
    safety behavior in outcome terms.
  - engineer: surfaces the actual dbt command, selector, target, cron, and flag
    semantics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jobspec import JobSpec  # noqa: E402

_CRON_HINTS = {
    "0 10 * * 1-5": "every weekday at 10:00 UTC",
    "0 6 * * *": "every day at 06:00 UTC",
    "0 * * * *": "every hour",
}


def _cadence(spec: JobSpec) -> str:
    if spec.schedule.human:
        return spec.schedule.human
    if spec.schedule.cron in _CRON_HINTS:
        return _CRON_HINTS[spec.schedule.cron]
    return f"on cron `{spec.schedule.cron}`"


def describe_job(spec: JobSpec, persona: str | None = None) -> str:
    persona = persona or spec.persona
    cadence = _cadence(spec)
    env = spec.environment.target

    if persona == "engineer":
        selector = spec.selection.dbt_selector.strip()
        steps = spec.command.steps or [
            f"{spec.command.base} --select {selector}".strip() if selector else spec.command.base
        ]
        steps_str = "\n".join(f"  - `{s} --warn-error-options '{{\"error\":[\"NoNodesForSelectionCriteria\"]}}'`" for s in steps)
        return (
            f"**Job:** {spec.name}  (`job_type={spec.job_type}`, target `{env}`, group `{spec.business_group}`)\n"
            f"**Schedule:** `{spec.schedule.cron}` ({cadence})\n"
            f"**Steps:**\n{steps_str}\n"
            f"**Safety:** the permanent `--warn-error-options` flag makes the run fail on "
            f"`NoNodesForSelectionCriteria` rather than silently no-op. The dry-run variant additionally "
            f"appends `--empty`."
        )

    # business register
    return (
        f"This job “{spec.name}” will run {cadence} in the **{env}** environment "
        f"for the **{spec.business_group}** group. It refreshes the data behind "
        f"“{spec.selection.nl_text}”, and it will fail loudly if it ever points at "
        f"tables that no longer exist — instead of quietly doing nothing."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Describe a JobSpec for a persona.")
    ap.add_argument("spec_json", help="Path to a JobSpec JSON (orchestrator to_dict form).")
    ap.add_argument("--persona", choices=["business", "engineer"])
    args = ap.parse_args(argv)
    spec = JobSpec.from_dict(json.loads(Path(args.spec_json).read_text(encoding="utf-8")))
    print(describe_job(spec, args.persona))
    return 0


if __name__ == "__main__":
    sys.exit(main())
