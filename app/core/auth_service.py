from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.account_manager import sanitize_session_name, session_file_from_name, session_name_from_phone, write_metadata
from app.core.telethon_compat import (
    SessionPasswordNeededError,
    api_candidates,
    chinese_error,
    create_client,
    safe_disconnect,
    sent_code_type_name,
)


@dataclass
class PendingPhoneLogin:
    session_file: Path
    phone: str
    client: Any
    phone_code_hash: str
    api_source: str
    role: str


@dataclass
class PendingQrLogin:
    session_file: Path
    client: Any
    qr_login: Any
    api_source: str
    role: str


class AuthService:
    def __init__(self) -> None:
        self._phone: dict[str, PendingPhoneLogin] = {}
        self._qr: dict[str, PendingQrLogin] = {}

    async def request_phone_code(
        self,
        phone: str,
        role: str,
        config: dict[str, Any],
        force_sms: bool = False,
    ) -> dict[str, Any]:
        phone = phone.strip()
        if not phone:
            raise ValueError("手机号不能为空")
        key = session_name_from_phone(phone)
        await self.cancel(key)
        session_file = session_file_from_name(key)

        last_error = ""
        for api in api_candidates(config):
            client = None
            try:
                client = create_client(session_file, api, config)
                await client.connect()
                sent = await client.send_code_request(phone, force_sms=force_sms)
                self._phone[key] = PendingPhoneLogin(
                    session_file=session_file,
                    phone=phone,
                    client=client,
                    phone_code_hash=sent.phone_code_hash,
                    api_source=api.source,
                    role=role,
                )
                code_type = sent_code_type_name(sent.type)
                tip = "验证码已发送。"
                if "App" in code_type:
                    tip = "Telegram 当前把验证码发到了已登录的 Telegram 客户端。如果收不到，请输入 sms 尝试短信，或改用扫码登录。"
                return {
                    "key": key,
                    "code_type": code_type,
                    "api_source": api.source,
                    "message": tip,
                }
            except Exception as exc:
                last_error = chinese_error(exc)
                if client is not None:
                    await safe_disconnect(client)
        raise RuntimeError(last_error or "请求验证码失败")

    async def complete_phone_login(self, key: str, code: str) -> dict[str, Any]:
        pending = self._phone.get(sanitize_session_name(key))
        if not pending:
            raise RuntimeError("没有待完成的验证码登录，请先请求验证码")
        try:
            user = await pending.client.sign_in(
                phone=pending.phone,
                code=code.strip(),
                phone_code_hash=pending.phone_code_hash,
            )
            return await self._finish_phone_login(pending, user)
        except SessionPasswordNeededError:
            return {"need_password": True, "message": "账号开启了两步验证，请输入密码"}
        except Exception as exc:
            raise RuntimeError(chinese_error(exc)) from exc

    async def complete_phone_password(self, key: str, password: str) -> dict[str, Any]:
        pending = self._phone.get(sanitize_session_name(key))
        if not pending:
            raise RuntimeError("没有待完成的两步验证登录")
        try:
            user = await pending.client.sign_in(password=password)
            return await self._finish_phone_login(pending, user)
        except Exception as exc:
            raise RuntimeError(chinese_error(exc)) from exc

    async def _finish_phone_login(self, pending: PendingPhoneLogin, user: Any) -> dict[str, Any]:
        metadata = self._metadata_for_user(user, pending.role, pending.api_source)
        metadata["phone"] = pending.phone
        write_metadata(pending.session_file, metadata)
        await safe_disconnect(pending.client)
        self._phone.pop(pending.session_file.stem, None)
        return {"success": True, "session": pending.session_file.name, "user": metadata.get("user", ""), "phone": metadata.get("phone", "")}

    async def start_qr_login(self, role: str, config: dict[str, Any]) -> dict[str, Any]:
        key = sanitize_session_name("qr_pending")
        await self.cancel(key, cleanup_qr=True)
        session_file = session_file_from_name(key)
        last_error = ""
        for api in api_candidates(config):
            client = None
            try:
                client = create_client(session_file, api, config)
                await client.connect()
                qr_login = await client.qr_login()
                self._qr[key] = PendingQrLogin(
                    session_file=session_file,
                    client=client,
                    qr_login=qr_login,
                    api_source=api.source,
                    role=role,
                )
                return {"key": key, "url": qr_login.url, "api_source": api.source}
            except Exception as exc:
                last_error = chinese_error(exc)
                if client is not None:
                    await safe_disconnect(client)
                await self._cleanup_qr_temp_files(session_file)
        raise RuntimeError(last_error or "创建扫码登录失败")

    async def wait_qr_login(self, key: str, timeout: int = 90) -> dict[str, Any]:
        pending = self._qr.get(sanitize_session_name(key))
        if not pending:
            raise RuntimeError("没有待完成的扫码登录")
        try:
            user = await asyncio.wait_for(pending.qr_login.wait(), timeout=timeout)
            return await self._finish_qr_login(pending, user)
        except SessionPasswordNeededError:
            return {"need_password": True, "message": "扫码已确认，账号开启了两步验证，请输入密码"}
        except asyncio.TimeoutError as exc:
            try:
                await self.cancel(pending.session_file.stem, cleanup_qr=True)
            except Exception as cleanup_exc:
                raise RuntimeError(f"扫码登录超时，后台登录已断开，但清理临时 session 失败：{cleanup_exc}") from exc
            raise RuntimeError("扫码登录超时，已断开后台登录并清理临时 session，请重新生成二维码") from exc
        except Exception as exc:
            raise RuntimeError(chinese_error(exc)) from exc

    async def complete_qr_password(self, key: str, password: str) -> dict[str, Any]:
        pending = self._qr.get(sanitize_session_name(key))
        if not pending:
            raise RuntimeError("没有待完成的扫码两步验证登录")
        try:
            user = await pending.client.sign_in(password=password)
            return await self._finish_qr_login(pending, user)
        except Exception as exc:
            raise RuntimeError(chinese_error(exc)) from exc

    async def _finish_qr_login(self, pending: PendingQrLogin, user: Any) -> dict[str, Any]:
        metadata = self._metadata_for_user(user, pending.role, pending.api_source)
        if not metadata.get("phone"):
            try:
                refreshed_user = await pending.client.get_me()
                metadata = self._metadata_for_user(refreshed_user, pending.role, pending.api_source)
            except Exception:
                pass
        await safe_disconnect(pending.client)
        final_session_file = pending.session_file
        phone_session_name = session_name_from_phone(str(metadata.get("phone") or ""))
        if phone_session_name and phone_session_name != pending.session_file.stem:
            final_session_file = self._replace_session_file(pending.session_file, session_file_from_name(phone_session_name))
        write_metadata(final_session_file, metadata)
        self._qr.pop(pending.session_file.stem, None)
        return {
            "success": True,
            "session": final_session_file.name,
            "user": metadata.get("user", ""),
            "phone": metadata.get("phone", ""),
        }

    def _replace_session_file(self, source: Path, target: Path) -> Path:
        if source == target:
            return source
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        source.replace(target)
        source_journal = source.with_name(f"{source.name}-journal")
        target_journal = target.with_name(f"{target.name}-journal")
        if source_journal.exists():
            if target_journal.exists():
                target_journal.unlink()
            source_journal.replace(target_journal)
        source_metadata = source.with_suffix(".json")
        if source_metadata.exists():
            source_metadata.unlink()
        return target

    async def cancel(self, key: str, cleanup_qr: bool = False) -> None:
        key = sanitize_session_name(key)
        phone = self._phone.pop(key, None)
        qr = self._qr.pop(key, None)
        if phone:
            await safe_disconnect(phone.client)
        if qr:
            await safe_disconnect(qr.client)
            if cleanup_qr:
                await self._cleanup_qr_temp_files(qr.session_file)

    async def close(self) -> None:
        keys = set(self._phone) | set(self._qr)
        for key in list(keys):
            await self.cancel(key, cleanup_qr=True)

    async def _cleanup_qr_temp_files(self, session_file: Path) -> None:
        if session_file.stem != "qr_pending":
            return
        targets = [
            session_file,
            session_file.with_suffix(".json"),
            Path(str(session_file) + "-journal"),
        ]
        last_error: Exception | None = None
        for _attempt in range(8):
            last_error = None
            for path in targets:
                if not path.exists() or not path.is_file():
                    continue
                try:
                    path.unlink()
                except Exception as exc:
                    last_error = exc
            if last_error is None:
                return
            await asyncio.sleep(0.25)
        if last_error is not None:
            raise last_error

    def _metadata_for_user(self, user: Any, role: str, api_source: str) -> dict[str, Any]:
        display = " ".join(part for part in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if part).strip()
        return {
            "role": role,
            "status": "可用",
            "user": display or getattr(user, "username", "") or str(getattr(user, "id", "")),
            "username": getattr(user, "username", "") or "",
            "phone": getattr(user, "phone", "") or "",
            "user_id": getattr(user, "id", ""),
            "api_source": api_source,
            "last_active": datetime.now().isoformat(timespec="seconds"),
            "today_count": 0,
        }
