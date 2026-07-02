from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.paths import ensure_runtime_dirs, runtime_paths


TELEGRAM_DESKTOP_API_ID = "2040"
TELEGRAM_DESKTOP_API_HASH = "b18441a1ff607e10a989891a5462e627"


DEFAULT_CONFIG: dict[str, Any] = {
    "telegram": {
        "api_id": TELEGRAM_DESKTOP_API_ID,
        "api_hash": TELEGRAM_DESKTOP_API_HASH,
        "phone": "",
        "monitor_session": "monitor",
        "use_desktop_fallback": True,
    },
    "proxy": {
        "enabled": False,
        "type": "socks5",
        "host": "",
        "port": "",
        "username": "",
        "password": "",
    },
    "groups": {
        "sources": [],
        "target": "",
    },
    "filters": {
        "blocked_user_ids": [],
        "blocked_keywords": [],
    },
    "replacements": [
        {
            "type": "literal",
            "old": "",
            "new": "",
            "ignore_case": False,
        }
    ],
    "strategy": {
        "sync_name": True,
        "sync_avatar": True,
        "identity_sync_user_set": False,
        "identity_cooldown_seconds": 180,
        "daily_account_limit": 200,
        "shard_total": 1,
        "shard_index": 0,
        "send_interval_min": 2.0,
        "send_interval_max": 5.0,
        "adaptive_throttle": True,
        "adaptive_decay": 0.85,
        "adaptive_penalty": 1.25,
        "floodwait_penalty_seconds": 60,
        "max_interval_seconds": 600,
        "replacement_mode": "literal",
    },
    "runtime": {
        "theme": "system",
        "log_panel": "bottom",
        "log_panel_user_set": False,
        "selected_accounts": [],
    },
}


def deep_merge(default: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(default)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def apply_builtin_defaults(config: dict[str, Any]) -> dict[str, Any]:
    telegram = config.setdefault("telegram", {})
    if not str(telegram.get("api_id") or "").strip():
        telegram["api_id"] = TELEGRAM_DESKTOP_API_ID
    if not str(telegram.get("api_hash") or "").strip():
        telegram["api_hash"] = TELEGRAM_DESKTOP_API_HASH

    strategy = config.setdefault("strategy", {})
    if not strategy.get("identity_sync_user_set", False):
        strategy["sync_name"] = True
        strategy["sync_avatar"] = True
        strategy["identity_sync_user_set"] = False
    return config


class ConfigStore:
    """JSON config loader that keeps unknown historical fields intact."""

    def __init__(self, path: Path | None = None) -> None:
        ensure_runtime_dirs()
        self.path = path or runtime_paths().config_file

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return apply_builtin_defaults(copy.deepcopy(DEFAULT_CONFIG))
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError:
            backup = self.path.with_suffix(".json.broken")
            self.path.replace(backup)
            return apply_builtin_defaults(copy.deepcopy(DEFAULT_CONFIG))
        if not isinstance(data, dict):
            return apply_builtin_defaults(copy.deepcopy(DEFAULT_CONFIG))
        return apply_builtin_defaults(deep_merge(DEFAULT_CONFIG, data))

    def save(self, config: dict[str, Any]) -> None:
        ensure_runtime_dirs()
        current: dict[str, Any] = {}
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    current = loaded
            except json.JSONDecodeError:
                current = {}
        merged = apply_builtin_defaults(deep_merge(current or DEFAULT_CONFIG, config))
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(merged, file, ensure_ascii=False, indent=2)


def normalize_sources(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = value.replace(",", "\n").splitlines()
    return [item.strip() for item in raw_items if item and item.strip()]


def lines_to_list(value: str) -> list[str]:
    return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]


def parse_int_list(value: str) -> list[int]:
    result: list[int] = []
    for item in lines_to_list(value):
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def list_to_lines(value: list[Any]) -> str:
    return "\n".join(str(item) for item in value)


def parse_replacement_lines(value: str, default_mode: str = "literal") -> list[dict[str, Any]]:
    replacements: list[dict[str, Any]] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "->" in line:
            old, new = line.split("->", 1)
        elif default_mode == "literal" and "-" in line:
            old, new = line.split("-", 1)
        else:
            continue
        old = old.strip()
        new = new.strip()
        if not old:
            continue
        replacements.append(
            {
                "type": default_mode if default_mode in {"literal", "regex"} else "literal",
                "old": old,
                "new": new,
                "ignore_case": False,
            }
        )
    return replacements


def replacements_to_lines(replacements: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in replacements:
        old = str(item.get("old", ""))
        new = str(item.get("new", ""))
        if old or new:
            lines.append(f"{old}->{new}")
    return "\n".join(lines)
