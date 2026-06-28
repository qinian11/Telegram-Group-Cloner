#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import contextlib
import os

from telethon import events
from telethon.tl.functions.channels import JoinChannelRequest


class MonitorMixin:
    async def start_monitoring(self, code_callback, pwd_callback):
        if self.is_monitoring or (self.monitor_task and not self.monitor_task.done()):
            self.log("监听已经在运行中。")
            return

        self.is_monitoring = True
        try:
            await self._cleanup_monitor_runtime(disconnect_pool=False)
            self._reload_config()
            if not self.source_groups:
                raise RuntimeError("源群组未配置。")
            if not self.target_group:
                raise RuntimeError("目标群组未配置。")

            with contextlib.suppress(Exception):
                self._load_message_map()

            self.log("策略配置已加载。")
            self.log(f"  - 克隆昵称: {self.clone_name_enabled}")
            self.log(f"  - 克隆头像: {self.clone_avatar_enabled}")
            self.log(f"  - 每日限制: {self.daily_clone_limit}")
            self.log(f"  - 冷却时间: {self.identity_cooldown_sec} 秒")
            self.log(f"  - 发送间隔: {self.min_send_interval}-{self.max_send_interval} 秒")

            self.monitor_client = await self._login_client(
                os.path.join("sessions", "monitor"),
                self.config.get("telegram", "monitor_phone", fallback=None),
                code_callback,
                pwd_callback,
            )
            if not self.monitor_client:
                raise RuntimeError("监听账号登录失败。")

            await self._load_or_login_sessions(code_callback, pwd_callback)
            if not self.clients_pool:
                self.log("没有可用克隆账号，监听会继续运行，但暂时不会转发。")

            joined = 0
            for group in self.source_groups:
                try:
                    self.log(f"监听账号尝试加入源群: {group}")
                    await self.monitor_client(JoinChannelRequest(group))
                    joined += 1
                except Exception as exc:
                    self.log(f"监听账号加入源群失败({group}): {exc}")
            if joined == 0:
                raise RuntimeError("监听账号无法加入任何源群。")
            self.log(f"监听账号已加入 {joined}/{len(self.source_groups)} 个源群。")

            self.monitor_client.add_event_handler(self._on_source_message, events.NewMessage(chats=self.source_groups))
            self.monitor_client.add_event_handler(self._on_source_edit, events.MessageEdited(chats=self.source_groups))
            self.monitor_client.add_event_handler(self._on_source_delete, events.MessageDeleted(chats=self.source_groups))

            self.monitor_task = asyncio.create_task(self.monitor_client.run_until_disconnected())
            self.log(f"开始监听源群: {', '.join(self.source_groups)}")
        except Exception:
            self.is_monitoring = False
            await self._cleanup_monitor_runtime(disconnect_pool=True)
            raise

    async def _cleanup_monitor_runtime(self, disconnect_pool: bool):
        task = self.monitor_task
        self.monitor_task = None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, timeout=2)
        if self.monitor_client:
            await self._safe_disconnect_client(self.monitor_client)
            self.monitor_client = None
        if disconnect_pool:
            clients = list(self.clients_pool.keys())
            if clients:
                await asyncio.gather(*(self._safe_disconnect_client(client) for client in clients), return_exceptions=True)
            self.clients_pool.clear()
            self.client_locks.clear()
            self.sender_locks.clear()

    async def stop_monitoring(self, force=False):
        runtime_exists = bool(self.monitor_client or self.monitor_task or self.clients_pool)
        if not self.is_monitoring and not force and not runtime_exists:
            self.log("监听未在运行。")
            return
        self.log("正在停止监听...")
        self.is_monitoring = False
        with contextlib.suppress(Exception):
            self._save_message_map()
        await self._cleanup_monitor_runtime(disconnect_pool=True)
        self.log("所有客户端已断开连接。")

    async def _on_source_message(self, event):
        try:
            sender = await event.get_sender()
        except Exception:
            return
        if not sender or getattr(sender, "bot", False):
            return
        if sender.id in self.blacklist_users:
            return
        text = getattr(event.message, "text", "") or ""
        if any(keyword and keyword in text for keyword in self.blacklist_keywords):
            return
        async with self._alloc_sender_lock(sender.id):
            client = await self._pick_client_for_sender(sender.id)
            if not client:
                return
            await self._maybe_update_identity(client, sender)
            await self._forward_with_throttle(client, event)

    def _resolve_source_event_ids(self, event):
        try:
            source_chat_id = int(getattr(event, "chat_id", 0))
            message = getattr(event, "message", None)
            source_message_id = int(message.id if message else getattr(event, "msg_id", 0))
        except Exception:
            return None, None
        if not source_chat_id or not source_message_id:
            return None, None
        return source_chat_id, source_message_id

    def _client_for_mapping(self, poster_phone):
        if poster_phone:
            return self._client_by_phone(poster_phone)
        return next(iter(self.clients_pool.keys()), None)

    async def _on_source_edit(self, event):
        source_chat_id, source_message_id = self._resolve_source_event_ids(event)
        if source_chat_id is None:
            return
        mapping = self._get_target_mapping(source_chat_id, source_message_id)
        if not mapping:
            return
        target_id, poster_phone = mapping
        client = self._client_for_mapping(poster_phone)
        if client is None:
            self.log(f"同步编辑跳过：找不到映射账号 {poster_phone or '-'}，源消息 {source_chat_id}/{source_message_id}。")
            return

        message = getattr(event, "message", None)
        text = self._apply_replacements(getattr(message, "text", "") or "")
        media = getattr(message, "media", None)
        try:
            await client.edit_message(self.target_group, target_id, text=text, file=media)
        except Exception as exc:
            if self._is_missing_target_message_error(exc):
                self._remove_target_mapping(source_chat_id, source_message_id)
                self.log(f"同步编辑失败：目标消息不存在，已清理映射 {source_chat_id}/{source_message_id} -> {target_id}。")
                return
            self.log(f"同步编辑失败，映射保留：{source_chat_id}/{source_message_id} -> {target_id}，错误：{exc}")

    async def _on_source_delete(self, event):
        try:
            source_chat_id = int(getattr(event, "chat_id", 0))
            deleted_ids = list(getattr(event, "deleted_ids", []) or [])
        except Exception:
            return
        if not source_chat_id or not deleted_ids:
            return

        for source_message_id in deleted_ids:
            mapping = self._get_target_mapping(source_chat_id, int(source_message_id))
            if not mapping:
                continue
            target_id, poster_phone = mapping
            client = self._client_for_mapping(poster_phone)
            if client is None:
                self.log(f"同步删除跳过：找不到映射账号 {poster_phone or '-'}，源消息 {source_chat_id}/{source_message_id}。")
                continue
            try:
                await client.delete_messages(self.target_group, target_id, revoke=True)
                self._remove_target_mapping(source_chat_id, int(source_message_id))
                self.log(f"同步删除成功，已清理映射 {source_chat_id}/{source_message_id} -> {target_id}。")
            except Exception as exc:
                if self._is_missing_target_message_error(exc):
                    self._remove_target_mapping(source_chat_id, int(source_message_id))
                    self.log(f"同步删除发现目标消息已不存在，已清理映射 {source_chat_id}/{source_message_id} -> {target_id}。")
                    continue
                self.log(f"同步删除失败，映射保留：{source_chat_id}/{source_message_id} -> {target_id}，错误：{exc}")

    def _client_by_phone(self, phone):
        for client, meta in self.clients_pool.items():
            if meta.get("phone") == phone:
                return client
        return None
