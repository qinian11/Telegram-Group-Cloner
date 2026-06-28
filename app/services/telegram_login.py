#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from datetime import datetime
from typing import Optional, Callable, Tuple

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError


class TelegramLogin:
    def __init__(self, parent_window=None, log_callback: Optional[Callable[[str], None]] = None):
        self.parent_window = parent_window
        self.log = log_callback or (lambda s: print(f"[{datetime.now():%H:%M:%S}] {s}"))
        self.client: Optional[TelegramClient] = None

    async def login_async(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_name: str,
        code_getter: Callable[[], str],
        pwd_getter: Optional[Callable[[], str]] = None,
    ) -> Tuple[bool, Optional[dict]]:
        try:
            self.client = TelegramClient(session_name, api_id, api_hash)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.log("发送验证码...")
                sent = await self.client.send_code_request(phone)

                code = code_getter()
                if not code:
                    return False, None

                try:
                    await self.client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                except SessionPasswordNeededError:
                    if not pwd_getter:
                        return False, None
                    pwd = pwd_getter()
                    await self.client.sign_in(password=pwd)
                except PhoneCodeInvalidError:
                    self.log("验证码无效。")
                    return False, None

            me = await self.client.get_me()
            info = {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": getattr(me, "phone", ""),
                "session_name": session_name,
            }
            self.log(f"登录成功：{info['phone'] or info['username'] or info['id']}")
            return True, info

        finally:
            if self.client and self.client.is_connected():
                await self.client.disconnect()
    def login_blocking(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_name: str,
        code_getter: Callable[[], str],
        pwd_getter: Optional[Callable[[], str]] = None,
    ) -> Tuple[bool, Optional[dict]]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.login_async(api_id, api_hash, phone, session_name, code_getter, pwd_getter)
            )
        finally:
            loop.close()
