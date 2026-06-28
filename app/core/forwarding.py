#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import re

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest

from .utils import now_ts


class ForwardingMixin:
    def _reload_config(self):
        source_group_str = self.config.get("telegram", "source_group", fallback="")
        self.source_groups = [item.strip() for item in source_group_str.split(",") if item.strip()]
        self.target_group = self.config.get("telegram", "target_group", fallback="")
        self.blacklist_users = {
            int(uid)
            for uid in self.config.get("blacklist", "user_ids", fallback="").split(",")
            if uid.strip().isdigit()
        }
        self.blacklist_keywords = {
            keyword.strip()
            for keyword in self.config.get("blacklist", "keywords", fallback="").split(",")
            if keyword.strip()
        }
        self.replacements = (
            dict(self.config.config.items("replacements"))
            if self.config.config.has_section("replacements")
            else {}
        )
        self.replacements_mode = (self.config.get("strategy", "replacements_mode", fallback="literal") or "literal").lower()
        self.replacements_case_insensitive = self.config.getboolean("strategy", "replacements_case_insensitive", fallback=False)
        self.clone_name_enabled = self.config.getboolean("strategy", "clone_name", fallback=True)
        self.clone_avatar_enabled = self.config.getboolean("strategy", "clone_avatar", fallback=True)
        self.daily_clone_limit = self.config.getint("strategy", "daily_clone_limit", fallback=30)
        self.identity_cooldown_sec = self.config.getint("strategy", "identity_cooldown_sec", fallback=3600)
        self.min_send_interval = max(0.0, float(self.config.get("strategy", "min_send_interval", fallback="1.0")))
        self.max_send_interval = max(self.min_send_interval, float(self.config.get("strategy", "max_send_interval", fallback="3.0")))
        self.adaptive_throttle = self.config.getboolean("strategy", "adaptive_throttle", fallback=True)
        self.adaptive_decay = float(self.config.get("strategy", "adaptive_decay", fallback=str(self.adaptive_decay)))
        self.adaptive_penalty = float(self.config.get("strategy", "adaptive_penalty", fallback=str(self.adaptive_penalty)))
        self.adaptive_cap = float(self.config.get("strategy", "adaptive_cap", fallback=str(self.adaptive_cap)))
        self.shard_total = max(1, int(self.config.get("strategy", "shard_total", fallback="1")))
        self.shard_index = max(0, min(self.shard_total - 1, int(self.config.get("strategy", "shard_index", fallback="0"))))

    def _apply_replacements(self, text: str) -> str:
        if not text:
            return text
        if self.replacements_mode == "regex":
            flags = re.IGNORECASE if self.replacements_case_insensitive else 0
            for old, new in self.replacements.items():
                try:
                    text = re.sub(old, new, text, flags=flags)
                except re.error as exc:
                    self.log(f"替换规则无效，已跳过：{old} ({exc})")
            return text
        if self.replacements_case_insensitive:
            for old, new in self.replacements.items():
                text = re.compile(re.escape(old), flags=re.IGNORECASE).sub(new, text)
            return text
        for old, new in self.replacements.items():
            text = text.replace(old, new)
        return text

    def _is_ban_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(marker in text or marker in name for marker in (
            "banned from sending messages",
            "write forbidden",
            "write_forbidden",
            "chatwriteforbidden",
            "chat_write_forbidden",
            "userbannedinchannel",
            "user_banned_in_channel",
            "not enough rights",
            "chatrestricted",
            "chat_restricted",
        ))

    def _is_auth_or_frozen_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(marker in text or marker in name for marker in (
            "frozen_method_invalid",
            "auth_key_unregistered",
            "unauthorized",
            "session_revoked",
        ))

    async def _maybe_update_identity(self, client: TelegramClient, sender):
        sender_id = sender.id
        first = sender.first_name or ""
        last = sender.last_name or ""
        photo_id = None
        try:
            photos = await self.monitor_client.get_profile_photos(sender, limit=1)
            if photos:
                photo_id = getattr(photos[0], "id", None)
        except Exception:
            pass

        old_sig = self.profile_cache.get(sender_id)
        new_sig = (first, last, photo_id)
        need_update_name = old_sig is None and self.clone_name_enabled
        need_update_photo = old_sig is None and self.clone_avatar_enabled and photo_id is not None
        if old_sig is not None:
            need_update_name = self.clone_name_enabled and (first != old_sig[0] or last != old_sig[1])
            need_update_photo = self.clone_avatar_enabled and photo_id is not None and photo_id != old_sig[2]

        if need_update_name:
            try:
                await client(UpdateProfileRequest(first_name=first or " ", last_name=last or ""))
                me = await client.get_me()
                self.log(f"[{getattr(me, 'phone', '?')}] 已更新昵称：{first} {last}".strip())
            except Exception as exc:
                self.log(f"更新昵称失败：{exc}")

        if need_update_photo:
            tmp_path = None
            try:
                photos = await self.monitor_client.get_profile_photos(sender, limit=1)
                if photos:
                    os.makedirs("cache", exist_ok=True)
                    tmp_path = await self.monitor_client.download_media(photos[0], file="cache/")
                if tmp_path:
                    uploaded = await client.upload_file(tmp_path)
                    await client(UploadProfilePhotoRequest(file=uploaded))
                    me = await client.get_me()
                    self.log(f"[{getattr(me, 'phone', '?')}] 已更新头像。")
            except Exception as exc:
                self.log(f"更新头像失败：{exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        self.profile_cache[sender_id] = new_sig

    async def _send_message_once(self, client: TelegramClient, event, text, reply_to):
        return await client.send_message(
            self.target_group,
            message=text,
            file=getattr(event.message, "media", None),
            reply_to=reply_to,
        )

    def _record_forward_mapping(self, event, sent, meta):
        source_chat_id = getattr(event, "chat_id", None)
        source_message = getattr(event, "message", None)
        source_message_id = getattr(source_message, "id", None)
        target_message_id = getattr(sent, "id", None)
        if source_chat_id is None or source_message_id is None or target_message_id is None:
            self.log("转发成功但缺少消息 ID，已跳过映射写入。")
            return
        phone = meta.get("phone") if meta else None
        self._set_target_mapping(source_chat_id, source_message_id, target_message_id, phone)

    async def _forward_with_throttle(self, client: TelegramClient, event):
        text = self._apply_replacements(getattr(event.message, "text", "") or "")
        meta = self.clients_pool.get(client)
        if meta:
            waited = now_ts() - meta.get("last_used", 0.0)
            target_gap = self._get_target_gap(meta)
            if waited < target_gap:
                await asyncio.sleep(target_gap - waited)

        reply_to = None
        if getattr(event, "reply_to_msg_id", None):
            source_chat_id = getattr(event, "chat_id", None)
            if source_chat_id is not None:
                mapping = self._get_target_mapping(int(source_chat_id), int(event.reply_to_msg_id))
                reply_to = mapping[0] if mapping else None

        try:
            try:
                sent = await self._send_message_once(client, event, text, reply_to)
            except FloodWaitError as exc:
                wait = int(getattr(exc, "seconds", 5) or 5)
                self.log(f"命中 FloodWait，等待 {wait} 秒后重试。")
                if meta:
                    self._apply_flood_penalty(meta, wait)
                await asyncio.sleep(wait + 1)
                sent = await self._send_message_once(client, event, text, reply_to)

            self._record_forward_mapping(event, sent, meta)
            if meta:
                meta["last_used"] = now_ts()
                self._apply_success_decay(meta)
            self.total_messages_forwarded += 1
        except Exception as exc:
            self.log(f"转发失败：{exc}")
            if self._is_ban_error(exc):
                await self._handle_banned_client(client)
            elif self._is_auth_or_frozen_error(exc):
                await self._cleanup_frozen_client(client)
