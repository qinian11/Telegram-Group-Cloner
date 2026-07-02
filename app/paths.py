from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    data_root: Path
    setting_dir: Path
    sessions_dir: Path
    sessions_banned_dir: Path
    cache_dir: Path
    logs_dir: Path
    exports_dir: Path
    config_file: Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def runtime_paths() -> RuntimePaths:
    root = app_root()
    data_root = Path(os.environ.get("TG_CLONER_DATA_DIR", root)).resolve()
    setting_dir = data_root / "setting"
    return RuntimePaths(
        app_root=root,
        data_root=data_root,
        setting_dir=setting_dir,
        sessions_dir=data_root / "sessions",
        sessions_banned_dir=data_root / "sessions_banned",
        cache_dir=data_root / "cache",
        logs_dir=data_root / "logs",
        exports_dir=data_root / "exports",
        config_file=setting_dir / "config.json",
    )


def ensure_runtime_dirs() -> RuntimePaths:
    paths = runtime_paths()
    for directory in [
        paths.setting_dir,
        paths.sessions_dir,
        paths.sessions_banned_dir,
        paths.cache_dir,
        paths.logs_dir,
        paths.exports_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    return paths
