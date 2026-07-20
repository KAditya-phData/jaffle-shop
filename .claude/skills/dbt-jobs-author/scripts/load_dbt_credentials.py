"""Resolve DBT_API_KEY / DBT_BASE_URL from ~/.dbt/dbt_cloud.yml and export them
into the OS environment — the exact names dbt-jobs-as-code itself reads
(os.environ.get("DBT_API_KEY"), os.environ.get("DBT_BASE_URL"), confirmed in
.venv/Lib/site-packages/dbt_jobs_as_code/main.py).

Never writes the key into any file under this skill (memory/, scripts/,
reference/, etc.) — only into the OS environment, via Python only:
  - Windows: HKEY_CURRENT_USER\\Environment via winreg (user/"local" scope,
    no admin needed). Falls back to the machine-wide HKEY_LOCAL_MACHINE hive
    only if the user hive write fails.
  - POSIX: no per-user registry equivalent exists, so this appends a marked
    export block to ~/.profile (reruns replace the block instead of
    duplicating it) — the user's own shell profile, not a skill file.

# ponytail: a brand-new process only picks up a persisted env var if its
# parent re-reads the registry/profile (new terminal, new session). Already-
# running shells in the current session won't see it until restarted; the
# os.environ assignment below covers only this process and its direct
# children. Upgrade path: none needed short of Windows broadcasting the
# change to already-running processes, which isn't possible from Python.

Usage:
    python load_dbt_credentials.py [--config PATH]

Output (stdout, JSON):
    {"ok": true, "host": "...", "base_url": "...", "persisted": "hkcu|hklm|profile|none"}
    or {"ok": false, "reason": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dbt_cloud_env import DEFAULT_CONFIG, load_config, resolve_active_project  # noqa: E402

_MARKER_START = "# >>> dbt-jobs-author DBT_API_KEY >>>"
_MARKER_END = "# <<< dbt-jobs-author DBT_API_KEY <<<"


def _broadcast_env_change() -> None:
    import ctypes

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x1A
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 0, 5000, None)


def _persist_windows(api_key: str, base_url: str) -> str:
    import winreg

    hives = (
        (winreg.HKEY_CURRENT_USER, "Environment", "hkcu"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "hklm"),
    )
    for hive, subkey, label in hives:
        try:
            key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "DBT_API_KEY", 0, winreg.REG_SZ, api_key)
            winreg.SetValueEx(key, "DBT_BASE_URL", 0, winreg.REG_SZ, base_url)
            winreg.CloseKey(key)
            _broadcast_env_change()
            return label
        except OSError:
            continue
    return "none"


def _persist_posix(api_key: str, base_url: str) -> str:
    profile = Path.home() / ".profile"
    block = f'{_MARKER_START}\nexport DBT_API_KEY="{api_key}"\nexport DBT_BASE_URL="{base_url}"\n{_MARKER_END}\n'
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if _MARKER_START in text:
        pre, _, rest = text.partition(_MARKER_START)
        _, _, post = rest.partition(_MARKER_END)
        text = pre + block + post.lstrip("\n")
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + block
    profile.write_text(text, encoding="utf-8")
    return "profile"


def run(config_path: Path) -> dict:
    if not config_path.exists():
        return {"ok": False, "reason": f"Config not found: {config_path}"}
    try:
        data = load_config(config_path)
        _, _, host, token = resolve_active_project(data)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    if not token:
        return {"ok": False, "reason": "token-value missing from config"}

    base_url = host if host.startswith("http") else f"https://{host}"
    os.environ["DBT_API_KEY"] = token
    os.environ["DBT_BASE_URL"] = base_url

    try:
        persisted = _persist_windows(token, base_url) if os.name == "nt" else _persist_posix(token, base_url)
    except Exception as exc:
        persisted = "none"
        print(f"Could not persist env vars: {exc}", file=sys.stderr)

    return {"ok": True, "host": host, "base_url": base_url, "persisted": persisted}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export DBT_API_KEY/DBT_BASE_URL from dbt_cloud.yml.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to dbt_cloud.yml")
    args = ap.parse_args(argv)
    result = run(args.config)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
