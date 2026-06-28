#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简易账号管理器（可与 UI 结合，不依赖 UI）
- 统一保存/删除 session
- 批量初始化登录（需要配合 telegram_login 的回调）
"""

import os
from typing import Callable, Optional, Dict, Any
from .telegram_login import TelegramLogin


class AccountManager:
    def __init__(self, sessions_dir="sessions", logger: Optional[Callable[[str], None]] = None, parent_window=None):
        self.sessions_dir = sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.log = logger or print
        self.parent_window = parent_window
        self.accounts: Dict[str, Dict[str, Any]] = {}  # key: session_name -> info

    def add_account(self, session_name: str, api_id: int, api_hash: str, phone: str):
        """
        注册一个账号记录（未必已登录）
        """
        path = os.path.join(self.sessions_dir, session_name)
        self.accounts[session_name] = {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "session_path": path,
        }
        return session_name

    def remove_account(self, session_name: str):
        self.accounts.pop(session_name, None)
        # 不主动删 session 文件，避免误删，可按需补充

    def login_account(self, session_name: str, code_getter, pwd_getter) -> bool:
        """
        交互式登录，生成/更新 session
        """
        info = self.accounts.get(session_name)
        if not info:
            self.log(f"{session_name} 不存在")
            return False

        login = TelegramLogin(parent_window=self.parent_window, log_callback=self.log)
        ok, _ = login.login_blocking(
            api_id=info["api_id"],
            api_hash=info["api_hash"],
            phone=info["phone"],
            session_name=info["session_path"],
            code_getter=code_getter,
            pwd_getter=pwd_getter,
        )
        if ok:
            self.log(f"{session_name} 登录完成。")
        else:
            self.log(f"{session_name} 登录失败。")
        return ok
