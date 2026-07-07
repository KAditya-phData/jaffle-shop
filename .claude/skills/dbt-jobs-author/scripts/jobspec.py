"""JobSpec: the internal representation of a dbt job before it becomes YAML.

This is the two-layer design from prompt.md: a convenient internal spec that
the orchestrator reasons about and fills via clarification, then projects into
dbt-jobs-as-code YAML (handled by the dbt-job-yaml-builder skill).

Kept dependency-free (dataclasses + dicts) so it serializes cleanly to JSON
across the skill/subagent boundary. `to_builder_dict()` produces exactly the
JobSpec contract the yaml-builder consumes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Environment:
    target: str = "prod"
    project_id: int | None = None
    environment_id: int | None = None


@dataclass
class Schedule:
    kind: str = "cron"  # cron | interval | manual
    cron: str | None = None
    human: str | None = None


@dataclass
class Selection:
    nl_text: str = ""
    dbt_selector: str = ""


@dataclass
class Command:
    kind: str = "build"  # build | run | test | source_freshness
    base: str = "dbt build"
    extra_flags: list[str] = field(default_factory=list)
    steps: list[str] | None = None  # optional explicit multi-step list


@dataclass
class JobSpec:
    name: str = ""
    business_group: str = ""
    description: str = ""
    account_id: int | None = None
    environment: Environment = field(default_factory=Environment)
    schedule: Schedule = field(default_factory=Schedule)
    selection: Selection = field(default_factory=Selection)
    command: Command = field(default_factory=Command)
    job_type: str = "scheduled"
    run_generate_sources: bool = False
    generate_docs: bool = False
    cost_optimization_features: list[str] = field(default_factory=lambda: ["state_aware_orchestration"])
    custom_environment_variables: list[dict[str, Any]] = field(default_factory=list)
    job_key: str = ""
    identifier: str = ""
    persona: str = "business"  # business | engineer

    # --- completeness ------------------------------------------------------

    REQUIRED = (
        "name",
        "business_group",
        "account_id",
        ("environment", "project_id"),
        ("environment", "environment_id"),
        ("selection", "dbt_selector"),
    )

    def missing_fields(self) -> list[str]:
        """Return required fields still unset (used to drive clarification)."""
        missing: list[str] = []
        d = asdict(self)
        for req in self.REQUIRED:
            if isinstance(req, tuple):
                sec, key = req
                if not d.get(sec, {}).get(key):
                    missing.append(f"{sec}.{key}")
            elif not d.get(req):
                missing.append(req)
        # schedule.cron required unless ci/merge
        if self.job_type not in ("ci", "merge") and not self.schedule.cron:
            missing.append("schedule.cron")
        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()

    # --- (de)serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobSpec":
        d = dict(d)
        d["environment"] = Environment(**d.get("environment", {}))
        d["schedule"] = Schedule(**d.get("schedule", {}))
        d["selection"] = Selection(**d.get("selection", {}))
        d["command"] = Command(**d.get("command", {}))
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_builder_dict(self) -> dict[str, Any]:
        """Project to the JobSpec contract consumed by dbt-job-yaml-builder."""
        out: dict[str, Any] = {
            "job_key": self.job_key or _slug(self.name),
            "name": self.name,
            "identifier": self.identifier or self.job_key or _slug(self.name),
            "business_group": self.business_group,
            "description": self.description,
            "account_id": self.account_id,
            "environment": {
                "target": self.environment.target,
                "project_id": self.environment.project_id,
                "environment_id": self.environment.environment_id,
            },
            "schedule": {"cron": self.schedule.cron, "human": self.schedule.human},
            "selection": {"nl_text": self.selection.nl_text, "dbt_selector": self.selection.dbt_selector},
            "command": {"base": self.command.base, "extra_flags": self.command.extra_flags},
            "job_type": self.job_type,
            "run_generate_sources": self.run_generate_sources,
            "generate_docs": self.generate_docs,
            "cost_optimization_features": self.cost_optimization_features,
        }
        if self.command.steps:
            out["command"]["steps"] = self.command.steps
        if self.custom_environment_variables:
            out["custom_environment_variables"] = self.custom_environment_variables
        return out


def _slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "_" for c in text)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "job"


if __name__ == "__main__":
    # tiny smoke test
    s = JobSpec(name="Demo", business_group="sales")
    print("missing:", s.missing_fields())
    print(json.dumps(s.to_builder_dict(), indent=2))
