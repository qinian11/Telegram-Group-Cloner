# -*- coding: utf-8 -*-
import asyncio
import contextlib
import os
import sys
import threading
import time
from datetime import datetime
from tkinter import messagebox, ttk
import tkinter as tk

import customtkinter as ctk

from ..config.app_config import Config
from ..core.cloner import ClonerLogic
from . import components as ui
from .dialogs import CustomInputDialog
from .log import LogMixin
from .pool import PoolTabMixin
from .settings import SettingsTabMixin
from .strategy import StrategyTabMixin
from .styles import STATUS_STYLE
from .theme import DesignTokens as T


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AppUI(SettingsTabMixin, StrategyTabMixin, PoolTabMixin, LogMixin, ctk.CTk):
    """Fluent 风格桌面控制台外壳，业务逻辑仍通过现有 mixin 方法执行。"""

    PAGE_META = {
        "overview": ("总览", "查看运行状态、账号健康度和当前转发任务"),
        "groups": ("群组配置", "配置 Telegram API、代理、源群、目标群和过滤规则"),
        "strategy": ("转发策略", "调整身份同步、额度分片、发送节流和替换模式"),
        "accounts": ("账号池", "管理监听账号、克隆账号、Session 状态和批量操作"),
        "settings": ("设置", "管理外观、日志和文件目录"),
        "about": ("关于", "查看应用信息、运行环境和合规提醒"),
    }

    NAV_ITEMS = [
        ("overview", "OV", "总览"),
        ("groups", "GR", "群组配置"),
        ("strategy", "ST", "转发策略"),
        ("accounts", "AC", "账号池"),
        ("settings", "SE", "设置"),
        ("about", "IN", "关于"),
    ]

    def __init__(self):
        super().__init__()
        self.title("作者TG：@hy499 小卡拉米")
        self.geometry("1050x650")
        self.minsize(760, 480)

        try:
            if os.path.exists("icon.ico"):
                self.iconbitmap("icon.ico")
        except Exception:
            pass

        self.font_xs = T.font(12)
        self.font_sm = T.font(13)
        self.font_md = T.font(14, "bold")
        self.font_lg = T.font(18, "bold")
        self.font_xl = T.font(23, "bold")

        self.config_obj = Config()
        self.cloner = ClonerLogic(self.config_obj, self.log)
        self.asyncio_thread = threading.Thread(target=self._start_loop, daemon=True)
        self.asyncio_thread.start()

        self.is_running = False
        self._theme_switching = False
        self._monitor_state = "idle"
        self._pool_refresh_job = None
        self._stats_refresh_job = None
        self._closing = False
        self._shutdown_future = None
        self._shutdown_deadline = 0.0

        self.selected_page = "overview"
        self.sidebar_collapsed = False
        self.config_dirty = False
        self.config_valid = False
        self.loading_action = None
        self.log_panel_collapsed = False
        self.log_panel_maximized = False
        self.log_panel_height = self.config_obj.getint("ui", "log_panel_height", fallback=T.log_default_height)
        self.log_autoscroll_var = tk.BooleanVar(value=True)
        self.log_level_var = tk.StringVar(value="ALL")
        self.log_search_var = tk.StringVar()
        self.pool_filter_var = tk.StringVar()
        self.theme_mode = tk.StringVar(value=ctk.get_appearance_mode().lower())

        self.stat_value_labels = {}
        self.nav_buttons = {}
        self.page_frames = {}
        self.page_title_label = None
        self.page_desc_label = None
        self.sidebar = None
        self.sidebar_title = None
        self.sidebar_version = None
        self.main_action_btn = None
        self.status_badge = None
        self.validation_panel = None
        self.toast = None
        self.log_text = None
        self.log_count_label = None
        self.log_container = None
        self.log_body = None
        self.log_grip = None
        self.log_header = None
        self.log_collapsed_btn = None
        self.content_host = None
        self.stats_label = None
        self.overview_config_label = None
        self.sidebar_context_label = None
        self.pool_summary_label = None
        self.start_btn = None
        self.stop_btn = None
        self.dashboard_start_btn = None
        self.dashboard_stop_btn = None
        self.sidebar_status_badge = None
        self.sidebar_status_hint = None
        self.overview_status_badge = None
        self.overview_status_hint = None
        self.workdir_btn = None
        self.sidebar_toggle_btn = None
        self.theme_buttons = {}

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._build_ui()
        self._load_settings()
        self._mark_clean()
        self._refresh_config_summary()
        self._set_monitoring_state("idle")
        self._refresh_pool_view(schedule_next=False)
        self._refresh_stats(schedule_next=False)
        self._schedule_pool_refresh()
        self._schedule_stats_refresh()
        self.pool_filter_var.trace_add("write", lambda *_: self._refresh_pool_view(schedule_next=False))

    def _start_loop(self):
        asyncio.set_event_loop(self.cloner.loop)
        self.cloner.loop.run_forever()

    def _ui_alive(self):
        if self._closing:
            return False
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _build_ui(self):
        colors = T.colors()
        self.configure(fg_color=colors["app_bg"])
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        shell = ctk.CTkFrame(self, fg_color=colors["app_bg"], corner_radius=0)
        shell.grid(row=0, column=1, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_columnconfigure(1, weight=0)
        shell.grid_rowconfigure(1, weight=1)

        self._build_topbar(shell)
        self._build_content(shell)
        self._build_log_panel(shell)
        self.toast = ui.Toast(self)
        self._show_page("overview")

    def _build_sidebar(self):
        colors = T.colors()
        self.sidebar = ctk.CTkFrame(self, width=T.sidebar_width, fg_color=colors["sidebar_bg"], corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=T.space_4, pady=(T.space_4, T.space_2))
        brand.grid_columnconfigure(0, weight=1)
        self.sidebar_title = ctk.CTkLabel(brand, text="控制台", font=T.font(16, "bold"), text_color=colors["text_primary"])
        self.sidebar_title.grid(row=0, column=0, sticky="w")
        self.sidebar_version = ctk.CTkLabel(brand, text="桌面运营控制台 v1.0", font=T.font(12), text_color=colors["text_muted"])
        self.sidebar_version.grid(row=1, column=0, sticky="w", pady=(2, 0))

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="new", padx=T.space_2, pady=(T.space_2, 0))
        nav.grid_columnconfigure(0, weight=1)
        for index, (key, icon, text) in enumerate(self.NAV_ITEMS):
            item = ctk.CTkFrame(nav, fg_color="transparent", corner_radius=T.radius_sm, height=T.nav_h)
            item.grid(row=index, column=0, sticky="ew", pady=(0, T.space_1))
            item.grid_propagate(False)
            item.grid_rowconfigure(0, weight=1)
            item.grid_columnconfigure(2, weight=1)
            indicator = ctk.CTkFrame(item, width=3, corner_radius=2, fg_color="transparent")
            indicator.grid(row=0, column=0, sticky="nsw", pady=7)
            icon_label = ctk.CTkLabel(item, text=icon, width=36, font=T.font(13, "bold"), text_color=colors["text_muted"])
            icon_label.grid(row=0, column=1, sticky="nsw", padx=(8, 0))
            label = ctk.CTkLabel(item, text=text, width=92, anchor="w", font=T.font(13), text_color=colors["text_secondary"])
            label.grid(row=0, column=2, sticky="nsew", padx=(6, 10))
            for widget in (item, icon_label, label):
                widget.bind("<Button-1>", lambda _e, page=key: self._show_page(page))
                widget.bind("<Enter>", lambda _e, frame=item: frame.configure(fg_color=T.colors()["surface_2"]))
                widget.bind("<Leave>", lambda _e, page=key, frame=item: self._paint_nav_item(page))
            ui.Tooltip(item, text)
            self.nav_buttons[key] = (item, indicator, icon_label, label)

        bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=T.space_2, pady=T.space_2)
        bottom.grid_columnconfigure(0, weight=1)
        self.workdir_btn = ui.button(bottom, "打开工作目录", self._open_workdir, "ghost", height=32)
        self.workdir_btn.grid(row=0, column=0, sticky="ew", pady=(0, T.space_1))
        self._build_sidebar_theme_buttons(bottom)
        self.sidebar_toggle_btn = ui.button(bottom, "收起侧边栏", self._toggle_sidebar, "secondary", height=32)
        self.sidebar_toggle_btn.grid(row=4, column=0, sticky="ew", pady=(T.space_1, 0))

    def _build_sidebar_theme_buttons(self, parent):
        labels = [("light", "浅色", "亮"), ("dark", "深色", "暗"), ("system", "跟随系统", "系")]
        for row, (mode, full_text, short_text) in enumerate(labels, start=1):
            button = ui.button(
                parent,
                full_text,
                lambda selected=mode: self._switch_theme(selected),
                "secondary",
                height=30,
            )
            button.grid(row=row, column=0, sticky="ew", pady=(0, T.space_1))
            ui.Tooltip(button, full_text)
            self.theme_buttons[mode] = (button, full_text, short_text)
        self._paint_theme_buttons()

    def _build_topbar(self, parent):
        colors = T.colors()
        top = ctk.CTkFrame(parent, height=T.topbar_height, fg_color=colors["app_bg"], corner_radius=0)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=T.space_5, pady=(T.space_2, 0))
        top.grid_propagate(False)
        top.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        self.page_title_label = ctk.CTkLabel(title_box, text="", font=T.font(23, "bold"), text_color=colors["text_primary"])
        self.page_title_label.grid(row=0, column=0, sticky="w")
        self.page_desc_label = ctk.CTkLabel(title_box, text="", font=T.font(13), text_color=colors["text_secondary"])
        self.page_desc_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.status_badge = ui.badge(actions, "● 待命", "muted")
        self.status_badge.grid(row=0, column=0, padx=(0, T.space_2))
        ui.button(actions, "校验配置", self._validate_and_show, "secondary", width=96).grid(row=0, column=1, padx=(0, T.space_2))
        self.main_action_btn = ui.button(actions, "开始监听", self._toggle_monitoring, "primary", width=112)
        self.main_action_btn.grid(row=0, column=2)

    def _build_content(self, parent):
        colors = T.colors()
        self.content_host = ctk.CTkFrame(parent, fg_color=colors["app_bg"], corner_radius=0)
        self.content_host.grid(row=1, column=0, sticky="nsew", padx=(T.space_5, T.space_2), pady=(T.space_3, T.space_3))
        self.content_host.grid_columnconfigure(0, weight=1)
        self.content_host.grid_rowconfigure(0, weight=1)
        for key in self.PAGE_META:
            page = ctk.CTkScrollableFrame(self.content_host, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_forget()
            page.grid_columnconfigure(0, weight=1)
            page.grid_columnconfigure(1, weight=1)
            self.page_frames[key] = page
        self._build_overview_page(self.page_frames["overview"])
        self._build_group_config_page(self.page_frames["groups"])
        self._build_strategy_page(self.page_frames["strategy"])
        self._build_accounts_page(self.page_frames["accounts"])
        self._build_settings_page(self.page_frames["settings"])
        self._build_about_page(self.page_frames["about"])

    def _build_log_panel(self, parent):
        colors = T.colors()
        width = T.log_side_collapsed_width if self.log_panel_collapsed else T.log_side_width
        self.log_container = ctk.CTkFrame(parent, width=width, fg_color=colors["surface_1"], corner_radius=T.radius_lg, border_width=1, border_color=colors["border"])
        self.log_container.grid(row=1, column=1, sticky="nsew", padx=(T.space_2, T.space_5), pady=(T.space_3, T.space_3))
        self.log_container.grid_propagate(False)
        self.log_container.grid_columnconfigure(0, weight=1)
        self.log_container.grid_rowconfigure(3, weight=1)

        self.log_grip = ctk.CTkFrame(self.log_container, width=6, fg_color=colors["surface_2"], corner_radius=4)
        self.log_grip.grid(row=0, column=0, rowspan=4, sticky="nsw", padx=(T.space_1, 0), pady=T.space_3)
        self.log_grip.bind("<B1-Motion>", self._resize_log_panel)

        self.log_header = ctk.CTkFrame(self.log_container, height=74, fg_color="transparent")
        self.log_header.grid(row=1, column=0, sticky="ew", padx=(T.space_3 + 6, T.space_3), pady=(T.space_2, 0))
        self.log_header.grid_propagate(False)
        self.log_header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.log_header, text="运行日志", font=T.font(15, "bold"), text_color=colors["text_primary"]).grid(row=0, column=0, sticky="w")
        self.log_count_label = ctk.CTkLabel(self.log_header, text="0 行", font=T.font(12), text_color=colors["text_muted"])
        self.log_count_label.grid(row=0, column=1, sticky="w", padx=(T.space_2, 0))
        ui.button(self.log_header, "复制", self._copy_log, "ghost", width=44, height=28).grid(row=0, column=2, padx=T.space_1)
        ui.button(self.log_header, "清空", self._confirm_clear_log, "ghost", width=44, height=28).grid(row=0, column=3, padx=T.space_1)
        ui.button(self.log_header, "折叠", self._toggle_log_collapse, "ghost", width=44, height=28).grid(row=0, column=4, padx=T.space_1)
        ctk.CTkOptionMenu(self.log_header, values=["ALL", "INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG"], variable=self.log_level_var, width=82, height=30, command=lambda _: self._apply_log_filter()).grid(row=1, column=0, padx=(0, T.space_1), pady=(T.space_2, 0), sticky="w")
        ui.entry(self.log_header, textvariable=self.log_search_var, placeholder_text="搜索日志").grid(row=1, column=1, columnspan=4, padx=(T.space_1, 0), pady=(T.space_2, 0), sticky="ew")
        self.log_search_var.trace_add("write", lambda *_: self._apply_log_filter())
        ctk.CTkSwitch(self.log_header, text="", variable=self.log_autoscroll_var, width=40, font=T.font(12), command=self._apply_log_filter()).grid(row=0, column=5, padx=(T.space_1, 0))
        ui.button(self.log_header, "导出", self._export_log, "ghost", width=44, height=28).grid(row=0, column=6, padx=(T.space_1, 0))
        self.log_collapsed_btn = ui.button(self.log_container, "展开\n日志", self._toggle_log_collapse, "secondary", width=40, height=96)
        self.log_collapsed_btn.grid(row=1, column=0, rowspan=3, sticky="n", padx=T.space_2, pady=T.space_3)
        self.log_collapsed_btn.grid_remove()

        self.log_body = ctk.CTkFrame(self.log_container, fg_color="transparent")
        self.log_body.grid(row=3, column=0, sticky="nsew", padx=(T.space_3 + 6, T.space_3), pady=(T.space_2, T.space_3))
        self.log_body.grid_columnconfigure(0, weight=1)
        self.log_body.grid_rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_body,
            wrap=tk.WORD,
            state="disabled",
            bd=0,
            relief="flat",
            font=(T.mono_family, 11),
            height=8,
            bg=colors["surface_2"],
            fg=colors["text_primary"],
            insertbackground=colors["text_primary"],
            selectbackground=colors["brand"],
        )
        scroll = ttk.Scrollbar(self.log_body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self._configure_log_tags()

    def _build_overview_page(self, page):
        self.guide_card = ui.card(page, "首次配置引导", "按顺序完成后即可开始监听", compact=True)
        self.guide_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, T.space_3))
        self.guide_card.grid_columnconfigure((0, 1), weight=1)
        steps = [
            ("1", "配置 Telegram API", "填写 API ID 和 API Hash", "去配置", lambda: self._show_page("groups")),
            ("2", "登录监听账号", "用于监听源群消息", "去登录", self._login_monitor_account),
            ("3", "设置群组", "添加源群并填写目标群", "去配置", lambda: self._show_page("groups")),
            ("4", "校验并开始", "检查配置后启动监听", "去校验", self._validate_and_show),
        ]
        for index, (num, title, desc, btn, command) in enumerate(steps):
            row = 2 + index // 2
            col = index % 2
            step = ui.card(self.guide_card, compact=True)
            step.configure(height=92)
            step.grid(row=row, column=col, sticky="nsew", padx=(T.space_4 if col == 0 else T.space_2, T.space_4 if col == 1 else T.space_2), pady=(0, T.space_2))
            step.grid_propagate(False)
            step.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(step, text=num, width=22, height=20, corner_radius=999, fg_color=T.colors()["surface_3"], font=T.font(11, "bold")).grid(row=0, column=0, sticky="w", padx=(T.space_2, T.space_1), pady=(T.space_2, 0))
            ctk.CTkLabel(step, text=title, font=T.font(12, "bold"), text_color=T.colors()["text_primary"]).grid(row=0, column=1, sticky="w", padx=(0, T.space_2), pady=(T.space_2, 0))
            ctk.CTkLabel(step, text=desc, font=T.font(11), text_color=T.colors()["text_muted"], wraplength=190, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", padx=T.space_2, pady=(T.space_1, T.space_1))
            ui.button(step, btn, command, "secondary", height=26).grid(row=2, column=0, columnspan=2, sticky="ew", padx=T.space_2, pady=(0, T.space_2))

        metrics = ctk.CTkFrame(page, fg_color="transparent")
        metrics.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, T.space_3))
        for col in range(3):
            metrics.grid_columnconfigure(col, weight=1)
        self._metric(metrics, 0, 0, "账号总数", "total_accounts", "账号池中的全部账号")
        self._metric(metrics, 0, 1, "活跃账号", "active_accounts", "已绑定发送人的账号")
        self._metric(metrics, 0, 2, "空闲账号", "idle_accounts", "可用于新发送人的账号")
        self._metric(metrics, 1, 0, "封禁账号", "banned_accounts", "已移入封禁目录")
        self._metric(metrics, 1, 1, "今日已转发", "total_messages_forwarded", "当前运行期间累计")

        task = ui.card(page, "当前任务", "当前配置和策略摘要")
        task.grid(row=2, column=0, sticky="nsew", padx=(0, T.space_2))
        task.grid_columnconfigure(0, weight=1)
        self.overview_config_label = ctk.CTkLabel(task, text="尚未加载配置。", font=T.font(13), justify="left", anchor="w")
        self.overview_config_label.grid(row=2, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_5))
        ui.button(task, "编辑配置", lambda: self._show_page("groups"), "secondary", height=34).grid(row=3, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))

        alerts = ui.card(page, "运行提醒", "配置缺口和运行异常会显示在这里")
        alerts.grid(row=2, column=1, sticky="nsew", padx=(T.space_2, 0))
        self.validation_panel = ctk.CTkFrame(alerts, fg_color="transparent")
        self.validation_panel.grid(row=2, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_5))
        self._render_validation(["尚未执行校验。"])

    def _metric(self, parent, row, col, title, key, desc):
        item = ui.card(parent, compact=True)
        item.configure(height=82)
        item.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else T.space_2, 0), pady=(0, T.space_2))
        item.grid_propagate(False)
        ctk.CTkLabel(item, text=title, font=T.font(11), text_color=T.colors()["text_muted"]).grid(row=0, column=0, sticky="w", padx=T.space_2, pady=(T.space_2, 0))
        label = ctk.CTkLabel(item, text="0", font=T.font(20, "bold"), text_color=T.colors()["text_primary"])
        label.grid(row=1, column=0, sticky="w", padx=T.space_2)
        ctk.CTkLabel(item, text=desc, font=T.font(10), text_color=T.colors()["text_muted"]).grid(row=2, column=0, sticky="w", padx=T.space_2, pady=(0, T.space_1))
        self.stat_value_labels[key] = label

    def _build_group_config_page(self, page):
        api = ui.card(page, "Telegram API", "基础 API 和监听账号")
        api.grid(row=0, column=0, sticky="nsew", padx=(0, T.space_2), pady=(0, T.space_4))
        api.grid_columnconfigure((0, 1), weight=1)
        ui.field_label(api, "API ID", 2, 0)
        self.api_id = ui.entry(api, placeholder_text="12345678")
        self.api_id.grid(row=3, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(api, "API Hash", 2, 1)
        self.api_hash = ui.entry(api, placeholder_text="Telegram API Hash", show="*")
        self.api_hash.grid(row=3, column=1, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(api, "监听账号手机号", 4, 0)
        self.monitor_phone = ui.entry(api, placeholder_text="+8613800000000")
        self.monitor_phone.grid(row=5, column=0, columnspan=2, sticky="ew", padx=T.space_5, pady=(0, T.space_5))

        proxy = ui.card(page, "代理配置", "代理关闭时字段会禁用但不会清空")
        proxy.grid(row=0, column=1, sticky="nsew", padx=(T.space_2, 0), pady=(0, T.space_4))
        proxy.grid_columnconfigure(0, weight=3)
        proxy.grid_columnconfigure(1, weight=1)
        self.var_proxy_enabled = tk.BooleanVar(value=False)
        ctk.CTkSwitch(proxy, text="启用代理", variable=self.var_proxy_enabled, command=self._toggle_proxy_fields, font=T.font(13)).grid(row=2, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(proxy, "代理类型", 3, 0)
        self.proxy_type = ui.entry(proxy, placeholder_text="socks5 / socks4 / http")
        self.proxy_type.grid(row=4, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(proxy, "端口", 3, 1)
        self.proxy_port = ui.entry(proxy, placeholder_text="7890")
        self.proxy_port.grid(row=4, column=1, sticky="ew", padx=(0, T.space_5), pady=(0, T.space_3))
        ui.field_label(proxy, "代理主机", 5, 0)
        self.proxy_host = ui.entry(proxy, placeholder_text="127.0.0.1")
        self.proxy_host.grid(row=6, column=0, columnspan=2, sticky="ew", padx=T.space_5, pady=(0, T.space_5))

        groups = ui.card(page, "群组配置", "源群支持英文逗号或换行分隔")
        groups.grid(row=1, column=0, sticky="nsew", padx=(0, T.space_2), pady=(0, T.space_4))
        groups.grid_columnconfigure(0, weight=1)
        ui.field_label(groups, "源群组", 2, 0)
        self.source_groups = ui.entry(groups, placeholder_text="https://t.me/a, @group_b")
        self.source_groups.grid(row=3, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(groups, "目标群组", 4, 0)
        self.target_group = ui.entry(groups, placeholder_text="https://t.me/target")
        self.target_group.grid(row=5, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        row = ctk.CTkFrame(groups, fg_color="transparent")
        row.grid(row=6, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_5))
        ui.button(row, "测试访问", lambda: self.toast.show("测试访问需要真实 Telegram 环境。", "warning"), "secondary", height=34).pack(side="left", padx=(0, T.space_2))
        ui.button(row, "加入目标群", self._join_target_all, "secondary", height=34).pack(side="left", padx=(0, T.space_2))
        ui.button(row, "清除字段", lambda: self._set_entry_value(self.target_group, ""), "ghost", height=34).pack(side="left")

        filters = ui.card(page, "过滤与替换", "黑名单和替换规则保持原配置格式兼容")
        filters.grid(row=1, column=1, sticky="nsew", padx=(T.space_2, 0), pady=(0, T.space_4))
        filters.grid_columnconfigure(0, weight=1)
        ui.field_label(filters, "黑名单用户 ID", 2, 0)
        self.black_users = ui.entry(filters, placeholder_text="12345,67890")
        self.black_users.grid(row=3, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(filters, "黑名单关键词", 4, 0)
        self.black_words = ui.entry(filters, placeholder_text="广告, 兼职, 推广")
        self.black_words.grid(row=5, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        ui.field_label(filters, "替换规则（每行 old=new）", 6, 0)
        self.replacements = ctk.CTkTextbox(filters, height=120, corner_radius=T.radius_sm, font=T.font(13), fg_color=T.colors()["surface_2"])
        self.replacements.grid(row=7, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_5))

        action = ctk.CTkFrame(page, fg_color="transparent")
        action.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, T.space_4))
        action.grid_columnconfigure(0, weight=1)
        self.config_dirty_label = ctk.CTkLabel(action, text="未保存更改：无", font=T.font(12), text_color=T.colors()["text_muted"])
        self.config_dirty_label.grid(row=0, column=0, sticky="w")
        ui.button(action, "校验配置", self._validate_and_show, "secondary").grid(row=0, column=1, padx=T.space_2)
        self.save_config_btn = ui.button(action, "保存更改", self._save_settings_from_page, "primary")
        self.save_config_btn.grid(row=0, column=2)
        self._bind_dirty_tracking()

    def _build_strategy_page(self, page):
        self._build_strategy_tab(page)
        action = ctk.CTkFrame(page, fg_color="transparent")
        action.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, T.space_4))
        action.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(action, text="策略更改会在保存后写入现有配置字段。", font=T.font(12), text_color=T.colors()["text_muted"]).grid(row=0, column=0, sticky="w")
        ui.button(action, "恢复默认值", self._reset_strategy_defaults, "secondary").grid(row=0, column=1, padx=T.space_2)
        ui.button(action, "保存策略", self._save_settings_from_page, "primary").grid(row=0, column=2)

    def _tab_scroll(self, tab):
        """兼容旧页面 mixin：新页面本身已经是可滚动容器。"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        return tab

    def _content_card(self, parent, row, column, title, subtitle=None, columnspan=1, padx=(0, 0), pady=(0, 10)):
        """兼容旧页面 mixin 的卡片创建方法。"""
        frame = ui.card(parent, title, subtitle)
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="new", padx=padx, pady=pady)
        frame.grid_columnconfigure(0, weight=1)
        return frame

    def _form_label(self, parent, row, column, text, padx):
        ui.field_label(parent, text, row, column, padx=padx)

    def _build_accounts_page(self, page):
        toolbar = ui.card(page, compact=True)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, T.space_2))
        toolbar.grid_columnconfigure(0, weight=1)
        self.pool_filter_entry = ui.entry(toolbar, textvariable=self.pool_filter_var, placeholder_text="搜索手机号 / Session / 用户 ID / 状态")
        self.pool_filter_entry.grid(row=0, column=0, sticky="ew", padx=(T.space_3, T.space_2), pady=T.space_3)
        self.pool_summary_label = ctk.CTkLabel(toolbar, text="共 0 个账号，当前显示 0 个", font=T.font(12), text_color=T.colors()["text_muted"])
        self.pool_summary_label.grid(row=0, column=1, sticky="w", padx=(0, T.space_3), pady=T.space_3)
        ui.button(toolbar, "刷新", lambda: self._refresh_pool_view(schedule_next=False), "secondary", height=34).grid(row=0, column=2, padx=(0, T.space_2), pady=T.space_3)
        self.delete_account_btn = ui.button(toolbar, "删除选中", self._delete_selected_account, "danger", height=34)
        self.delete_account_btn.grid(row=0, column=3, padx=(0, T.space_2), pady=T.space_3)
        self.delete_account_btn.configure(state="disabled")
        ui.button(toolbar, "登录账号", self._show_login_choice, "primary", height=34).grid(row=0, column=4, padx=(0, T.space_3), pady=T.space_3)

        table_card = ui.card(page)
        table_card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, T.space_2))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self.tree = ttk.Treeview(
            table_card,
            columns=("phone", "user_id", "last_used", "last_switch", "daily", "state", "folder"),
            show="headings",
            height=9,
            style="Pool.Treeview",
            selectmode="extended",
        )
        headings = {
            "phone": "手机号 / Session",
            "user_id": "绑定用户 ID",
            "last_used": "最后活跃",
            "last_switch": "最后切换",
            "daily": "今日额度",
            "state": "状态",
            "folder": "目录",
        }
        for key, text in headings.items():
            self.tree.heading(key, text=text)
        for key, width in {"phone": 190, "user_id": 130, "last_used": 170, "last_switch": 170, "daily": 92, "state": 92, "folder": 122}.items():
            self.tree.column(key, width=width, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=T.space_5, pady=T.space_5)
        self.tree.bind("<ButtonRelease-1>", self._select_pool_row_at_event)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_pool_selection_state())
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns", pady=T.space_5)
        self._configure_tree_style()
        batch = ctk.CTkFrame(page, fg_color="transparent")
        batch.grid(row=2, column=0, columnspan=2, sticky="ew", pady=T.space_3)
        batch.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(batch, text="危险操作已收纳到批量栏，删除前会二次确认。", font=T.font(12), text_color=T.colors()["text_muted"]).grid(row=0, column=0, sticky="w")
        ui.button(batch, "删除选中账号", self._delete_selected_account, "danger").grid(row=0, column=1, padx=T.space_2)
        ui.button(batch, "清空头像", self._clear_photos, "secondary").grid(row=0, column=2)

    def _select_pool_row_at_event(self, event):
        """点击账号池空白或单元格时，明确更新表格选中状态。"""
        if not getattr(self, "tree", None):
            return
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
        self._update_pool_selection_state()

    def _update_pool_selection_state(self):
        selected_count = len(self.tree.selection()) if getattr(self, "tree", None) else 0
        if getattr(self, "delete_account_btn", None):
            self.delete_account_btn.configure(
                state="normal" if selected_count else "disabled",
                text=f"删除选中({selected_count})" if selected_count else "删除选中",
            )

    def _build_settings_page(self, page):
        appearance = ui.card(page, "外观", "主题和窗口偏好")
        appearance.grid(row=0, column=0, sticky="nsew", padx=(0, T.space_2), pady=(0, T.space_4))
        ctk.CTkLabel(appearance, text="主题", font=T.font(13), text_color=T.colors()["text_secondary"]).grid(row=2, column=0, sticky="w", padx=T.space_5)
        ctk.CTkSegmentedButton(appearance, values=["light", "dark", "system"], variable=self.theme_mode, command=self._switch_theme, height=36).grid(row=3, column=0, sticky="ew", padx=T.space_5, pady=(T.space_2, T.space_5))
        ctk.CTkLabel(appearance, text="界面缩放：跟随系统 DPI（100% / 125% / 150%）", font=T.font(12), text_color=T.colors()["text_muted"]).grid(row=4, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))

        logs = ui.card(page, "日志", "底部日志抽屉设置")
        logs.grid(row=0, column=1, sticky="nsew", padx=(T.space_2, 0), pady=(0, T.space_4))
        ctk.CTkLabel(logs, text="最大保留行数：1000", font=T.font(13), text_color=T.colors()["text_secondary"]).grid(row=2, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_2))
        ctk.CTkSwitch(logs, text="自动滚动", variable=self.log_autoscroll_var, font=T.font(13)).grid(row=3, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))

        files = ui.card(page, "文件与目录", "当前工作目录和配置目录")
        files.grid(row=1, column=0, columnspan=2, sticky="ew")
        files.grid_columnconfigure(0, weight=1)
        ui.field_label(files, "当前工作目录", 2, 0)
        work = ui.entry(files)
        work.grid(row=3, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_2))
        work.insert(0, os.path.abspath("."))
        work.configure(state="disabled")
        ui.field_label(files, "当前配置目录", 4, 0)
        setting = ui.entry(files)
        setting.grid(row=5, column=0, sticky="ew", padx=T.space_5, pady=(0, T.space_3))
        setting.insert(0, os.path.abspath("setting"))
        setting.configure(state="disabled")
        row = ctk.CTkFrame(files, fg_color="transparent")
        row.grid(row=6, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))
        ui.button(row, "打开工作目录", self._open_workdir, "secondary").pack(side="left", padx=(0, T.space_2))
        ui.button(row, "打开配置目录", lambda: self._open_directory("setting"), "secondary").pack(side="left")

    def _build_about_page(self, page):
        info = ui.card(page, "应用信息", "运行环境和目录")
        info.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, T.space_4))
        info.grid_columnconfigure(1, weight=1)
        lines = [
            ("应用名称", "TG 群组克隆控制台"),
            ("版本号", "1.0"),
            ("Python", sys.version.split()[0]),
            ("CustomTkinter", getattr(ctk, "__version__", "unknown")),
            ("Telethon", self._telethon_version()),
            ("配置目录", os.path.abspath("setting")),
            ("Session 目录", os.path.abspath("sessions")),
        ]
        for index, (key, value) in enumerate(lines, start=2):
            ctk.CTkLabel(info, text=key, font=T.font(13), text_color=T.colors()["text_muted"]).grid(row=index, column=0, sticky="w", padx=T.space_5, pady=2)
            ctk.CTkLabel(info, text=value, font=T.font(12), text_color=T.colors()["text_primary"], wraplength=520, justify="left").grid(row=index, column=1, sticky="ew", padx=T.space_5, pady=2)
        capability = ui.card(page, "主要能力", "监听、转发、身份同步和账号池管理")
        capability.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, T.space_3))
        ctk.CTkLabel(capability, text="- 多源群监听与单目标群转发\n- 昵称和头像同步\n- 黑名单、替换规则和账号池管理", justify="left", font=T.font(12), wraplength=620).grid(row=2, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))
        compliance = ui.card(page, "合规提醒", "请只在得到明确授权的场景中使用")
        compliance.grid(row=2, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(compliance, text="请遵守 Telegram 平台规则，并对实际账号和群组数据变更保持谨慎。", wraplength=620, justify="left", font=T.font(12), text_color=T.colors()["warning"]).grid(row=2, column=0, sticky="w", padx=T.space_5, pady=(0, T.space_5))

    def _show_page(self, key):
        self.selected_page = key
        for page_key, frame in self.page_frames.items():
            if page_key == key:
                frame.grid(row=0, column=0, sticky="nsew")
                frame.tkraise()
                self.after_idle(lambda current=frame: self._scroll_page_to_top(current))
            else:
                frame.grid_forget()
        title, desc = self.PAGE_META[key]
        if self.page_title_label:
            self.page_title_label.configure(text=title)
        if self.page_desc_label:
            self.page_desc_label.configure(text=desc)
        for page_key in self.nav_buttons:
            self._paint_nav_item(page_key)

    def _scroll_page_to_top(self, frame):
        """切换页面时复位滚动位置，避免进入页面后停在空白区域。"""
        try:
            canvas = getattr(frame, "_parent_canvas", None)
            if canvas is not None and canvas.winfo_exists():
                canvas.yview_moveto(0)
        except Exception as error:
            self.log(f"复位页面滚动失败：{error}", level="DEBUG")

    def _paint_nav_item(self, key):
        if key not in self.nav_buttons:
            return
        colors = T.colors()
        item, indicator, icon_label, label = self.nav_buttons[key]
        active = self.selected_page == key
        item.configure(fg_color=colors["surface_2"] if active else "transparent")
        indicator.configure(fg_color=colors["brand"] if active else "transparent")
        icon_label.configure(text_color=colors["brand"] if active else colors["text_muted"])
        label.configure(text_color=colors["text_primary"] if active else colors["text_secondary"])

    def _toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        width = T.sidebar_collapsed_width if self.sidebar_collapsed else T.sidebar_width
        self.sidebar.configure(width=width)
        visible = not self.sidebar_collapsed
        for _, _, _, label in self.nav_buttons.values():
            if visible:
                label.grid()
            else:
                label.grid_remove()
        for widget in (self.sidebar_title, self.sidebar_version):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        if self.workdir_btn is not None:
            self.workdir_btn.configure(text="打开工作目录" if visible else "目录", width=0)
        if self.sidebar_toggle_btn is not None:
            self.sidebar_toggle_btn.configure(text="收起侧边栏" if visible else "展开", width=0)
        for button, full_text, short_text in self.theme_buttons.values():
            button.configure(text=full_text if visible else short_text, width=0)
        self._paint_theme_buttons()

    def _toggle_monitoring(self):
        if self._monitor_state in {"starting", "stopping"}:
            return
        if self._monitor_state == "running":
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _set_monitoring_state(self, state, hint=None):
        style = STATUS_STYLE.get(state, STATUS_STYLE["idle"])
        self._monitor_state = state
        self.is_running = state in {"starting", "running", "stopping"}
        label = style["label"]
        tone = {"idle": "muted", "starting": "brand", "running": "success", "stopping": "warning", "error": "danger"}.get(state, "muted")
        if self.status_badge is not None:
            self.status_badge.configure(text=f"● {label}", text_color=T.colors().get(tone, T.colors()["text_muted"]))
        if self.main_action_btn is not None:
            if state == "running":
                self.main_action_btn.configure(text="停止监听", state="normal", fg_color=T.colors()["warning"], hover_color=T.colors()["warning"])
            elif state in {"starting", "stopping"}:
                self.main_action_btn.configure(text="处理中…", state="disabled")
            else:
                self.main_action_btn.configure(text="开始监听", state="normal", fg_color=T.colors()["brand"], hover_color=T.colors()["brand_hover"])

    def _sync_runtime_state(self):
        actual_running = bool(getattr(self.cloner, "is_monitoring", False))
        if self._monitor_state == "starting" and actual_running:
            self._set_monitoring_state("running")
        elif self._monitor_state == "stopping" and not actual_running:
            self._set_monitoring_state("idle")
        elif actual_running and self._monitor_state != "running":
            self._set_monitoring_state("running")
        elif not actual_running and self._monitor_state == "running":
            self._set_monitoring_state("idle", "监听任务已经结束。")

    def _run_async(self, coro, done_callback=None, error_context="异步任务"):
        if self._closing:
            with contextlib.suppress(Exception):
                coro.close()
            return None
        loop = getattr(self.cloner, "loop", None)
        if loop is None or loop.is_closed():
            with contextlib.suppress(Exception):
                coro.close()
            self.log(f"{error_context}失败：事件循环不可用", level="ERROR")
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as error:
            self.log(f"{error_context}失败：{error}", level="ERROR")
            return None

        def _on_done(task):
            task_error = None
            try:
                task.result()
            except Exception as error:
                task_error = error
                if self._ui_alive():
                    self.after(0, lambda err=error: self.log(f"{error_context}失败：{err}", level="ERROR"))
            finally:
                if done_callback and self._ui_alive():
                    self.after(0, lambda current_task=task, err=task_error: done_callback(current_task, err))

        future.add_done_callback(_on_done)
        return future

    def _start_monitoring(self):
        if not self._save_settings(show_dialog=False):
            self._show_page("groups")
            self.toast.show("配置未通过校验，请先修复。", "error")
            return
        self.log("=" * 50)
        self.log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监听...")
        self._set_monitoring_state("starting")

        async def code_cb():
            return await self._ask_from_main("验证码", "请输入收到的验证码：")

        async def pwd_cb():
            return await self._ask_from_main("2FA 密码", "请输入两步验证密码：", show="*")

        self._run_async(self.cloner.start_monitoring(code_cb, pwd_cb), done_callback=self._after_start_monitoring, error_context="启动监听")

    def _after_start_monitoring(self, _future, error):
        if error:
            self._set_monitoring_state("error", "启动过程中出现异常，请检查日志。")
            return
        if self.cloner.is_monitoring:
            self._set_monitoring_state("running")
            self.log("监听任务已启动。", level="SUCCESS")
        else:
            self._set_monitoring_state("error", "监听未能成功启动，请检查账号、群组和网络配置。")

    def _stop_monitoring(self):
        if not messagebox.askyesno("停止监听", "确定要停止当前监听任务吗？"):
            return
        if not self.cloner.is_monitoring and self._monitor_state not in {"starting", "running"}:
            self.log("监听当前未在运行。", level="WARNING")
            return
        self.log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 请求停止监听...")
        self._set_monitoring_state("stopping")
        self._run_async(self.cloner.stop_monitoring(), done_callback=self._after_stop_monitoring, error_context="停止监听")

    def _after_stop_monitoring(self, _future, error):
        if error and self.cloner.is_monitoring:
            self._set_monitoring_state("error", "停止监听时出现异常，请检查日志。")
            return
        self._set_monitoring_state("idle", "监听已停止，可以继续调整配置。")
        self.log("监听已停止。", level="SUCCESS")

    def _login_new_account(self):
        if not self._save_settings(show_dialog=False):
            self.toast.show("请先修正配置，再登录新账号。", "error")
            self._show_page("groups")
            return
        phone = self._simple_prompt("登录克隆号", "请输入手机号（带区号，以 + 开头）：")
        if not phone:
            return

        async def code_cb():
            return await self._ask_from_main("验证码", f"请输入 {phone} 的验证码：")

        async def pwd_cb():
            return await self._ask_from_main("2FA 密码", f"请输入 {phone} 的两步验证密码：", show="*")

        self.log(f"开始为 {phone} 登录...")
        self._run_async(self.cloner.login_new_account(phone, code_cb, pwd_cb), error_context="登录克隆号")

    def _login_monitor_account(self):
        if not self._save_settings(show_dialog=False):
            self.toast.show("请先修正配置，再登录监听账号。", "error")
            self._show_page("groups")
            return
        phone = self._simple_prompt("登录监听号", "请输入监听账号手机号（带区号，以 + 开头）：")
        if not phone:
            return
        phone = phone.strip()
        try:
            self.config_obj.set("telegram", "monitor_phone", phone)
            self.config_obj.save_config()
            self._set_entry_value(self.monitor_phone, phone)
        except Exception:
            pass

        async def code_cb():
            return await self._ask_from_main("验证码", f"请输入 {phone} 的验证码：")

        async def pwd_cb():
            return await self._ask_from_main("2FA 密码", "请输入两步验证密码：", show="*")

        self.log(f"开始登录或更换监听账号：{phone}")
        if hasattr(self.cloner, "login_monitor_account"):
            self._run_async(self.cloner.login_monitor_account(phone, code_cb, pwd_cb), error_context="登录监听号")
        else:
            self._run_async(self.cloner.start_monitoring(code_cb, pwd_cb), error_context="登录监听号")

    def _join_target_all(self):
        if not self._save_settings(show_dialog=False):
            self.toast.show("请先修正配置，再加入目标群。", "error")
            return
        self.log("准备让账号池全部加入目标群...")
        self._run_async(self.cloner.do_join_target_for_all(), error_context="加入目标群")

    def _clear_photos(self):
        if not messagebox.askyesno("清空头像", "确定清空账号池中账号的历史头像吗？"):
            return
        self.log("开始清空历史头像...")
        self._run_async(self.cloner.delete_all_photos(), error_context="清空头像")

    def _delete_monitor_account(self):
        if not messagebox.askyesno("确认删除", "确定删除监听账号的 Session 文件吗？\n删除后需要重新登录。"):
            return
        self.log("正在删除监听账号 Session ...")
        if hasattr(self.cloner, "delete_monitor_session"):
            self._run_async(self.cloner.delete_monitor_session(), error_context="删除监听账号 Session")

    def _show_login_choice(self):
        dialog = CustomInputDialog(self, title="登录账号", prompt="输入 1 登录监听账号，输入 2 登录克隆账号：")
        choice = (dialog.get_input() or "").strip()
        if choice == "1":
            self._login_monitor_account()
        elif choice == "2":
            self._login_new_account()

    def _simple_prompt(self, title, prompt, show=None):
        dialog = CustomInputDialog(self, title=title, prompt=prompt, show=show)
        return dialog.get_input()

    async def _ask_from_main(self, title, prompt, show=None):
        future = self.cloner.loop.create_future()

        def runner():
            try:
                dialog = CustomInputDialog(self, title=title, prompt=prompt, show=show)
                self.cloner.loop.call_soon_threadsafe(future.set_result, dialog.get_input())
            except Exception as error:
                self.cloner.loop.call_soon_threadsafe(future.set_exception, error)

        if self._ui_alive():
            self.after(0, runner)
        return await future

    def _validate_and_show(self):
        self._set_monitoring_state("starting")
        errors = self._validate_settings()
        self.config_valid = not errors
        if errors:
            self._render_validation(errors)
            self._set_monitoring_state("error")
            self.toast.show("配置校验未通过。", "error")
            self._show_page("overview")
            return False
        checks = [
            "Telegram API：通过",
            "监听账号：已填写或已有 Session",
            f"源群：{len(self._split_csv(self.source_groups.get()))} 个",
            "目标群：已填写",
            f"可用克隆账号：{self.cloner.get_stats().get('total_accounts', 0)} 个",
            "替换规则：格式通过",
        ]
        self._render_validation(checks, success=True)
        self._set_monitoring_state("idle")
        self.toast.show("配置校验通过。", "success")
        return True

    def _render_validation(self, lines, success=False):
        if not self.validation_panel:
            return
        for child in self.validation_panel.winfo_children():
            child.destroy()
        for index, line in enumerate(lines):
            tone = "success" if success else ("danger" if index == 0 and line != "尚未执行校验。" else "warning")
            mark = "✓" if success else ("!" if line != "尚未执行校验。" else "i")
            row = ctk.CTkFrame(self.validation_panel, fg_color=T.colors()["surface_2"], corner_radius=T.radius_sm)
            row.grid(row=index, column=0, sticky="ew", pady=(0, T.space_2))
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=mark, width=28, text_color=T.colors().get(tone, T.colors()["brand"]), font=T.font(14, "bold")).grid(row=0, column=0, padx=T.space_2, pady=T.space_2)
            ctk.CTkLabel(row, text=line, anchor="w", font=T.font(13), text_color=T.colors()["text_primary"]).grid(row=0, column=1, sticky="ew", pady=T.space_2)
            if not success and line != "尚未执行校验。":
                ui.button(row, "去修复", lambda: self._show_page("groups"), "ghost", height=30).grid(row=0, column=2, padx=T.space_2)

    def _save_settings_from_page(self):
        if self._save_settings(show_dialog=False):
            self._mark_clean()
            self.toast.show("配置已保存。", "success")
            return True
        self.toast.show("保存失败，请检查配置。", "error")
        return False

    def _save_settings(self, show_dialog=True):
        result = super()._save_settings(show_dialog=show_dialog)
        if result:
            self._refresh_config_summary()
        return result

    def _mark_dirty(self, *_):
        self.config_dirty = True
        if hasattr(self, "config_dirty_label") and self.config_dirty_label:
            self.config_dirty_label.configure(text="未保存更改：有")

    def _mark_clean(self):
        self.config_dirty = False
        if hasattr(self, "config_dirty_label") and self.config_dirty_label:
            self.config_dirty_label.configure(text="未保存更改：无")

    def _bind_dirty_tracking(self):
        widgets = [self.api_id, self.api_hash, self.monitor_phone, self.proxy_host, self.proxy_port, self.source_groups, self.target_group, self.black_users, self.black_words]
        for widget in widgets:
            widget.bind("<KeyRelease>", self._mark_dirty)
        self.replacements.bind("<KeyRelease>", self._mark_dirty)

    def _refresh_config_summary(self):
        if not getattr(self, "overview_config_label", None):
            return
        try:
            source_groups = self._split_csv(self.source_groups.get().strip())
            target_group = self.target_group.get().strip() or "未设置"
            proxy_text = "开启" if self.var_proxy_enabled.get() else "关闭"
            replacement_mode = self._mode_to_label(self._label_to_mode(self.replacement_mode_var.get()))
            replacement_lines = len(self._normalize_replacements())
            clone_name = "开启" if self.var_clone_name.get() else "关闭"
            clone_avatar = "开启" if self.var_clone_avatar.get() else "关闭"
            text = (
                f"源群：{len(source_groups)} 个\n"
                f"目标群：{target_group}\n"
                f"代理：{proxy_text}\n"
                f"替换模式：{replacement_mode} / 规则：{replacement_lines}\n"
                f"昵称同步：{clone_name}，头像同步：{clone_avatar}\n"
                f"分片：{self.shard_index.get().strip() or '0'} / {self.shard_total.get().strip() or '1'}\n"
                f"每日额度：{self.daily_limit.get().strip() or '30'}"
            )
            self.overview_config_label.configure(text=text)
        except Exception as error:
            self.log(f"刷新配置摘要失败：{error}", level="ERROR")

    def _reset_strategy_defaults(self):
        self.var_clone_name.set(True)
        self.var_clone_avatar.set(True)
        self._set_entry_value(self.cooldown, "3600")
        self._set_entry_value(self.daily_limit, "30")
        self._set_entry_value(self.shard_total, "1")
        self._set_entry_value(self.shard_index, "0")
        self._set_entry_value(self.min_interval, "1.0")
        self._set_entry_value(self.max_interval, "3.0")
        self.replacement_mode_var.set(self._mode_to_label("literal"))
        self.var_replacements_case_insensitive.set(False)
        self.var_adaptive_throttle.set(True)
        self._set_entry_value(self.adaptive_decay, "0.85")
        self._set_entry_value(self.adaptive_penalty, "1.25")
        self._set_entry_value(self.adaptive_cap, "30.0")
        self._toggle_adaptive_fields()
        self.toast.show("策略已恢复默认值，保存后生效。", "success")

    def _configure_tree_style(self):
        colors = T.colors()
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Pool.Treeview", background=colors["surface_1"], foreground=colors["text_primary"], fieldbackground=colors["surface_1"], rowheight=44, borderwidth=0, font=(T.font_family, 10))
        style.configure("Pool.Treeview.Heading", background=colors["surface_2"], foreground=colors["text_secondary"], font=(T.font_family, 10, "bold"), padding=(8, 8))
        style.map("Pool.Treeview", background=[("selected", colors["brand"])], foreground=[("selected", "#FFFFFF")])

    def _apply_log_theme(self):
        if not self.log_text:
            return
        colors = T.colors()
        self.log_text.configure(bg=colors["surface_2"], fg=colors["text_primary"], selectbackground=colors["brand"], insertbackground=colors["text_primary"])
        self._configure_log_tags()

    def _configure_log_tags(self):
        if not self.log_text:
            return
        colors = T.colors()
        self.log_text.tag_configure("INFO", foreground="#8CB4FF")
        self.log_text.tag_configure("SUCCESS", foreground=colors["success"])
        self.log_text.tag_configure("WARNING", foreground=colors["warning"])
        self.log_text.tag_configure("ERROR", foreground=colors["danger"])
        self.log_text.tag_configure("DEBUG", foreground=colors["text_muted"])
        self.log_text.tag_configure("MATCH", background=colors["surface_3"])

    def log(self, message: str, level="INFO"):
        def _write():
            try:
                if not self.log_text or not self.winfo_exists():
                    return
                at_bottom = self.log_text.yview()[1] >= 0.98
                timestamp = datetime.now().strftime("%H:%M:%S")
                normalized = (level or "INFO").upper()
                prefix = {"INFO": "[INFO]", "SUCCESS": "[OK]", "WARNING": "[WARN]", "ERROR": "[ERROR]", "DEBUG": "[DEBUG]"}.get(normalized, "[INFO]")
                tag = normalized if normalized in {"INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG"} else "INFO"
                self.log_text.config(state="normal")
                self.log_text.insert(tk.END, f"[{timestamp}] {prefix} {message}\n", tag)
                self.log_text.config(state="disabled")
                lines = int(self.log_text.index("end-1c").split(".")[0])
                if self.log_count_label:
                    self.log_count_label.configure(text=f"{max(0, lines - 1)} 行")
                if lines > 1000:
                    self.log_text.config(state="normal")
                    self.log_text.delete(1.0, f"{lines - 800}.0")
                    self.log_text.config(state="disabled")
                if self.log_autoscroll_var.get() and at_bottom:
                    self.log_text.yview(tk.END)
            except Exception:
                pass

        try:
            if self.winfo_exists():
                self.after(0, _write)
        except Exception:
            pass

    def _apply_log_filter(self):
        if not self.log_text:
            return
        keyword = self.log_search_var.get().strip()
        self.log_text.tag_remove("MATCH", "1.0", tk.END)
        if keyword:
            start = "1.0"
            while True:
                pos = self.log_text.search(keyword, start, stopindex=tk.END, nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(keyword)}c"
                self.log_text.tag_add("MATCH", pos, end)
                start = end

    def _confirm_clear_log(self):
        if messagebox.askyesno("清空日志", "确定清空当前运行日志吗？"):
            self._clear_log()

    def _clear_log(self):
        if self.log_text:
            self.log_text.config(state="normal")
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state="disabled")
            if self.log_count_label:
                self.log_count_label.configure(text="0 行")

    def _copy_log(self):
        if not self.log_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get("1.0", tk.END))
        self.toast.show("日志已复制。", "success")

    def _resize_log_panel(self, event):
        if not self.log_container:
            return
        window_w = max(self.winfo_width(), 900)
        new_w = max(260, min(window_w - event.x_root + self.winfo_rootx(), int(window_w * 0.45)))
        self.log_panel_height = new_w
        self.log_container.configure(width=new_w)
        with contextlib.suppress(Exception):
            self.config_obj.set("ui", "log_panel_height", str(new_w))
            self.config_obj.save_config()

    def _toggle_log_collapse(self):
        self.log_panel_collapsed = not self.log_panel_collapsed
        if self.log_panel_collapsed:
            for widget in (self.log_grip, self.log_header, self.log_body):
                if widget is not None:
                    widget.grid_remove()
            if self.log_collapsed_btn is not None:
                self.log_collapsed_btn.grid()
        else:
            if self.log_grip is not None:
                self.log_grip.grid()
            if self.log_header is not None:
                self.log_header.grid()
            if self.log_body is not None:
                self.log_body.grid()
            if self.log_collapsed_btn is not None:
                self.log_collapsed_btn.grid_remove()
        self.log_container.configure(width=T.log_side_collapsed_width if self.log_panel_collapsed else T.log_side_width)

    def _toggle_log_maximize(self):
        self.log_panel_maximized = not self.log_panel_maximized
        target = int(self.winfo_width() * 0.45) if self.log_panel_maximized else T.log_side_width
        self.log_container.configure(width=target)

    def _open_workdir(self):
        self._open_directory(".")

    def _open_directory(self, path):
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(abs_path, exist_ok=True)
            os.startfile(abs_path)
        except Exception as error:
            self.log(f"打开目录失败：{error}", level="ERROR")

    def _switch_theme(self, value=None):
        if self._theme_switching:
            return
        self._theme_switching = True
        try:
            mode = (value or self.theme_mode.get() or "dark").lower()
            self.theme_mode.set(mode)
            ctk.set_appearance_mode(mode.capitalize())
            self._apply_theme_recursive()
            self._configure_tree_style()
            self._apply_log_theme()
            self._paint_all_nav_items()
            self._paint_theme_buttons()
            self.log(f"已切换到 {mode} 主题。", level="SUCCESS")
        except Exception as error:
            self.log(f"切换主题失败：{error}", level="ERROR")
        finally:
            self._theme_switching = False

    def _apply_theme_recursive(self):
        colors = T.colors()
        self.configure(fg_color=colors["app_bg"])
        if self.sidebar is not None:
            self.sidebar.configure(fg_color=colors["sidebar_bg"])
        if self.content_host is not None:
            self.content_host.configure(fg_color=colors["app_bg"])
        if self.log_container is not None:
            self.log_container.configure(fg_color=colors["surface_1"], border_color=colors["border"])

    def _paint_all_nav_items(self):
        for page_key in self.nav_buttons:
            self._paint_nav_item(page_key)

    def _paint_theme_buttons(self):
        colors = T.colors()
        current = (self.theme_mode.get() or "dark").lower()
        for mode, (button, _full_text, _short_text) in self.theme_buttons.items():
            active = current == mode
            button.configure(
                fg_color=colors["brand"] if active else colors["surface_2"],
                hover_color=colors["brand_hover"] if active else colors["surface_3"],
                text_color="#FFFFFF" if active else colors["text_primary"],
                border_color=colors["brand"] if active else colors["border"],
            )

    def _telethon_version(self):
        try:
            import telethon
            return getattr(telethon, "__version__", "unknown")
        except Exception:
            return "unknown"

    def _finish_shutdown(self):
        with contextlib.suppress(Exception):
            for job in self.tk.call("after", "info"):
                with contextlib.suppress(Exception):
                    self.after_cancel(job)
        try:
            loop = getattr(self.cloner, "loop", None)
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _poll_shutdown(self):
        future = self._shutdown_future
        done = future is None or future.done()
        timed_out = time.monotonic() >= self._shutdown_deadline
        if not done and not timed_out:
            self.after(80, self._poll_shutdown)
            return
        self._finish_shutdown()

    def _cancel_scheduled_jobs(self):
        for attr_name in ("_pool_refresh_job", "_stats_refresh_job"):
            job = getattr(self, attr_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr_name, None)

    def _schedule_pool_refresh(self, delay=1500):
        if not self._ui_alive():
            return
        if self._pool_refresh_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._pool_refresh_job)
        self._pool_refresh_job = self.after(delay, lambda: self._refresh_pool_view(schedule_next=True))

    def _schedule_stats_refresh(self, delay=2000):
        if not self._ui_alive():
            return
        if self._stats_refresh_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._stats_refresh_job)
        self._stats_refresh_job = self.after(delay, lambda: self._refresh_stats(schedule_next=True))

    def on_closing(self):
        if self._closing:
            return
        self._closing = True
        self._cancel_scheduled_jobs()
        try:
            self.withdraw()
        except Exception:
            pass
        with contextlib.suppress(Exception):
            self.log("正在关闭应用...")
        loop = getattr(self.cloner, "loop", None)
        if loop is None or loop.is_closed():
            self._finish_shutdown()
            return
        try:
            self._shutdown_future = asyncio.run_coroutine_threadsafe(self.cloner.shutdown(), loop)
            self._shutdown_deadline = time.monotonic() + 20.0
            self.after(80, self._poll_shutdown)
        except Exception:
            self._finish_shutdown()
