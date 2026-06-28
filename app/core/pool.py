#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import contextlib
import datetime
import os
import random
import shutil
from typing import Any, Dict, Optional

from telethon import TelegramClient
from telethon import utils as telethon_utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.photos import DeletePhotosRequest

from .utils import now_ts


class PoolMixin:
    def _alloc_sender_lock(self, sender_id: int) -> asyncio.Lock:
        lock = self.sender_locks.get(sender_id)
        if lock is None:
            lock = asyncio.Lock()
            self.sender_locks[sender_id] = lock
        return lock

    async def _pick_client_for_sender(self, sender_id: int) -> Optional[TelegramClient]:
        now = now_ts()
        for client, meta in self.clients_pool.items():
            if not meta.get("banned") and meta.get("user_id") == sender_id:
                meta["last_used"] = now
                return client

        idle_candidates = []
        for client, meta in self.clients_pool.items():
            if meta.get("banned") or meta.get("user_id") is not None:
                continue
            if self._check_daily_and_cooldown(meta):
                idle_candidates.append((client, meta))
        if idle_candidates:
            client, meta = random.choice(idle_candidates)
            meta["user_id"] = sender_id
            meta["last_used"] = now
            meta["last_identity_switch"] = now
            meta["daily_clones"] = self._inc_daily(meta["daily_date"], meta["daily_clones"])
            return client

        reusable = []
        for client, meta in self.clients_pool.items():
            if meta.get("banned"):
                continue
            if self._check_daily_and_cooldown(meta):
                reusable.append((client, meta))
        if reusable:
            client, meta = min(reusable, key=lambda item: item[1].get("last_used", 0.0))
            meta["user_id"] = sender_id
            meta["last_used"] = now
            meta["last_identity_switch"] = now
            meta["daily_clones"] = self._inc_daily(meta["daily_date"], meta["daily_clones"])
            return client

        self.log("没有可用账号：账号池为空、冷却中或已达到每日上限，本条消息跳过。")
        return None

    def _check_daily_and_cooldown(self, meta: Dict[str, Any]) -> bool:
        today = datetime.date.today().isoformat()
        if meta.get("daily_date") != today:
            meta["daily_date"] = today
            meta["daily_clones"] = 0
        if int(meta.get("daily_clones", 0)) >= max(0, int(self.daily_clone_limit)):
            return False
        if self.identity_cooldown_sec > 0 and now_ts() - float(meta.get("last_identity_switch", 0.0)) < self.identity_cooldown_sec:
            return False
        return True

    def _inc_daily(self, day: str, count: int) -> int:
        return int(count or 0) + 1

    def _move_session_to_banned(self, session_path: Optional[str]) -> bool:
        if not session_path or not os.path.exists(session_path):
            return False
        banned_dir = getattr(self, "sessions_banned_dir", "sessions_banned")
        os.makedirs(banned_dir, exist_ok=True)
        moved = False
        for path in (session_path, session_path + "-journal"):
            if not os.path.exists(path):
                continue
            dst = os.path.join(banned_dir, os.path.basename(path))
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(path, dst)
            moved = True
        return moved

    async def _handle_banned_client(self, client: TelegramClient):
        session_path = getattr(client.session, "filename", None)
        phone = "未知"
        with contextlib.suppress(Exception):
            if client.is_connected():
                me = await client.get_me()
                phone = getattr(me, "phone", "未知")
        self.clients_pool.pop(client, None)
        self.client_locks.pop(client, None)
        await self._safe_disconnect_client(client)

        try:
            moved = self._move_session_to_banned(session_path)
            if moved:
                self.log(f"账号 [{phone}] 在目标群受限，session 已移入 sessions_banned。")
            else:
                self.log(f"账号 [{phone}] 在目标群受限，已移出可用池；未找到可迁移 session 文件。")
        except Exception as exc:
            self.log(f"账号 [{phone}] 已移出可用池，但移动 session 文件失败：{exc}")

        if not self.clients_pool:
            self.log("当前账号池为空，监听会继续运行，但不会转发。请登录新账号或解除限制。")

    async def _cleanup_frozen_client(self, client: TelegramClient):
        phone = "未知"
        with contextlib.suppress(Exception):
            me = await client.get_me()
            phone = getattr(me, "phone", "未知")
        self.clients_pool.pop(client, None)
        self.client_locks.pop(client, None)
        await self._safe_disconnect_client(client)
        self.log(f"账号 [{phone}] 授权失效或连接异常，已移出账号池。")

    async def _ensure_join_target(self, client: TelegramClient):
        target = self.target_group or self.config.get("telegram", "target_group", fallback="")
        if not target:
            return
        try:
            await client(JoinChannelRequest(target))
            me = await client.get_me()
            self.log(f"[{getattr(me, 'phone', '?')}] 已加入目标群：{target}")
        except Exception as exc:
            text = str(exc).lower()
            if "already participant" in text or "user already participant" in text:
                return
            self.log(f"加入目标群失败：{exc}")

    async def do_join_target_for_all(self):
        self._reload_config()
        await self._ensure_pool_loaded_for_management()
        if not self.clients_pool:
            self.log("没有可用克隆账号，无法执行加入目标群。")
            return
        self.log("正在让所有克隆账号加入目标群...")
        for client in list(self.clients_pool.keys()):
            await self._ensure_join_target(client)
        self.log("加入目标群操作完成。")

    async def delete_all_photos(self):
        await self._ensure_pool_loaded_for_management()
        if not self.clients_pool:
            self.log("没有可用克隆账号，无法清空头像。")
            return
        self.log("正在清空所有克隆账号的历史头像...")
        for client in list(self.clients_pool.keys()):
            try:
                photos = await client.get_profile_photos("me")
                photo_inputs = []
                for photo in photos:
                    with contextlib.suppress(Exception):
                        photo_inputs.append(telethon_utils.get_input_photo(photo))
                if photo_inputs:
                    await client(DeletePhotosRequest(photo_inputs))
                me = await client.get_me()
                self.log(f"[{getattr(me, 'phone', '?')}] 已清空历史头像。")
            except Exception as exc:
                self.log(f"清空头像失败：{exc}")
        self.log("清空头像操作完成。")

    async def delete_account(self, identifier: str):
        target = (identifier or "").strip()
        if not target:
            self.log("未提供要删除的账号标识。")
            return False
        normalized_target = self._normalize_session_token(target)
        removed_any = False

        for client in list(self.clients_pool.keys()):
            meta = self.clients_pool.get(client, {})
            phone = str(meta.get("phone") or "")
            session_name = self._loaded_session_name(client)
            if target in {phone, session_name} or (
                normalized_target and normalized_target in {
                    self._normalize_session_token(phone),
                    self._normalize_session_token(session_name),
                }
            ):
                await self._safe_disconnect_client(client)
                self.clients_pool.pop(client, None)
                self.client_locks.pop(client, None)
                removed_any = True
                self.log(f"已从账号池移除：{phone or session_name or target}")

        for folder in (
            getattr(self, "sessions_dir", "sessions"),
            getattr(self, "sessions_banned_dir", "sessions_banned"),
        ):
            if not os.path.isdir(folder):
                continue
            for filename in list(os.listdir(folder)):
                if not filename.endswith(".session"):
                    continue
                session_name = filename[:-8]
                if session_name == "monitor":
                    continue
                if target != session_name and normalized_target != self._normalize_session_token(session_name):
                    continue
                session_path = os.path.join(folder, filename)
                related_paths = [
                    session_path,
                    session_path + "-journal",
                    os.path.splitext(session_path)[0] + ".json",
                    session_path + ".bak",
                ]
                for related_path in related_paths:
                    if not os.path.exists(related_path):
                        continue
                    with contextlib.suppress(Exception):
                        os.remove(related_path)
                        removed_any = True
                        self.log(f"已删除账号文件：{related_path}")
        if not removed_any:
            self.log(f"未找到账号：{target}")
        return removed_any

    def snapshot_pool(self):
        data = []
        loaded_session_keys = set()
        for client, meta in self.clients_pool.items():
            session_name = self._loaded_session_name(client)
            session_key = self._normalize_session_token(session_name) or session_name
            if session_key:
                loaded_session_keys.add(session_key)
            data.append({
                "phone": meta.get("phone", "") or session_name or "未知",
                "session_name": session_name,
                "folder": "sessions",
                "user_id": meta.get("user_id"),
                "last_used": meta.get("last_used", 0.0),
                "last_identity_switch": meta.get("last_identity_switch", 0.0),
                "daily_date": meta.get("daily_date", ""),
                "daily_clones": meta.get("daily_clones", 0),
                "banned": bool(meta.get("banned", False)),
                "loaded": True,
                "has_json": bool(meta.get("json_config", False)),
            })

        for entry in self._iter_session_entries(include_banned=True):
            session_key = self._normalize_session_token(entry["session_name"]) or entry["session_name"]
            if session_key in loaded_session_keys:
                continue
            data.append({
                "phone": entry["session_name"],
                "session_name": entry["session_name"],
                "folder": entry["folder"],
                "user_id": None,
                "last_used": 0.0,
                "last_identity_switch": 0.0,
                "daily_date": "",
                "daily_clones": 0,
                "banned": entry["banned"],
                "loaded": False,
                "has_json": entry.get("has_json", False),
            })
        return data

    def get_stats(self):
        snapshot = self.snapshot_pool()
        total = len(snapshot)
        active = sum(1 for item in snapshot if item.get("user_id") is not None and not item.get("banned", False))
        banned = sum(1 for item in snapshot if item.get("banned", False))
        idle = total - active - banned
        return {
            "total_accounts": total,
            "active_accounts": active,
            "idle_accounts": idle,
            "banned_accounts": banned,
            "total_messages_forwarded": self.total_messages_forwarded,
        }
