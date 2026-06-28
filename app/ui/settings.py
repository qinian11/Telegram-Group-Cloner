# -*- coding: utf-8 -*-
import os
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk


class SettingsTabMixin:
    def _build_settings_tab(self, tab):
        scroll = self._tab_scroll(tab)

        api_card = self._content_card(scroll, 0, 0, "Telegram API", padx=(0, 4), pady=(0, 4))
        api_card.grid_columnconfigure(0, weight=1)
        api_card.grid_columnconfigure(1, weight=1)
        self._form_label(api_card, 1, 0, "API ID", 10)
        self._form_label(api_card, 1, 1, "API Hash", 10)
        self.api_id = ctk.CTkEntry(api_card, height=28, placeholder_text="12345678", font=self.font_sm)
        self.api_id.grid(row=2, column=0, sticky="ew", padx=(10, 5), pady=(0, 4))
        self.api_hash = ctk.CTkEntry(api_card, height=28, placeholder_text="Telegram API Hash", show="*", font=self.font_sm)
        self.api_hash.grid(row=2, column=1, sticky="ew", padx=(5, 10), pady=(0, 4))
        self._form_label(api_card, 3, 0, "监听账号手机号", 10)
        self.monitor_phone = ctk.CTkEntry(api_card, height=28, placeholder_text="+8613800000000", font=self.font_sm)
        self.monitor_phone.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

        proxy_card = self._content_card(scroll, 0, 1, "代理配置", padx=(4, 0), pady=(0, 4))
        proxy_card.grid_columnconfigure(0, weight=1)
        proxy_card.grid_columnconfigure(1, weight=1)
        self.var_proxy_enabled = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            proxy_card,
            text="启用代理",
            variable=self.var_proxy_enabled,
            command=self._toggle_proxy_fields,
            font=self.font_xs,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))
        self._form_label(proxy_card, 2, 0, "代理类型", 10)
        self._form_label(proxy_card, 2, 1, "代理端口", 10)
        self.proxy_type = ctk.CTkEntry(proxy_card, height=28, placeholder_text="socks5", font=self.font_sm)
        self.proxy_type.grid(row=3, column=0, sticky="ew", padx=(10, 5), pady=(0, 4))
        self.proxy_port = ctk.CTkEntry(proxy_card, height=28, placeholder_text="7890", font=self.font_sm)
        self.proxy_port.grid(row=3, column=1, sticky="ew", padx=(5, 10), pady=(0, 4))
        self._form_label(proxy_card, 4, 0, "代理主机", 10)
        self.proxy_host = ctk.CTkEntry(proxy_card, height=28, placeholder_text="127.0.0.1", font=self.font_sm)
        self.proxy_host.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

        group_card = self._content_card(scroll, 1, 0, "群组配置", padx=(0, 4), pady=(0, 4))
        group_card.grid_columnconfigure(0, weight=1)
        self._form_label(group_card, 1, 0, "源群组，多个用英文逗号分隔", 10)
        self.source_groups = ctk.CTkEntry(group_card, height=28, placeholder_text="https://t.me/a, @group_b", font=self.font_sm)
        self.source_groups.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._form_label(group_card, 3, 0, "目标群组", 10)
        self.target_group = ctk.CTkEntry(group_card, height=28, placeholder_text="https://t.me/target", font=self.font_sm)
        self.target_group.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))

        filter_card = self._content_card(scroll, 1, 1, "过滤配置", padx=(4, 0), pady=(0, 4))
        filter_card.grid_columnconfigure(0, weight=1)
        self._form_label(filter_card, 1, 0, "黑名单用户 ID，多个用英文逗号分隔", 10)
        self.black_users = ctk.CTkEntry(filter_card, height=28, placeholder_text="12345,67890", font=self.font_sm)
        self.black_users.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._form_label(filter_card, 3, 0, "黑名单关键词，多个用英文逗号分隔", 10)
        self.black_words = ctk.CTkEntry(filter_card, height=28, placeholder_text="广告, 兼职, 推广", font=self.font_sm)
        self.black_words.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 8))

        replace_card = self._content_card(scroll, 2, 0, "替换规则", columnspan=2, pady=(0, 2))
        self.replacements = ctk.CTkTextbox(replace_card, height=96, corner_radius=10, font=self.font_sm)
        self.replacements.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

    def _toggle_proxy_fields(self):
        state = "normal" if self.var_proxy_enabled.get() else "disabled"
        self.proxy_type.configure(state=state)
        self.proxy_host.configure(state=state)
        self.proxy_port.configure(state=state)

    def _set_entry_value(self, entry, value):
        entry.delete(0, tk.END)
        if value is not None:
            entry.insert(0, str(value))

    def _set_text_value(self, textbox, value):
        textbox.delete("1.0", tk.END)
        if value:
            textbox.insert("1.0", value)

    def _split_csv(self, value):
        return [item.strip() for item in (value or "").split(",") if item.strip()]

    def _normalize_replacements(self):
        lines = []
        for line in self.replacements.get("1.0", tk.END).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                left, right = stripped.split("=", 1)
                lines.append(f"{left.strip()}={right.strip()}")
        return lines

    def _load_settings(self):
        self._set_entry_value(self.api_id, self.config_obj.get("telegram", "api_id", fallback=""))
        self._set_entry_value(self.api_hash, self.config_obj.get("telegram", "api_hash", fallback=""))
        self._set_entry_value(self.monitor_phone, self.config_obj.get("telegram", "monitor_phone", fallback=""))
        self._set_entry_value(self.source_groups, self.config_obj.get("telegram", "source_group", fallback=""))
        self._set_entry_value(self.target_group, self.config_obj.get("telegram", "target_group", fallback=""))
        self._set_entry_value(self.black_users, self.config_obj.get("blacklist", "user_ids", fallback=""))
        self._set_entry_value(self.black_words, self.config_obj.get("blacklist", "keywords", fallback=""))

        self.var_proxy_enabled.set(self.config_obj.getboolean("proxy", "is_enabled", fallback=False))
        self._set_entry_value(self.proxy_type, self.config_obj.get("proxy", "type", fallback="socks5"))
        self._set_entry_value(self.proxy_host, self.config_obj.get("proxy", "host", fallback="127.0.0.1"))
        self._set_entry_value(self.proxy_port, self.config_obj.getint("proxy", "port", fallback=7890))
        self._toggle_proxy_fields()

        lines = []
        if self.config_obj.config.has_section("replacements"):
            for key, value in self.config_obj.config.items("replacements"):
                if key.strip():
                    lines.append(f"{key}={value}")
        self._set_text_value(self.replacements, "\n".join(lines))

        self.var_clone_name.set(self.config_obj.getboolean("strategy", "clone_name", fallback=True))
        self.var_clone_avatar.set(self.config_obj.getboolean("strategy", "clone_avatar", fallback=True))
        self._set_entry_value(self.daily_limit, self.config_obj.getint("strategy", "daily_clone_limit", fallback=30))
        self._set_entry_value(self.cooldown, self.config_obj.getint("strategy", "identity_cooldown_sec", fallback=3600))
        self._set_entry_value(self.min_interval, self.config_obj.getfloat("strategy", "min_send_interval", fallback=1.0))
        self._set_entry_value(self.max_interval, self.config_obj.getfloat("strategy", "max_send_interval", fallback=3.0))
        self.replacement_mode_var.set(self._mode_to_label(self.config_obj.get("strategy", "replacements_mode", fallback="literal")))
        self.var_replacements_case_insensitive.set(
            self.config_obj.getboolean("strategy", "replacements_case_insensitive", fallback=False)
        )
        self.var_adaptive_throttle.set(self.config_obj.getboolean("strategy", "adaptive_throttle", fallback=True))
        self._set_entry_value(self.adaptive_decay, self.config_obj.getfloat("strategy", "adaptive_decay", fallback=0.85))
        self._set_entry_value(self.adaptive_penalty, self.config_obj.getfloat("strategy", "adaptive_penalty", fallback=1.25))
        self._set_entry_value(self.adaptive_cap, self.config_obj.getfloat("strategy", "adaptive_cap", fallback=30.0))
        self._set_entry_value(self.shard_total, self.config_obj.getint("strategy", "shard_total", fallback=1))
        self._set_entry_value(self.shard_index, self.config_obj.getint("strategy", "shard_index", fallback=0))
        self._toggle_adaptive_fields()

    def _validate_settings(self):
        errors = []
        api_id = self.api_id.get().strip()
        if not api_id:
            errors.append("API ID 不能为空")
        elif not api_id.isdigit():
            errors.append("API ID 必须是数字")
        if not self.api_hash.get().strip():
            errors.append("API Hash 不能为空")
        if not self._split_csv(self.source_groups.get().strip()):
            errors.append("至少需要填写 1 个源群组")
        if not self.target_group.get().strip():
            errors.append("目标群组不能为空")

        phone = self.monitor_phone.get().strip()
        monitor_session_exists = os.path.exists(os.path.join("sessions", "monitor.session"))
        if not phone and not monitor_session_exists:
            errors.append("首次使用需要填写监听账号手机号")
        elif phone and not phone.startswith("+"):
            errors.append("手机号必须以 + 开头")

        black_users = [item.strip() for item in self.black_users.get().split(",") if item.strip()]
        if any(not item.isdigit() for item in black_users):
            errors.append("黑名单用户 ID 只能包含数字和英文逗号")

        if self.var_proxy_enabled.get():
            if not self.proxy_type.get().strip():
                errors.append("启用代理后必须填写代理类型")
            if not self.proxy_host.get().strip():
                errors.append("启用代理后必须填写代理主机")
            try:
                port = int(self.proxy_port.get().strip())
                if port < 1 or port > 65535:
                    errors.append("代理端口必须在 1-65535 之间")
            except Exception:
                errors.append("代理端口必须是数字")

        numeric_checks = [
            ("每日克隆上限", self.daily_limit.get().strip() or "30", int, lambda value: value >= 1),
            ("身份切换冷却时间", self.cooldown.get().strip() or "3600", int, lambda value: value >= 0),
            ("最小发送间隔", self.min_interval.get().strip() or "1.0", float, lambda value: value >= 0),
            ("最大发送间隔", self.max_interval.get().strip() or "3.0", float, lambda value: value >= 0),
            ("分片总数", self.shard_total.get().strip() or "1", int, lambda value: value >= 1),
            ("分片编号", self.shard_index.get().strip() or "0", int, lambda value: value >= 0),
        ]
        parsed = {}
        for label, raw, parser, validator in numeric_checks:
            try:
                value = parser(raw)
                parsed[label] = value
                if not validator(value):
                    errors.append(f"{label} 不合法")
            except Exception:
                errors.append(f"{label} 必须是数字")
        if parsed.get("最小发送间隔", 0) > parsed.get("最大发送间隔", 0):
            errors.append("最小发送间隔不能大于最大发送间隔")
        if parsed.get("分片编号", 0) >= parsed.get("分片总数", 1):
            errors.append("分片编号必须小于分片总数")

        mode = self._label_to_mode(self.replacement_mode_var.get())
        if mode not in {"literal", "regex"}:
            errors.append("替换模式必须是普通文本替换或正则表达式")

        if self.var_adaptive_throttle.get():
            try:
                decay = float(self.adaptive_decay.get().strip() or "0.85")
                if not 0 < decay <= 1:
                    errors.append("自适应衰减必须大于 0 且小于等于 1")
            except Exception:
                errors.append("自适应衰减必须是数字")
            try:
                penalty = float(self.adaptive_penalty.get().strip() or "1.25")
                if penalty < 1:
                    errors.append("FloodWait 惩罚倍率不能小于 1")
            except Exception:
                errors.append("FloodWait 惩罚倍率必须是数字")
            try:
                cap = float(self.adaptive_cap.get().strip() or "30.0")
                if cap <= 0:
                    errors.append("自适应上限必须大于 0")
            except Exception:
                errors.append("自适应上限必须是数字")

        for index, line in enumerate(self.replacements.get("1.0", tk.END).splitlines(), start=1):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" not in stripped:
                errors.append(f"替换规则第 {index} 行缺少 =")
        return errors

    def _save_settings(self, show_dialog=True):
        errors = self._validate_settings()
        if errors:
            error_msg = "配置校验失败：\n" + "\n".join(f"- {item}" for item in errors)
            self.log(error_msg, level="ERROR")
            if show_dialog:
                messagebox.showerror("配置校验", error_msg)
            return False

        self.config_obj.set("telegram", "api_id", self.api_id.get().strip())
        self.config_obj.set("telegram", "api_hash", self.api_hash.get().strip())
        self.config_obj.set("telegram", "monitor_phone", self.monitor_phone.get().strip())
        self.config_obj.set("telegram", "source_group", ", ".join(self._split_csv(self.source_groups.get().strip())))
        self.config_obj.set("telegram", "target_group", self.target_group.get().strip())
        self.config_obj.set("proxy", "is_enabled", str(self.var_proxy_enabled.get()).lower())
        self.config_obj.set("proxy", "type", self.proxy_type.get().strip() or "socks5")
        self.config_obj.set("proxy", "host", self.proxy_host.get().strip() or "127.0.0.1")
        self.config_obj.set("proxy", "port", self.proxy_port.get().strip() or "7890")
        self.config_obj.set("blacklist", "user_ids", self.black_users.get().strip())
        self.config_obj.set("blacklist", "keywords", self.black_words.get().strip())

        if self.config_obj.config.has_section("replacements"):
            self.config_obj.config.remove_section("replacements")
        self.config_obj.config.add_section("replacements")
        for line in self._normalize_replacements():
            left, right = line.split("=", 1)
            self.config_obj.set("replacements", left.strip(), right.strip())

        self.config_obj.set("strategy", "clone_name", str(self.var_clone_name.get()).lower())
        self.config_obj.set("strategy", "clone_avatar", str(self.var_clone_avatar.get()).lower())
        self.config_obj.set("strategy", "daily_clone_limit", self.daily_limit.get().strip() or "30")
        self.config_obj.set("strategy", "identity_cooldown_sec", self.cooldown.get().strip() or "3600")
        self.config_obj.set("strategy", "min_send_interval", self.min_interval.get().strip() or "1.0")
        self.config_obj.set("strategy", "max_send_interval", self.max_interval.get().strip() or "3.0")
        self.config_obj.set("strategy", "replacements_mode", self._label_to_mode(self.replacement_mode_var.get()) or "literal")
        self.config_obj.set(
            "strategy",
            "replacements_case_insensitive",
            str(self.var_replacements_case_insensitive.get()).lower(),
        )
        self.config_obj.set("strategy", "adaptive_throttle", str(self.var_adaptive_throttle.get()).lower())
        self.config_obj.set("strategy", "adaptive_decay", self.adaptive_decay.get().strip() or "0.85")
        self.config_obj.set("strategy", "adaptive_penalty", self.adaptive_penalty.get().strip() or "1.25")
        self.config_obj.set("strategy", "adaptive_cap", self.adaptive_cap.get().strip() or "30.0")
        self.config_obj.set("strategy", "shard_total", self.shard_total.get().strip() or "1")
        self.config_obj.set("strategy", "shard_index", self.shard_index.get().strip() or "0")
        self.config_obj.save_config()
        self._refresh_config_summary()
        self.log("配置已保存。", level="SUCCESS")
        if self.cloner.is_monitoring:
            self.log("监听正在运行，新配置会在下次启动或批量操作时生效。", level="WARNING")
        return True

    def _validate_only(self):
        errors = self._validate_settings()
        if errors:
            messagebox.showerror("配置校验", "\n".join(f"- {item}" for item in errors))
            return
        messagebox.showinfo("配置校验", "当前配置校验通过，可以开始使用。")

    def _build_config_summary(self):
        source_groups = self._split_csv(self.source_groups.get().strip())
        target_group = self.target_group.get().strip() or "未设置"
        proxy_text = "开启" if self.var_proxy_enabled.get() else "关闭"
        replacement_mode = self._mode_to_label(self._label_to_mode(self.replacement_mode_var.get()))
        replacement_lines = len(self._normalize_replacements())
        clone_name = "开启" if self.var_clone_name.get() else "关闭"
        clone_avatar = "开启" if self.var_clone_avatar.get() else "关闭"
        return (
            f"源群数量：{len(source_groups)} 个\n"
            f"目标群组：{target_group}\n"
            f"代理状态：{proxy_text}\n"
            f"替换模式：{replacement_mode} / 规则数：{replacement_lines}\n"
            f"昵称同步：{clone_name}，头像同步：{clone_avatar}\n"
            f"分片：{self.shard_index.get().strip() or '0'} / {self.shard_total.get().strip() or '1'}"
        )

    def _refresh_config_summary(self):
        summary = self._build_config_summary()
        if self.overview_config_label is not None:
            self.overview_config_label.configure(text=summary)
