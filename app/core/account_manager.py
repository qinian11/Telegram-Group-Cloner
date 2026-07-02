from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.paths import ensure_runtime_dirs
from app.core.telethon_compat import api_candidates, chinese_error, connect_client_with_repair, safe_disconnect


@dataclass
class SessionRecord:
    name: str
    path: Path
    role: str
    status: str
    user: str
    phone: str
    last_active: str
    today_count: int
    directory: str
    metadata_path: Path | None = None


def metadata_path_for(session_file: Path) -> Path:
    return session_file.with_suffix(".json")


def read_metadata(session_file: Path) -> dict[str, Any]:
    path = metadata_path_for(session_file)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_metadata(session_file: Path, metadata: dict[str, Any]) -> None:
    path = metadata_path_for(session_file)
    with path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)


def session_file_from_name(name: str) -> Path:
    paths = ensure_runtime_dirs()
    cleaned = sanitize_session_name(name)
    return paths.sessions_dir / f"{cleaned}.session"


def sanitize_session_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-", "+") else "_" for ch in name.strip())
    return cleaned.strip("._") or "account"


def session_name_from_phone(phone: str) -> str:
    phone = phone.strip()
    if not phone:
        return ""
    prefix = "+" if phone.startswith("+") else ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return sanitize_session_name(f"{prefix}{digits}" if digits else phone)


def unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return target.with_name(f"{target.stem}_{stamp}{target.suffix}")


class AccountManager:
    def __init__(self) -> None:
        self.paths = ensure_runtime_dirs()

    def scan(self, config: dict[str, Any]) -> list[SessionRecord]:
        monitor_name = str(config.get("telegram", {}).get("monitor_session") or "monitor").removesuffix(".session")
        records: list[SessionRecord] = []
        for directory, directory_label in [
            (self.paths.sessions_dir, "sessions"),
            (self.paths.sessions_banned_dir, "sessions_banned"),
        ]:
            for session_file in sorted(directory.glob("*.session")):
                if session_file.name.endswith("-journal"):
                    continue
                meta = read_metadata(session_file)
                role = str(meta.get("role") or ("监听账号" if session_file.stem == monitor_name else "克隆账号"))
                status = "已封禁" if directory_label == "sessions_banned" else str(meta.get("status") or "待检测")
                user = str(meta.get("user") or meta.get("username") or "")
                phone = str(meta.get("phone") or "")
                last_active = str(meta.get("last_active") or "")
                today_count = int(meta.get("today_count") or 0)
                records.append(
                    SessionRecord(
                        name=session_file.stem,
                        path=session_file,
                        role=role,
                        status=status,
                        user=user,
                        phone=phone,
                        last_active=last_active,
                        today_count=today_count,
                        directory=directory_label,
                        metadata_path=metadata_path_for(session_file) if metadata_path_for(session_file).exists() else None,
                    )
                )
        return records

    def import_session(self, source: Path, role: str = "克隆账号") -> Path:
        if source.suffix.lower() != ".session":
            raise ValueError("请选择 .session 文件")
        target = unique_path(self.paths.sessions_dir / source.name)
        shutil.copy2(source, target)
        json_source = source.with_suffix(".json")
        if json_source.exists():
            shutil.copy2(json_source, target.with_suffix(".json"))
            meta = read_metadata(target)
        else:
            meta = {}
        meta["role"] = role
        meta["status"] = "待检测"
        meta["preferred_api"] = "telegram_desktop"
        meta["api_source"] = "Telegram Desktop 官方 API（导入优先检测）"
        meta["imported_at"] = datetime.now().isoformat(timespec="seconds")
        write_metadata(target, meta)
        return target

    def delete_session(self, session_file: Path) -> list[Path]:
        deleted: list[Path] = []
        for path in self.related_files(session_file):
            if path.exists() and path.is_file():
                path.unlink()
                deleted.append(path)
        return deleted

    def ban_session(self, session_file: Path, reason: str = "账号封禁") -> Path:
        target = unique_path(self.paths.sessions_banned_dir / session_file.name)
        session_file.replace(target)
        for related in [session_file.with_suffix(".json"), Path(str(session_file) + "-journal")]:
            if related.exists():
                related.replace(unique_path(self.paths.sessions_banned_dir / related.name))
        meta = read_metadata(target)
        meta["status"] = "已封禁"
        meta["ban_reason"] = reason
        meta["banned_at"] = datetime.now().isoformat(timespec="seconds")
        write_metadata(target, meta)
        return target

    def related_files(self, session_file: Path) -> list[Path]:
        return [
            session_file,
            session_file.with_suffix(".json"),
            Path(str(session_file) + "-journal"),
        ]

    def clear_avatar_cache(self) -> int:
        count = 0
        for path in self.paths.cache_dir.glob("avatar*"):
            if path.is_file():
                path.unlink()
                count += 1
            elif path.is_dir():
                shutil.rmtree(path)
                count += 1
        return count

    async def inspect_session(self, session_file: Path, config: dict[str, Any]) -> dict[str, Any]:
        meta = read_metadata(session_file)
        last_error = ""
        unauthorized_sources: list[str] = []
        for api in api_candidates(config, meta, prefer_desktop=True):
            client = None
            try:
                client = await connect_client_with_repair(session_file, api, config)
                authorized = await client.is_user_authorized()
                if not authorized:
                    unauthorized_sources.append(api.source)
                    last_error = f"{api.source} 返回未授权"
                    continue
                me = await client.get_me()
                user_name = " ".join(part for part in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if part).strip()
                meta.update(
                    {
                        "status": "可用",
                        "user": user_name or getattr(me, "username", "") or str(getattr(me, "id", "")),
                        "username": getattr(me, "username", "") or "",
                        "phone": getattr(me, "phone", "") or meta.get("phone", ""),
                        "user_id": getattr(me, "id", ""),
                        "api_id": api.api_id,
                        "api_hash": api.api_hash,
                        "api_source": api.source,
                        "last_active": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                write_metadata(session_file, meta)
                return meta
            except Exception as exc:
                last_error = chinese_error(exc)
            finally:
                if client is not None:
                    await safe_disconnect(client)
        if unauthorized_sources:
            meta.update(
                {
                    "status": "未授权",
                    "api_source": "、".join(unauthorized_sources),
                    "last_error": last_error or "所有 API 候选均返回未授权",
                }
            )
        else:
            meta.update({"status": "连接失败", "last_error": last_error})
        write_metadata(session_file, meta)
        return meta
