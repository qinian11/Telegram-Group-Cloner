from __future__ import annotations

import asyncio
import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import normalize_sources
from app.core.account_manager import AccountManager, read_metadata, write_metadata
from app.core.telethon_compat import (
    FloodWaitError,
    SessionPasswordNeededError,
    UserBannedInChannelError,
    api_candidates,
    chinese_error,
    connect_client_with_repair,
    events,
    functions,
    safe_disconnect,
)
from app.logging_bus import LogBus


@dataclass
class CloneAccount:
    session_file: Path
    client: Any
    name: str
    metadata: dict[str, Any]
    today_count: int = 0
    next_available: float = 0.0


@dataclass
class ForwardRuntime:
    monitor_client: Any | None = None
    clone_accounts: list[CloneAccount] = field(default_factory=list)
    message_map: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    target: str = ""
    source_entities: list[Any] = field(default_factory=list)
    identity_cache: dict[tuple[str, int], tuple[float, tuple[Any, ...]]] = field(default_factory=dict)
    sender_locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    sender_account_map: dict[int, str] = field(default_factory=dict)
    round_robin_index: int = 0


class ForwardingController:
    def __init__(self, account_manager: AccountManager, logger: LogBus) -> None:
        self.account_manager = account_manager
        self.logger = logger
        self.message_map_path = self.account_manager.paths.cache_dir / "message_map.json"
        self._stop_event: asyncio.Event | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def run(self, config: dict[str, Any], selected_accounts: list[Path] | None = None) -> None:
        if self._running:
            self.logger.warning("监听任务已在运行，忽略重复启动")
            return
        self._running = True
        self._stop_event = asyncio.Event()
        runtime = ForwardRuntime()
        try:
            self._load_message_map(runtime)
            await self._run_inner(config, runtime, selected_accounts or [])
        finally:
            self._running = False
            self._save_message_map(runtime)
            await self._disconnect_runtime(runtime)
            self.logger.info("监听任务已停止，客户端连接已断开")

    async def _run_inner(self, config: dict[str, Any], runtime: ForwardRuntime, selected_accounts: list[Path]) -> None:
        sources = normalize_sources(config.get("groups", {}).get("sources", []))
        target = str(config.get("groups", {}).get("target") or "").strip()
        if not sources:
            raise RuntimeError("请先配置至少一个源群")
        if not target:
            raise RuntimeError("请先配置目标群")

        monitor_name = str(config.get("telegram", {}).get("monitor_session") or "monitor").removesuffix(".session")
        monitor_file = self.account_manager.paths.sessions_dir / f"{monitor_name}.session"
        if not monitor_file.exists():
            raise RuntimeError(f"未找到监听账号 session：{monitor_file.name}")

        self.logger.info("正在连接监听账号")
        runtime.monitor_client = await self._connect_authorized(monitor_file, config, "监听账号", receive_updates=True)
        await self._try_join_sources(runtime.monitor_client, sources)
        runtime.target = target
        for source in sources:
            try:
                entity = await runtime.monitor_client.get_entity(source)
                runtime.source_entities.append(entity)
                self.logger.ok(f"源群可访问：{source}")
            except Exception as exc:
                self.logger.warning(f"源群不可访问 {source}：{chinese_error(exc)}")
        if not runtime.source_entities:
            raise RuntimeError("所有源群均不可访问")

        await self._load_clone_accounts(config, runtime, selected_accounts)
        if not runtime.clone_accounts:
            raise RuntimeError("没有可用克隆账号，请先登录或导入账号")

        await self._try_join_target(runtime, target)
        self._install_handlers(config, runtime)
        self.logger.success(f"监听已启动：{len(runtime.source_entities)} 个源群，{len(runtime.clone_accounts)} 个克隆账号")

        assert self._stop_event is not None
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

    async def _connect_authorized(
        self,
        session_file: Path,
        config: dict[str, Any],
        label: str,
        receive_updates: bool,
    ) -> Any:
        meta = read_metadata(session_file)
        last_error = ""
        for api in api_candidates(config, meta):
            client = None
            try:
                self.logger.debug(f"{label} {session_file.stem} 使用 {api.source} 连接")
                client = await connect_client_with_repair(
                    session_file,
                    api,
                    config,
                    logger=self.logger.warning,
                    receive_updates=receive_updates,
                )
                if not await client.is_user_authorized():
                    await safe_disconnect(client)
                    last_error = "session 未授权"
                    continue
                meta.update({"status": "可用", "api_source": api.source, "last_active": datetime.now().isoformat(timespec="seconds")})
                write_metadata(session_file, meta)
                return client
            except SessionPasswordNeededError:
                last_error = "账号需要两步验证，请重新登录"
            except Exception as exc:
                last_error = chinese_error(exc)
                if client is not None:
                    await safe_disconnect(client)
        raise RuntimeError(f"{label} {session_file.name} 连接失败：{last_error}")

    async def _load_clone_accounts(self, config: dict[str, Any], runtime: ForwardRuntime, selected_accounts: list[Path]) -> None:
        selected_names = {path.stem for path in selected_accounts}
        records = self.account_manager.scan(config)
        for record in records:
            if record.directory != "sessions" or record.role in {"监听账号", "monitor"}:
                continue
            if selected_names and record.name not in selected_names:
                continue
            try:
                client = await self._connect_authorized(record.path, config, "克隆账号", receive_updates=False)
                meta = read_metadata(record.path)
                runtime.clone_accounts.append(
                    CloneAccount(
                        session_file=record.path,
                        client=client,
                        name=record.name,
                        metadata=meta,
                        today_count=int(meta.get("today_count") or 0),
                    )
                )
                self.logger.ok(f"克隆账号可用：{record.name}")
            except Exception as exc:
                self.logger.warning(f"克隆账号不可用 {record.name}：{chinese_error(exc)}")

    async def _try_join_sources(self, monitor_client: Any, sources: list[str]) -> None:
        if functions is None:
            return
        for source in sources:
            try:
                await monitor_client(functions.channels.JoinChannelRequest(source))
                self.logger.debug(f"监听账号已尝试加入源群：{source}")
            except Exception as exc:
                self.logger.debug(f"监听账号加入源群跳过 {source}：{chinese_error(exc)}")

    async def _try_join_target(self, runtime: ForwardRuntime, target: str) -> None:
        if functions is None:
            return
        for account in runtime.clone_accounts:
            try:
                await account.client(functions.channels.JoinChannelRequest(target))
                self.logger.ok(f"{account.name} 已尝试加入目标群")
            except Exception as exc:
                self.logger.debug(f"{account.name} 加入目标群跳过：{chinese_error(exc)}")

    def _install_handlers(self, config: dict[str, Any], runtime: ForwardRuntime) -> None:
        source_entities = runtime.source_entities

        @runtime.monitor_client.on(events.NewMessage(chats=source_entities))
        async def handle_new_message(event: Any) -> None:
            await self._handle_new_message(event, config, runtime)

        @runtime.monitor_client.on(events.MessageEdited(chats=source_entities))
        async def handle_edit(event: Any) -> None:
            await self._handle_edit(event, config, runtime)

        @runtime.monitor_client.on(events.MessageDeleted(chats=source_entities))
        async def handle_delete(event: Any) -> None:
            await self._handle_delete(event, runtime)

    async def _handle_new_message(self, event: Any, config: dict[str, Any], runtime: ForwardRuntime) -> None:
        try:
            sender = await event.get_sender()
        except Exception:
            return
        if not sender or getattr(sender, "bot", False):
            self.logger.debug("消息来自机器人或无法识别发送者，已跳过")
            return
        sender_id = int(getattr(sender, "id", 0) or getattr(event.message, "sender_id", 0) or 0)
        text = event.raw_text or ""
        if self._filtered(sender_id, text, config):
            self.logger.debug("消息命中过滤规则，已跳过")
            return
        if self._is_clone_sender(runtime, sender_id):
            self.logger.debug("消息来自克隆账号，已跳过以避免循环转发")
            return

        async with self._sender_lock(runtime, sender_id):
            await self._forward_new_message_locked(event, config, runtime, sender_id, text)

    async def _forward_new_message_locked(
        self,
        event: Any,
        config: dict[str, Any],
        runtime: ForwardRuntime,
        sender_id: int,
        text: str,
    ) -> None:
        account = self._pick_account(runtime, config, sender_id)
        if account is None:
            self.logger.error("没有可用克隆账号，消息未转发")
            return

        source_chat_id = self._source_chat_id(event)
        reply_to = None
        if event.message.reply_to_msg_id:
            mapping = self._get_mapping(runtime, source_chat_id, int(event.message.reply_to_msg_id))
            reply_to = mapping.get("target_message_id") if mapping else None

        try:
            await self._maybe_update_identity(account, event, config, runtime)
            await self._wait_for_account(account, config)
            text = self._apply_replacements(text, config)
            sent = await self._send_message(account, runtime, event, text, reply_to)
            self._set_mapping(runtime, source_chat_id, int(event.message.id), int(sent.id), account.name)
            self._mark_sent(account)
            self._apply_success_decay(account, config)
            self.logger.ok(f"{account.name} 已转发消息 {event.message.id} -> {sent.id}")
        except FloodWaitError as exc:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            account.next_available = asyncio.get_running_loop().time() + seconds
            self._apply_flood_penalty(account, config, seconds)
            self.logger.warning(f"{account.name} 触发 FloodWait，等待 {seconds} 秒")
        except UserBannedInChannelError:
            await self._handle_banned_account(runtime, account, "目标群封禁")
        except Exception as exc:
            self._remove_mapping(runtime, source_chat_id, int(event.message.id))
            if self._is_ban_error(exc):
                await self._handle_banned_account(runtime, account, chinese_error(exc))
            elif self._is_auth_or_frozen_error(exc):
                self.logger.error(f"{account.name} 授权失效：{chinese_error(exc)}")
                await safe_disconnect(account.client)
                if account in runtime.clone_accounts:
                    runtime.clone_accounts.remove(account)
            else:
                self.logger.error(f"{account.name} 转发失败：{chinese_error(exc)}")

    async def _send_message(self, account: CloneAccount, runtime: ForwardRuntime, event: Any, text: str, reply_to: int | None) -> Any:
        media = getattr(event.message, "media", None)
        if media:
            return await account.client.send_message(runtime.target, message=text or None, file=media, reply_to=reply_to)
        return await account.client.send_message(runtime.target, message=text or " ", reply_to=reply_to)

    async def _handle_edit(self, event: Any, config: dict[str, Any], runtime: ForwardRuntime) -> None:
        source_chat_id = self._source_chat_id(event)
        mapping = self._get_mapping(runtime, source_chat_id, int(event.message.id))
        if not mapping:
            self.logger.debug(f"编辑同步找不到映射，已跳过：{event.message.id}")
            return
        account = self._find_account(runtime, mapping.get("poster_name")) or self._pick_account(runtime, config)
        if account is None:
            self.logger.warning("编辑同步失败：没有可用克隆账号")
            return
        target_id = int(mapping["target_message_id"])
        try:
            text = self._apply_replacements(event.raw_text or "", config)
            media = getattr(event.message, "media", None)
            await account.client.edit_message(runtime.target, target_id, text=text, file=media)
            self.logger.ok(f"已同步编辑消息：{event.message.id}")
        except Exception as exc:
            if self._is_missing_target_message_error(exc):
                self._remove_mapping(runtime, source_chat_id, int(event.message.id))
                self.logger.debug(f"目标消息已不存在，已清理映射：{event.message.id}")
            else:
                self.logger.warning(f"编辑同步失败：{chinese_error(exc)}")

    async def _handle_delete(self, event: Any, runtime: ForwardRuntime) -> None:
        source_chat_id = int(getattr(event, "chat_id", 0) or 0)
        grouped: dict[str, list[int]] = defaultdict(list)
        for message_id in getattr(event, "deleted_ids", []):
            mapping = self._get_mapping(runtime, source_chat_id, int(message_id))
            if mapping:
                grouped[str(mapping.get("poster_name") or "")].append(int(mapping["target_message_id"]))
                self._remove_mapping(runtime, source_chat_id, int(message_id))
            else:
                self.logger.debug(f"删除同步找不到映射，已跳过：{message_id}")

        for poster_name, target_ids in grouped.items():
            account = self._find_account(runtime, poster_name) or (runtime.clone_accounts[0] if runtime.clone_accounts else None)
            if account is None:
                continue
            try:
                await account.client.delete_messages(runtime.target, target_ids)
                self.logger.ok(f"已同步删除 {len(target_ids)} 条消息")
            except Exception as exc:
                self.logger.warning(f"删除同步失败：{chinese_error(exc)}")

    def _filtered(self, sender_id: int, text: str, config: dict[str, Any]) -> bool:
        filters = config.get("filters", {})
        if sender_id in set(int(item) for item in filters.get("blocked_user_ids", []) if str(item).isdigit()):
            return True
        lowered = text.lower()
        for keyword in filters.get("blocked_keywords", []):
            if keyword and str(keyword).lower() in lowered:
                return True
        return False

    def _apply_replacements(self, text: str, config: dict[str, Any]) -> str:
        result = text
        for rule in config.get("replacements", []):
            old = str(rule.get("old") or "")
            new = str(rule.get("new") or "")
            if not old:
                continue
            flags = re.IGNORECASE if rule.get("ignore_case") else 0
            if rule.get("type") == "regex":
                try:
                    result = re.sub(old, new, result, flags=flags)
                except re.error as exc:
                    self.logger.warning(f"正则替换规则无效 {old}：{exc}")
            elif rule.get("ignore_case"):
                result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
            else:
                result = result.replace(old, new)
        return result

    async def _maybe_update_identity(self, account: CloneAccount, event: Any, config: dict[str, Any], runtime: ForwardRuntime) -> None:
        strategy = config.get("strategy", {})
        if not strategy.get("sync_name") and not strategy.get("sync_avatar"):
            return
        sender = await event.get_sender()
        sender_id = int(getattr(sender, "id", 0) or 0)
        if not sender_id:
            return
        first = str(getattr(sender, "first_name", "") or "")
        last = str(getattr(sender, "last_name", "") or "")
        photo_id = None
        if strategy.get("sync_avatar"):
            try:
                photos = await runtime.monitor_client.get_profile_photos(sender, limit=1)
                if photos:
                    photo_id = getattr(photos[0], "id", None)
            except Exception:
                photo_id = None

        signature = (first, last, photo_id)
        cache_key = (account.name, sender_id)
        now = asyncio.get_running_loop().time()
        cooldown = max(0, int(strategy.get("identity_cooldown_seconds") or 0))
        cached = runtime.identity_cache.get(cache_key)
        if cached and cached[1] == signature and now - cached[0] < cooldown:
            return

        if strategy.get("sync_name") and functions is not None:
            try:
                await account.client(functions.account.UpdateProfileRequest(first_name=first or " ", last_name=last or ""))
                self.logger.debug(f"{account.name} 已同步昵称：{first} {last}".strip())
            except Exception as exc:
                self.logger.warning(f"{account.name} 同步昵称失败：{chinese_error(exc)}")

        if strategy.get("sync_avatar") and photo_id and functions is not None:
            downloaded: str | None = None
            try:
                downloaded = await runtime.monitor_client.download_profile_photo(
                    sender,
                    file=str(self.account_manager.paths.cache_dir / f"avatar_{sender_id}_{account.name}"),
                )
                if downloaded:
                    uploaded = await account.client.upload_file(downloaded)
                    await account.client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
                    self.logger.debug(f"{account.name} 已同步头像")
            except Exception as exc:
                self.logger.warning(f"{account.name} 同步头像失败：{chinese_error(exc)}")
            finally:
                if downloaded:
                    try:
                        Path(downloaded).unlink(missing_ok=True)
                    except Exception:
                        pass

        runtime.identity_cache[cache_key] = (now, signature)

    def _sender_lock(self, runtime: ForwardRuntime, sender_id: int) -> asyncio.Lock:
        lock = runtime.sender_locks.get(sender_id)
        if lock is None:
            lock = asyncio.Lock()
            runtime.sender_locks[sender_id] = lock
        return lock

    def _pick_account(self, runtime: ForwardRuntime, config: dict[str, Any], sender_id: int | None = None) -> CloneAccount | None:
        now = asyncio.get_running_loop().time()
        strategy = config.get("strategy", {})
        daily_limit = int(strategy.get("daily_account_limit") or 0)
        candidates = [
            account
            for account in runtime.clone_accounts
            if account.next_available <= now and (daily_limit <= 0 or account.today_count < daily_limit)
        ]
        if not candidates:
            return None
        if sender_id:
            mapped_name = runtime.sender_account_map.get(sender_id)
            if mapped_name:
                mapped = self._find_account(runtime, mapped_name)
                if mapped in candidates:
                    return mapped
        account = candidates[runtime.round_robin_index % len(candidates)]
        runtime.round_robin_index += 1
        if sender_id:
            runtime.sender_account_map[sender_id] = account.name
        return account

    def _find_account(self, runtime: ForwardRuntime, name: str | None) -> CloneAccount | None:
        if not name:
            return None
        for account in runtime.clone_accounts:
            if account.name == name:
                return account
        return None

    def _is_clone_sender(self, runtime: ForwardRuntime, sender_id: int) -> bool:
        if not sender_id:
            return False
        for account in runtime.clone_accounts:
            try:
                if int(account.metadata.get("user_id") or 0) == int(sender_id):
                    return True
            except (TypeError, ValueError):
                continue
        return False

    async def _wait_for_account(self, account: CloneAccount, config: dict[str, Any]) -> None:
        strategy = config.get("strategy", {})
        if strategy.get("adaptive_throttle", True):
            min_wait = float(account.metadata.get("adaptive_min", strategy.get("send_interval_min") or 0))
            max_wait = float(account.metadata.get("adaptive_max", strategy.get("send_interval_max") or min_wait))
        else:
            min_wait = float(strategy.get("send_interval_min") or 0)
            max_wait = float(strategy.get("send_interval_max") or min_wait)
        max_wait = max(max_wait, min_wait)
        max_interval = float(strategy.get("max_interval_seconds") or max_wait)
        min_wait = min(min_wait, max_interval)
        max_wait = min(max_wait, max_interval)
        wait_seconds = random.uniform(min_wait, max_wait)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

    def _mark_sent(self, account: CloneAccount) -> None:
        account.today_count += 1
        account.metadata["today_count"] = account.today_count
        account.metadata["today_count_date"] = date.today().isoformat()
        account.metadata["last_active"] = datetime.now().isoformat(timespec="seconds")
        write_metadata(account.session_file, account.metadata)

    def _apply_success_decay(self, account: CloneAccount, config: dict[str, Any]) -> None:
        strategy = config.get("strategy", {})
        if not strategy.get("adaptive_throttle", True):
            return
        decay = float(strategy.get("adaptive_decay", 0.85))
        min_base = float(strategy.get("send_interval_min") or 0)
        max_base = float(strategy.get("send_interval_max") or min_base)
        cap = float(strategy.get("max_interval_seconds") or max_base)
        current_min = float(account.metadata.get("adaptive_min", min_base))
        current_max = float(account.metadata.get("adaptive_max", max_base))
        account.metadata["adaptive_min"] = max(min_base, min(current_min * decay, cap))
        account.metadata["adaptive_max"] = max(account.metadata["adaptive_min"], min(current_max * decay, cap))
        write_metadata(account.session_file, account.metadata)

    def _apply_flood_penalty(self, account: CloneAccount, config: dict[str, Any], wait_seconds: int) -> None:
        strategy = config.get("strategy", {})
        if not strategy.get("adaptive_throttle", True):
            return
        penalty = float(strategy.get("adaptive_penalty", 1.25))
        configured_penalty = float(strategy.get("floodwait_penalty_seconds") or 0)
        cap = float(strategy.get("max_interval_seconds") or max(wait_seconds, configured_penalty, 1))
        current_min = float(account.metadata.get("adaptive_min", strategy.get("send_interval_min") or 0))
        current_max = float(account.metadata.get("adaptive_max", strategy.get("send_interval_max") or current_min))
        new_min = min(cap, max(wait_seconds + 1, configured_penalty, current_min * penalty))
        new_max = min(cap, max(new_min, current_max * penalty))
        account.metadata["adaptive_min"] = new_min
        account.metadata["adaptive_max"] = new_max
        write_metadata(account.session_file, account.metadata)

    async def _handle_banned_account(self, runtime: ForwardRuntime, account: CloneAccount, reason: str) -> None:
        self.logger.error(f"{account.name} 已不可发送，正在迁移到 sessions_banned：{reason}")
        await safe_disconnect(account.client)
        if account in runtime.clone_accounts:
            runtime.clone_accounts.remove(account)
        self.account_manager.ban_session(account.session_file, reason)

    def _is_ban_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(
            marker in text or marker in name
            for marker in (
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
            )
        )

    def _is_auth_or_frozen_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(
            marker in text or marker in name
            for marker in (
                "frozen_method_invalid",
                "auth_key_unregistered",
                "unauthorized",
                "session_revoked",
            )
        )

    def _is_missing_target_message_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(marker in text or marker in name for marker in ("message_id_invalid", "messageidinvalid", "message not found", "deleted"))

    def _source_chat_id(self, event: Any) -> int:
        chat_id = getattr(event, "chat_id", None)
        if chat_id is not None:
            return int(chat_id)
        chat = getattr(event, "chat", None)
        if chat is not None and getattr(chat, "id", None) is not None:
            return int(chat.id)
        peer_id = getattr(getattr(event, "message", None), "peer_id", None)
        return int(getattr(peer_id, "channel_id", 0) or 0)

    def _load_message_map(self, runtime: ForwardRuntime) -> None:
        if not self.message_map_path.exists():
            return
        try:
            with self.message_map_path.open("r", encoding="utf-8") as file:
                items = json.load(file)
        except Exception as exc:
            self.logger.warning(f"读取消息映射失败，已忽略损坏缓存：{exc}")
            runtime.message_map = {}
            return

        loaded: dict[tuple[int, int], dict[str, Any]] = {}
        if isinstance(items, list):
            for item in items:
                try:
                    loaded[(int(item["source_chat_id"]), int(item["source_message_id"]))] = {
                        "target_message_id": int(item["target_message_id"]),
                        "poster_name": item.get("poster_name") or item.get("poster_phone") or "",
                    }
                except Exception:
                    continue
        runtime.message_map = loaded
        if loaded:
            self.logger.debug(f"已加载 {len(loaded)} 条消息映射")

    def _save_message_map(self, runtime: ForwardRuntime) -> None:
        self.message_map_path.parent.mkdir(parents=True, exist_ok=True)
        items = []
        for (source_chat_id, source_message_id), value in runtime.message_map.items():
            try:
                items.append(
                    {
                        "source_chat_id": int(source_chat_id),
                        "source_message_id": int(source_message_id),
                        "target_message_id": int(value["target_message_id"]),
                        "poster_name": value.get("poster_name") or "",
                    }
                )
            except Exception:
                continue
        with self.message_map_path.open("w", encoding="utf-8") as file:
            json.dump(items, file, ensure_ascii=False, indent=2)

    def _get_mapping(self, runtime: ForwardRuntime, source_chat_id: int, source_message_id: int) -> dict[str, Any] | None:
        return runtime.message_map.get((int(source_chat_id), int(source_message_id)))

    def _set_mapping(
        self,
        runtime: ForwardRuntime,
        source_chat_id: int,
        source_message_id: int,
        target_message_id: int,
        poster_name: str,
    ) -> None:
        runtime.message_map[(int(source_chat_id), int(source_message_id))] = {
            "target_message_id": int(target_message_id),
            "poster_name": poster_name,
        }
        self._save_message_map(runtime)

    def _remove_mapping(self, runtime: ForwardRuntime, source_chat_id: int, source_message_id: int) -> None:
        runtime.message_map.pop((int(source_chat_id), int(source_message_id)), None)
        self._save_message_map(runtime)

    async def _disconnect_runtime(self, runtime: ForwardRuntime) -> None:
        clients = [runtime.monitor_client] if runtime.monitor_client else []
        clients.extend(account.client for account in runtime.clone_accounts)
        for client in clients:
            await safe_disconnect(client)
