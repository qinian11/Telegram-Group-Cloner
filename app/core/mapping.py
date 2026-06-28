#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import random
from typing import Any, Dict, Optional, Tuple


class MappingMixin:
    def _load_message_map(self):
        os.makedirs("cache", exist_ok=True)
        if not os.path.exists(self.message_map_path):
            return
        try:
            with open(self.message_map_path, "r", encoding="utf-8") as file:
                items = json.load(file)
        except Exception as exc:
            self.log(f"读取消息映射失败，已忽略损坏缓存：{exc}")
            self.message_id_mapping = {}
            return

        mapping = {}
        for item in items:
            try:
                key = (int(item.get("source_chat_id")), int(item.get("source_message_id")))
                target_message_id = int(item.get("target_message_id"))
                poster_phone = item.get("poster_phone") or None
                mapping[key] = (target_message_id, poster_phone)
            except Exception:
                continue
        self.message_id_mapping = mapping

    def _save_message_map(self):
        os.makedirs("cache", exist_ok=True)
        items = []
        for (source_chat_id, source_message_id), value in self.message_id_mapping.items():
            target_message_id, poster_phone = self._normalize_mapping_value(value)
            if target_message_id is None:
                continue
            items.append({
                "source_chat_id": source_chat_id,
                "source_message_id": source_message_id,
                "target_message_id": target_message_id,
                "poster_phone": poster_phone,
            })
        with open(self.message_map_path, "w", encoding="utf-8") as file:
            json.dump(items, file, ensure_ascii=False)

    def _normalize_mapping_value(self, value) -> Tuple[Optional[int], Optional[str]]:
        try:
            if isinstance(value, tuple):
                target_message_id, poster_phone = value
            else:
                target_message_id, poster_phone = value, None
            return int(target_message_id), poster_phone or None
        except Exception:
            return None, None

    def _get_target_mapping(self, source_chat_id: int, source_message_id: int):
        value = self.message_id_mapping.get((source_chat_id, source_message_id))
        if value is None:
            return None
        target_message_id, poster_phone = self._normalize_mapping_value(value)
        if target_message_id is None:
            return None
        return target_message_id, poster_phone

    def _set_target_mapping(self, source_chat_id: int, source_message_id: int, target_message_id: int, poster_phone=None):
        try:
            key = (int(source_chat_id), int(source_message_id))
            target_id = int(target_message_id)
        except Exception:
            return False
        self.message_id_mapping[key] = (target_id, poster_phone or None)
        self._mark_message_map_dirty()
        return True

    def _remove_target_mapping(self, source_chat_id: int, source_message_id: int):
        try:
            key = (int(source_chat_id), int(source_message_id))
        except Exception:
            return False
        if key not in self.message_id_mapping:
            return False
        self.message_id_mapping.pop(key, None)
        self._mark_message_map_dirty(save_every=1)
        return True

    def _mark_message_map_dirty(self, save_every=50):
        self.message_map_dirty_count += 1
        if self.message_map_dirty_count >= save_every:
            self._save_message_map()
            self.message_map_dirty_count = 0

    def _is_missing_target_message_error(self, error: Exception) -> bool:
        text = str(error).lower()
        name = error.__class__.__name__.lower()
        return any(marker in text or marker in name for marker in (
            "message_id_invalid",
            "messageidinvalid",
            "message not found",
            "not found",
            "deleted",
        ))

    def _get_target_gap(self, meta: Dict[str, Any]) -> float:
        if not self.adaptive_throttle:
            return random.uniform(self.min_send_interval, self.max_send_interval)
        amin = float(meta.get("adaptive_min", self.min_send_interval))
        amax = float(meta.get("adaptive_max", self.max_send_interval))
        amin = max(self.min_send_interval, min(amin, self.adaptive_cap))
        amax = max(amin, min(amax, self.adaptive_cap))
        return random.uniform(amin, amax)

    def _apply_success_decay(self, meta: Dict[str, Any]):
        if not self.adaptive_throttle:
            return
        amin = float(meta.get("adaptive_min", self.min_send_interval))
        amax = float(meta.get("adaptive_max", self.max_send_interval))
        amin = max(self.min_send_interval, amin * self.adaptive_decay)
        amax = max(amin, amax * self.adaptive_decay)
        amin = max(self.min_send_interval, amin)
        amax = min(self.adaptive_cap, max(amin, amax))
        meta["adaptive_min"] = amin
        meta["adaptive_max"] = amax

    def _apply_flood_penalty(self, meta: Dict[str, Any], wait_seconds: int):
        if not self.adaptive_throttle:
            return
        amin = float(meta.get("adaptive_min", self.min_send_interval))
        amax = float(meta.get("adaptive_max", self.max_send_interval))
        base_min = max(self.min_send_interval, wait_seconds + 1)
        amin = max(base_min, amin * self.adaptive_penalty)
        amax = max(amin + 0.5, amax * self.adaptive_penalty)
        amin = min(amin, self.adaptive_cap)
        amax = min(max(amin, amax), self.adaptive_cap)
        meta["adaptive_min"] = amin
        meta["adaptive_max"] = amax
