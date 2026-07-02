# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse
import sys

from app.config import ConfigStore
from app.paths import ensure_runtime_dirs, runtime_paths


APP_NAME = "TG群组克隆 "
APP_VERSION = "版本1.0.0  作者TG:@hy499"


def run_self_test() -> int:
    """A non-GUI smoke test used by packaging and headless verification."""
    ensure_runtime_dirs()
    store = ConfigStore()
    config = store.load()
    store.save(config)
    paths = runtime_paths()
    required = [
        paths.setting_dir,
        paths.sessions_dir,
        paths.sessions_banned_dir,
        paths.cache_dir,
        paths.logs_dir,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("SELF_TEST_FAILED missing directories:", missing)
        return 2
    print(f"{APP_NAME} {APP_VERSION} self-test OK")
    print(f"data_root={paths.data_root}")
    print(f"config={paths.config_file}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--self-test", action="store_true", help="run a non-GUI startup smoke test")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if args.self_test:
        return run_self_test()

    ensure_runtime_dirs()
    from app.ui.app import TelegramClonerApp

    app = TelegramClonerApp(app_name=APP_NAME, version=APP_VERSION)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
