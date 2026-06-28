#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#TG: @hy499

import asyncio
import os
from typing import Any, Dict, Optional, Tuple

from telethon import TelegramClient

from .forwarding import ForwardingMixin
from .mapping import MappingMixin
from .monitor import MonitorMixin
from .pool import PoolMixin
from .session import SessionMixin


class ClonerLogic(SessionMixin, MonitorMixin, ForwardingMixin, PoolMixin, MappingMixin):

    def __init__(self, config, logger_callback):
        self.config = config
        self.log = logger_callback
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.monitor_client: Optional[TelegramClient] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.clients_pool: Dict[TelegramClient, Dict[str, Any]] = {}
        self.client_locks: Dict[TelegramClient, asyncio.Lock] = {}
        self.sender_locks: Dict[int, asyncio.Lock] = {}
        self.message_id_mapping: Dict[Tuple[int, int], int] = {}
        self.is_monitoring = False

        self.message_map_path = os.path.join("cache", "message_map.json")
        self.message_map_dirty_count = 0
        self.profile_cache: Dict[int, Tuple[str, str, Optional[int]]] = {}
        self.sessions_dir = "sessions"
        self.sessions_banned_dir = "sessions_banned"

        self.source_groups = []
        self.target_group = ""
        self.blacklist_users = set()
        self.blacklist_keywords = set()
        self.replacements = {}
        self.replacements_mode = "literal"
        self.replacements_case_insensitive = False
        self._replacement_rules = []

        self.clone_name_enabled = True
        self.clone_avatar_enabled = True
        self.daily_clone_limit = 30
        self.identity_cooldown_sec = 3600
        self.min_send_interval = 1.0
        self.max_send_interval = 3.0
        self.adaptive_throttle = True
        self.adaptive_decay = 0.85
        self.adaptive_penalty = 1.25
        self.adaptive_cap = 30.0

        self.shard_total = 1
        self.shard_index = 0
        self.total_messages_forwarded = 0
        self._shutdown_in_progress = False
