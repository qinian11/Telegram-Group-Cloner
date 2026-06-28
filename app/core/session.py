#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import contextlib
import datetime
import json
import os
import shutil
import sqlite3
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import JoinChannelRequest


class SessionMixin:
    OFFICIAL_DESKTOP_API_ID = 2040
    OFFICIAL_DESKTOP_API_HASH = "b18441a1ff607e10a989891a5462e627"
    OFFICIAL_DESKTOP_DEVICE = {
        "device_model": "Desktop",
        "system_version": "Windows 10",
        "app_version": "5.0",
        "system_lang_code": "en",
        "lang_code": "en",
    }

    def get_proxy(self):
        if self.config.getboolean("proxy", "is_enabled", fallback=False):
            return (
                self.config.get("proxy", "type", fallback="socks5"),
                self.config.get("proxy", "host", fallback="127.0.0.1"),
                self.config.getint("proxy", "port", fallback=7890),
            )
        return None

    def _session_name_from_path(self, session_path: str) -> str:
        return os.path.basename(session_path).replace(".session", "")

    def _session_file_path(self, session_path: str) -> str:
        return session_path if session_path.endswith(".session") else f"{session_path}.session"

    def _session_json_path(self, session_path: str) -> str:
        return os.path.splitext(self._session_file_path(session_path))[0] + ".json"

    def _load_session_json(self, session_path: str) -> dict:
        json_path = self._session_json_path(session_path)
        if not os.path.exists(json_path):
            return {}
        try:
            with open(json_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            self.log(f"读取 session JSON 失败：{os.path.basename(json_path)}，{exc}")
        return {}

    def _session_api_config(self, session_path: str):
        candidates = self._session_api_candidates(session_path)
        if candidates:
            api_id, api_hash, json_config, _label = candidates[0]
            return api_id, api_hash, json_config
        return 0, "", {}

    def _session_api_candidates(self, session_path: str):
        json_config = self._load_session_json(session_path)
        candidates = []
        seen = set()

        def add_candidate(api_id, api_hash, config, label):
            if not api_id or not api_hash:
                return
            try:
                normalized = (int(api_id), str(api_hash))
            except (TypeError, ValueError):
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append((normalized[0], normalized[1], dict(config or {}), label))

        api_id = json_config.get("app_id") or json_config.get("api_id")
        api_hash = json_config.get("app_hash") or json_config.get("api_hash")
        if api_id and api_hash:
            before = len(candidates)
            add_candidate(api_id, api_hash, json_config, "session JSON")
            if len(candidates) == before:
                self.log(f"session JSON 中的 API 配置无效，改用全局配置：{os.path.basename(self._session_json_path(session_path))}")

        add_candidate(
            self.OFFICIAL_DESKTOP_API_ID,
            self.OFFICIAL_DESKTOP_API_HASH,
            {**self.OFFICIAL_DESKTOP_DEVICE, **json_config},
            "Telegram Desktop 官方 API",
        )
        add_candidate(
            self.config.getint("telegram", "api_id", fallback=0),
            self.config.get("telegram", "api_hash", fallback=""),
            json_config,
            "全局配置 API",
        )
        return candidates

    def _client_device_kwargs(self, json_config: dict) -> dict:
        if not json_config:
            return {}
        mapping = {
            "device_model": json_config.get("device_model"),
            "system_version": json_config.get("system_version") or json_config.get("sdk"),
            "app_version": json_config.get("app_version"),
            "lang_code": json_config.get("lang_code") or json_config.get("lang_pack"),
            "system_lang_code": json_config.get("system_lang_code"),
        }
        return {key: str(value) for key, value in mapping.items() if value}

    def _repair_session_schema(self, session_path: str) -> bool:
        session_file = self._session_file_path(session_path)
        if not os.path.exists(session_file):
            return False
        backup_path = session_file + ".bak"
        try:
            if not os.path.exists(backup_path):
                shutil.copy2(session_file, backup_path)
            conn = sqlite3.connect(session_file)
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(sessions)")
                existing_columns = [row[1] for row in cursor.fetchall()]
                required_columns = ["dc_id", "server_address", "port", "auth_key", "takeout_id", "tmp_auth_key"]
                if not existing_columns:
                    return False
                if existing_columns != required_columns:
                    cursor.execute("BEGIN TRANSACTION")
                    cursor.execute(
                        "CREATE TABLE sessions_new (dc_id INTEGER, server_address TEXT, port INTEGER, auth_key BLOB, takeout_id INTEGER, tmp_auth_key BLOB)"
                    )
                    select_cols = [col if col in existing_columns else "NULL" for col in required_columns]
                    cursor.execute(f"SELECT {', '.join(select_cols)} FROM sessions")
                    rows = cursor.fetchall()
                    for row in rows:
                        cursor.execute("INSERT INTO sessions_new VALUES (?,?,?,?,?,?)", row)
                    cursor.execute("DROP TABLE sessions")
                    cursor.execute("ALTER TABLE sessions_new RENAME TO sessions")
                cursor.execute("CREATE TABLE IF NOT EXISTS version (version integer primary key)")
                cursor.execute("SELECT version FROM version")
                if cursor.fetchone() is None:
                    cursor.execute("INSERT INTO version VALUES (8)")
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS entities (id integer primary key, hash integer not null, username text, phone integer, name text, date integer)"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS sent_files (md5_digest blob, file_size integer, type integer, id integer, hash integer, primary key(md5_digest, file_size, type))"
                )
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS update_state (id integer primary key, pts integer, qts integer, date integer, seq integer)"
                )
                conn.commit()
                self.log(f"已修复 session 表结构：{os.path.basename(session_file)}")
                return True
            finally:
                conn.close()
        except Exception as exc:
            self.log(f"修复 session 表结构失败：{os.path.basename(session_file)}，{exc}")
            return False

    def _build_telegram_client(self, session_path: str, api_id: int, api_hash: str, json_config: dict, receive_updates: bool = True) -> TelegramClient:
        kwargs = self._client_device_kwargs(json_config)
        return TelegramClient(
            session_path,
            api_id,
            api_hash,
            proxy=self.get_proxy(),
            loop=self.loop,
            receive_updates=receive_updates,
            timeout=15,
            connection_retries=1,
            **kwargs,
        )

    def _normalize_session_token(self, value: Optional[str]) -> str:
        text = (value or "").strip()
        if text.endswith("-journal"):
            text = text[:-8]
        if text.endswith(".session"):
            text = text[:-8]
        return "".join(ch for ch in text if ch.isdigit() or ch == "+")

    def _loaded_session_name(self, client: TelegramClient) -> str:
        try:
            filename = getattr(client.session, "filename", None)
            if filename:
                return os.path.basename(filename).replace(".session", "")
        except Exception:
            pass
        return ""

    def _find_pool_client_by_session(self, session_name: str):
        for client in list(self.clients_pool.keys()):
            if self._loaded_session_name(client) == session_name:
                return client
        return None

    def _remove_pool_client(self, client: TelegramClient) -> None:
        self.clients_pool.pop(client, None)
        self.client_locks.pop(client, None)

    def _iter_session_entries(self, include_banned=True):
        entries = []
        seen = set()
        directories = [(getattr(self, "sessions_dir", "sessions"), False)]
        if include_banned:
            directories.append((getattr(self, "sessions_banned_dir", "sessions_banned"), True))
        for folder, banned in directories:
            if not os.path.isdir(folder):
                continue
            for filename in os.listdir(folder):
                if not filename.endswith(".session"):
                    continue
                session_name = filename[:-8]
                if session_name == "monitor":
                    continue
                key = self._normalize_session_token(session_name) or session_name
                if key in seen:
                    continue
                seen.add(key)
                entries.append({
                    "folder": folder,
                    "path": os.path.join(folder, filename),
                    "session_name": session_name,
                    "json_path": os.path.join(folder, f"{session_name}.json"),
                    "has_json": os.path.exists(os.path.join(folder, f"{session_name}.json")),
                    "banned": banned,
                    "loaded": False,
                })
        entries.sort(key=lambda item: (item["banned"], item["session_name"]))
        return entries

    async def _safe_disconnect_client(self, client: Optional[TelegramClient], timeout: float = 3.0):
        if client is None:
            return
        try:
            if client.is_connected():
                await asyncio.wait_for(client.disconnect(), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log(f"断开客户端失败：{exc}")

    async def _ensure_pool_loaded_for_management(self):
        self._reload_config()
        await self._load_or_login_sessions(None, None)

    async def _login_client(self, session_path, phone=None, code_callback=None, pwd_callback=None):
        api_candidates = self._session_api_candidates(session_path)
        if not api_candidates:
            self.log("API ID / API Hash 未配置，无法登录账号。")
            return None

        session_name = self._session_name_from_path(session_path)
        if session_name != "monitor":
            existing = self._find_pool_client_by_session(session_name)
            if existing and existing.is_connected():
                return existing

        last_unauthorized = None
        interactive_login = bool(phone and code_callback)
        candidates_to_try = api_candidates if not interactive_login else api_candidates[:1]
        client = None
        api_id = None
        json_config = {}
        api_label = ""

        for candidate_api_id, candidate_api_hash, candidate_json_config, candidate_label in candidates_to_try:
            try:
                client = self._build_telegram_client(
                    session_path,
                    candidate_api_id,
                    candidate_api_hash,
                    candidate_json_config,
                    receive_updates=session_name == "monitor",
                )
            except ValueError as exc:
                err_msg = str(exc)
                if "not enough values to unpack" in err_msg or "too many values to unpack" in err_msg:
                    self.log(f"session {session_name} 表结构异常，尝试自动修复。")
                    if self._repair_session_schema(session_path):
                        client = self._build_telegram_client(
                            session_path,
                            candidate_api_id,
                            candidate_api_hash,
                            candidate_json_config,
                            receive_updates=session_name == "monitor",
                        )
                    else:
                        self.log(f"session {session_name} 修复失败，无法加载。")
                        return None
                else:
                    raise

            try:
                try:
                    await client.connect()
                except ValueError as exc:
                    err_msg = str(exc)
                    if "not enough values to unpack" in err_msg or "too many values to unpack" in err_msg:
                        await self._safe_disconnect_client(client)
                        self.log(f"session {session_name} 连接时发现表结构异常，尝试自动修复。")
                        if not self._repair_session_schema(session_path):
                            self.log(f"session {session_name} 修复失败，无法加载。")
                            return None
                        client = self._build_telegram_client(
                            session_path,
                            candidate_api_id,
                            candidate_api_hash,
                            candidate_json_config,
                            receive_updates=session_name == "monitor",
                        )
                        await client.connect()
                    else:
                        raise

                if await client.is_user_authorized():
                    api_id = candidate_api_id
                    json_config = candidate_json_config
                    api_label = candidate_label
                    break

                last_unauthorized = candidate_label
                if not interactive_login:
                    await client.disconnect()
                    client = None
                    continue
                break
            except Exception:
                await self._safe_disconnect_client(client)
                client = None
                raise

        if client is None:
            labels = " / ".join(label for *_rest, label in candidates_to_try)
            self.log(f"session {session_name} 未授权，已尝试：{labels}。如果你确认它有效，请检查是否缺少配套 JSON 或 Telegram 服务端已注销授权。")
            return None

        try:
            if not await client.is_user_authorized():
                if not phone:
                    phone = self.config.get("bootstrap", f"phone_{session_name}", fallback=None)
                if not phone or not code_callback:
                    await client.disconnect()
                    self.log(f"session {session_name} 未授权，当前 API：{api_label or last_unauthorized or '-'}。")
                    return None

                self.log(f"session {session_name} 未授权，开始登录，使用 API：{api_label or api_candidates[0][3]}")
                if api_id is None:
                    api_id, _api_hash, json_config, api_label = api_candidates[0]
                try:
                    sent_code = await client.send_code_request(phone)
                except FloodWaitError as exc:
                    wait = int(getattr(exc, "seconds", 5) or 5)
                    self.log(f"发送验证码触发 FloodWait，等待 {wait} 秒后重试。")
                    await asyncio.sleep(wait + 1)
                    sent_code = await client.send_code_request(phone)

                code = await code_callback()
                if not code:
                    await client.disconnect()
                    self.log(f"session {session_name} 登录取消：未输入验证码。")
                    return None
                try:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=sent_code.phone_code_hash)
                except SessionPasswordNeededError:
                    password = await pwd_callback() if pwd_callback else None
                    if not password:
                        await client.disconnect()
                        self.log(f"session {session_name} 需要 2FA 密码，但未提供。")
                        return None
                    await client.sign_in(password=password)

            if session_name != "monitor":
                self.clients_pool[client] = {
                    "user_id": None,
                    "last_used": 0.0,
                    "last_identity_switch": 0.0,
                    "daily_date": datetime.date.today().isoformat(),
                    "daily_clones": 0,
                    "phone": None,
                    "session_name": session_name,
                    "api_id": api_id,
                    "json_config": bool(json_config),
                    "banned": False,
                    "adaptive_min": self.min_send_interval,
                    "adaptive_max": self.max_send_interval,
                }
                self.client_locks[client] = asyncio.Lock()
                try:
                    me = await client.get_me()
                    self.clients_pool[client]["phone"] = getattr(me, "phone", "")
                except Exception:
                    pass

            self.log(f"账号登录成功：{session_name}")
            if api_label:
                self.log(f"session {session_name} 使用 API：{api_label}")
            return client
        except Exception:
            await self._safe_disconnect_client(client)
            self._remove_pool_client(client)
            raise

    async def login_new_account(self, phone, code_callback, pwd_callback):
        os.makedirs("sessions", exist_ok=True)
        session_name = self._normalize_session_token(phone) or str(phone).strip()
        client = await self._login_client(os.path.join("sessions", session_name), phone, code_callback, pwd_callback)
        if not client:
            return None
        try:
            await self._ensure_join_target(client)
            self.log(f"新账号 {phone} 已加入账号池。")
            return client
        except Exception as exc:
            self.log(f"新账号 {phone} 配置失败：{exc}")
            self._remove_pool_client(client)
            await self._safe_disconnect_client(client)
            return None

    async def login_monitor_account(self, phone, code_callback, pwd_callback):
        os.makedirs("sessions", exist_ok=True)
        if self.monitor_client:
            await self._safe_disconnect_client(self.monitor_client)
            self.monitor_client = None
        client = await self._login_client(os.path.join("sessions", "monitor"), phone, code_callback, pwd_callback)
        if not client:
            return None
        self.monitor_client = client
        try:
            self._reload_config()
            success = 0
            for group in self.source_groups:
                try:
                    await client(JoinChannelRequest(group))
                    success += 1
                except Exception as exc:
                    self.log(f"监听账号加入源群失败({group})：{exc}")
            if success:
                self.log(f"监听账号已加入 {success}/{len(self.source_groups)} 个源群。")
        except Exception as exc:
            self.log(f"初始化监听账号群组失败：{exc}")
        self.log("监听账号登录/更换完成。")
        return client

    async def delete_monitor_session(self):
        try:
            self.is_monitoring = False
            task = self.monitor_task
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, timeout=2)
            self.monitor_task = None
            await self._safe_disconnect_client(self.monitor_client)
            self.monitor_client = None
            for path in (os.path.join("sessions", "monitor.session"), os.path.join("sessions", "monitor.session-journal")):
                if os.path.exists(path):
                    os.remove(path)
            self.log("监听账号 session 已删除。")
        except Exception as exc:
            self.log(f"删除监听账号 session 失败：{exc}")

    async def _load_or_login_sessions(self, code_callback=None, pwd_callback=None):
        self.log("正在加载现有账号...")
        disconnected_clients = [client for client in list(self.clients_pool.keys()) if not client.is_connected()]
        for client in disconnected_clients:
            self._remove_pool_client(client)
            await self._safe_disconnect_client(client)

        os.makedirs("sessions", exist_ok=True)
        all_files = [filename for filename in os.listdir("sessions") if filename.endswith(".session")]
        if self.shard_total > 1:
            all_files = [
                filename for filename in all_files
                if hash(filename.rsplit(".session", 1)[0]) % self.shard_total == self.shard_index
            ]

        loaded = 0
        for filename in all_files:
            session_name = filename[:-8]
            if session_name == "monitor":
                self.log("跳过监听账号：monitor")
                continue
            existing = self._find_pool_client_by_session(session_name)
            if existing and existing.is_connected():
                loaded += 1
                continue
            try:
                client = await self._login_client(os.path.join("sessions", session_name), None, code_callback, pwd_callback)
                if client and client.is_connected():
                    loaded += 1
            except Exception as exc:
                self.log(f"加载 session {session_name} 失败：{exc}")
        self.log(f"已加载 {loaded} 个克隆账号。")

    async def shutdown(self):
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True
        try:
            current = asyncio.current_task()
            self.is_monitoring = False
            with contextlib.suppress(Exception):
                self._save_message_map()

            startup_tasks = [
                task for task in asyncio.all_tasks()
                if task is not current
                and not task.done()
                and getattr(task.get_coro(), "__qualname__", "").startswith("MonitorMixin.start_monitoring")
            ]
            for task in startup_tasks:
                task.cancel()
            if startup_tasks:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.gather(*startup_tasks, return_exceptions=True), timeout=6)

            await self._cleanup_monitor_runtime(disconnect_pool=True)

            pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                done, still_pending = await asyncio.wait(pending, timeout=6)
                for task in done:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        task.result()
                for task in still_pending:
                    self.log(f"关闭时仍有后台任务未结束：{getattr(task.get_coro(), '__qualname__', task.get_name())}")
            with contextlib.suppress(Exception):
                await self.loop.shutdown_asyncgens()
        finally:
            self._shutdown_in_progress = False
