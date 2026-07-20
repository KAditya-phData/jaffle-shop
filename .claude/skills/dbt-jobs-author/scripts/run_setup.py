"""One-time setup orchestrator for dbt-jobs-author (SKILL.md sec 2.1).

Runs, in order, and stops on the first failure (except step 1, which only
degrades gracefully — see load_dbt_credentials.py):
  1. python scripts/load_dbt_credentials.py     -> exports DBT_API_KEY/DBT_BASE_URL
  2. Prereq check   - dbt on PATH; `dbt --version` / `dbt debug` captured.
                       (python being present is proven by this script running at all.)
  3. python scripts/dbt_cloud_env.py            -> account/project/host/environments
  4. python scripts/install_check.py --persona engineer -> dbt-jobs-as-code availability
  5. memory_io.save_setup_cache(...)            -> merges into memory/global/setup_cache.yml

Usage:
    python3 scripts/run_setup.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import load_dbt_credentials  # noqa: E402
import memory_io  # noqa: E402

# ponytail: no persona context exists in a pre-hook; "engineer" gives install steps
# instead of an escalation message, which is the more useful default here.
INSTALL_CHECK_PERSONA = "engineer"


def prereq_check() -> dict:
    dbt_path = shutil.which("dbt")
    if not dbt_path:
        print("which dbt | MISSING - install dbt before continuing", file=sys.stderr)
        sys.exit(1)
    dbt_version = subprocess.run(["dbt", "--version"], capture_output=True, text=True).stdout.strip()
    dbt_debug = subprocess.run(["dbt", "debug"], capture_output=True, text=True).stdout.strip()
    return {
        "python_version": sys.version.split()[0],
        "dbt_path": dbt_path,
        "dbt_version": dbt_version.splitlines()[0] if dbt_version else "",
        "dbt_debug": dbt_debug.splitlines()[0] if dbt_debug else "",
    }


def run_script(name: str, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return json.loads(result.stdout)


def main() -> int:
    # ponytail: credential load failure is non-fatal — connection_check.py
    # already degrades to {"status": "skipped"} when DBT_API_KEY is absent.
    creds = load_dbt_credentials.run(load_dbt_credentials.DEFAULT_CONFIG)

    prereqs = prereq_check()
    env_info = run_script("dbt_cloud_env.py")
    install_info = run_script("install_check.py", "--persona", INSTALL_CHECK_PERSONA)

    cache = memory_io.get_setup_cache()
    cache["tool_versions"] = {"python": prereqs["python_version"], "dbt": prereqs["dbt_version"]}
    cache["dbt_jobs_as_code_installed"] = install_info.get("installed")
    if env_info.get("status") != "unavailable":
        cache["account_id"] = env_info.get("account_id")
        cache["project_id"] = env_info.get("project_id")
        cache["host"] = env_info.get("host")
        cache["environments"] = env_info.get("environments", [])
    memory_io.save_setup_cache(cache)

    print(json.dumps({
        "credentials": creds,
        "prereqs": prereqs,
        "environments": env_info,
        "install_check": install_info,
        "cached_to": str(memory_io._SETUP_CACHE_PATH),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
