# -*- coding: utf-8 -*-
import tkinter as tk

import customtkinter as ctk


class StrategyTabMixin:
    REPLACEMENT_MODE_LABELS = {
        "literal": "普通文本替换",
        "regex": "正则表达式",
    }
    REPLACEMENT_MODE_VALUES = {label: value for value, label in REPLACEMENT_MODE_LABELS.items()}

    def _mode_to_label(self, mode):
        return self.REPLACEMENT_MODE_LABELS.get((mode or "literal").strip().lower(), "普通文本替换")

    def _label_to_mode(self, label):
        return self.REPLACEMENT_MODE_VALUES.get((label or "").strip(), (label or "literal").strip().lower())

    def _build_strategy_tab(self, tab):
        scroll = self._tab_scroll(tab)

        identity_card = self._content_card(scroll, 0, 0, "身份同步", padx=(0, 4), pady=(0, 4))
        identity_card.grid_columnconfigure(0, weight=1)
        identity_card.grid_columnconfigure(1, weight=1)
        self.var_clone_name = tk.BooleanVar(value=True)
        self.var_clone_avatar = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(identity_card, text="同步昵称", variable=self.var_clone_name, font=self.font_xs).grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 4)
        )
        ctk.CTkCheckBox(identity_card, text="同步头像", variable=self.var_clone_avatar, font=self.font_xs).grid(
            row=1, column=1, sticky="w", padx=10, pady=(0, 4)
        )
        self._form_label(identity_card, 2, 0, "身份切换冷却（秒）", 10)
        self.cooldown = ctk.CTkEntry(identity_card, height=28, placeholder_text="3600", font=self.font_sm)
        self.cooldown.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

        quota_card = self._content_card(scroll, 0, 1, "额度与分片", padx=(4, 0), pady=(0, 4))
        quota_card.grid_columnconfigure(0, weight=1)
        quota_card.grid_columnconfigure(1, weight=1)
        self._form_label(quota_card, 1, 0, "每日克隆上限", 10)
        self._form_label(quota_card, 1, 1, "分片总数", 10)
        self.daily_limit = ctk.CTkEntry(quota_card, height=28, placeholder_text="30", font=self.font_sm)
        self.daily_limit.grid(row=2, column=0, sticky="ew", padx=(10, 5), pady=(0, 4))
        self.shard_total = ctk.CTkEntry(quota_card, height=28, placeholder_text="1", font=self.font_sm)
        self.shard_total.grid(row=2, column=1, sticky="ew", padx=(5, 10), pady=(0, 4))
        self._form_label(quota_card, 3, 0, "当前分片编号", 10)
        self.shard_index = ctk.CTkEntry(quota_card, height=28, placeholder_text="0", font=self.font_sm)
        self.shard_index.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

        throttle_card = self._content_card(scroll, 1, 0, "发送节流", padx=(0, 4), pady=(0, 4))
        throttle_card.grid_columnconfigure(0, weight=1)
        throttle_card.grid_columnconfigure(1, weight=1)
        self._form_label(throttle_card, 1, 0, "最小发送间隔（秒）", 10)
        self._form_label(throttle_card, 1, 1, "最大发送间隔（秒）", 10)
        self.min_interval = ctk.CTkEntry(throttle_card, height=28, placeholder_text="1.0", font=self.font_sm)
        self.min_interval.grid(row=2, column=0, sticky="ew", padx=(10, 5), pady=(0, 8))
        self.max_interval = ctk.CTkEntry(throttle_card, height=28, placeholder_text="3.0", font=self.font_sm)
        self.max_interval.grid(row=2, column=1, sticky="ew", padx=(5, 10), pady=(0, 8))

        replace_mode_card = self._content_card(scroll, 1, 1, "替换模式", padx=(4, 0), pady=(0, 4))
        replace_mode_card.grid_columnconfigure(0, weight=1)
        self.replacement_mode_var = tk.StringVar(value=self._mode_to_label("literal"))
        self._form_label(replace_mode_card, 1, 0, "模式", 10)
        ctk.CTkOptionMenu(
            replace_mode_card,
            values=list(self.REPLACEMENT_MODE_VALUES.keys()),
            variable=self.replacement_mode_var,
            height=28,
            font=self.font_sm,
            dropdown_font=self.font_sm,
        ).grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.var_replacements_case_insensitive = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            replace_mode_card,
            text="忽略大小写",
            variable=self.var_replacements_case_insensitive,
            font=self.font_xs,
        ).grid(row=3, column=0, sticky="w", padx=10, pady=(0, 8))

        adaptive_card = self._content_card(scroll, 2, 0, "自适应节流", columnspan=2, pady=(0, 2))
        adaptive_card.grid_columnconfigure(0, weight=1)
        adaptive_card.grid_columnconfigure(1, weight=1)
        adaptive_card.grid_columnconfigure(2, weight=1)
        self.var_adaptive_throttle = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            adaptive_card,
            text="启用自适应节流",
            variable=self.var_adaptive_throttle,
            command=self._toggle_adaptive_fields,
            font=self.font_xs,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 4))
        self._form_label(adaptive_card, 2, 0, "成功衰减", 10)
        self._form_label(adaptive_card, 2, 1, "FloodWait 惩罚", 10)
        self._form_label(adaptive_card, 2, 2, "最大间隔上限", 10)
        self.adaptive_decay = ctk.CTkEntry(adaptive_card, height=28, placeholder_text="0.85", font=self.font_sm)
        self.adaptive_decay.grid(row=3, column=0, sticky="ew", padx=(10, 5), pady=(0, 8))
        self.adaptive_penalty = ctk.CTkEntry(adaptive_card, height=28, placeholder_text="1.25", font=self.font_sm)
        self.adaptive_penalty.grid(row=3, column=1, sticky="ew", padx=5, pady=(0, 8))
        self.adaptive_cap = ctk.CTkEntry(adaptive_card, height=28, placeholder_text="30.0", font=self.font_sm)
        self.adaptive_cap.grid(row=3, column=2, sticky="ew", padx=(5, 10), pady=(0, 8))

    def _toggle_adaptive_fields(self):
        state = "normal" if self.var_adaptive_throttle.get() else "disabled"
        for widget in (self.adaptive_decay, self.adaptive_penalty, self.adaptive_cap):
            widget.configure(state=state)
