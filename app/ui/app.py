from __future__ import annotations

import copy
import os
import subprocess
import sys
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from app.config import (
    ConfigStore,
    TELEGRAM_DESKTOP_API_HASH,
    TELEGRAM_DESKTOP_API_ID,
    lines_to_list,
    list_to_lines,
    normalize_sources,
    parse_int_list,
    parse_replacement_lines,
    replacements_to_lines,
)
from app.core.account_manager import AccountManager, SessionRecord, session_name_from_phone
from app.core.auth_service import AuthService
from app.core.forwarder import ForwardingController
from app.core.telethon_compat import TELETHON_AVAILABLE, chinese_error
from app.core.worker import AsyncWorker
from app.logging_bus import LogBus, LogRecord
from app.paths import ensure_runtime_dirs, runtime_paths


LOG_LEVEL_FILTERS: dict[str, set[str] | None] = {
    "全部": None,
    "信息": {"INFO"},
    "成功": {"OK", "SUCCESS"},
    "警告": {"WARNING"},
    "错误": {"ERROR"},
    "调试": {"DEBUG"},
}

LOG_LEVEL_LABELS = {
    "INFO": "信息",
    "OK": "成功",
    "SUCCESS": "成功",
    "WARNING": "警告",
    "ERROR": "错误",
    "DEBUG": "调试",
}


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _on_body_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        if not self.winfo_ismapped() or not self._contains_widget(event.widget):
            return
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return
            units = int(-1 * (delta / 120))
            if units == 0:
                units = -1 if delta > 0 else 1
        self.canvas.yview_scroll(units, "units")
        return "break"

    def _contains_widget(self, widget: tk.Widget) -> bool:
        current: tk.Widget | None = widget
        while current is not None:
            if current in (self, self.canvas, self.body):
                return True
            current = getattr(current, "master", None)
        return False


class TelegramClonerApp(tk.Tk):
    def __init__(self, app_name: str, version: str) -> None:
        super().__init__()
        self.app_name = app_name
        self.version = version
        self.paths = ensure_runtime_dirs()
        self.store = ConfigStore()
        self.config = self.store.load()
        self.log_bus = LogBus()
        self.worker = AsyncWorker()
        self.account_manager = AccountManager()
        self.auth_service = AuthService()
        self.forwarder = ForwardingController(self.account_manager, self.log_bus)
        self.accounts: list[SessionRecord] = []
        self._monitor_future: Future[Any] | None = None
        self._page_frames: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, ttk.Button] = {}
        self.login_dialog: LoginDialog | None = None

        self.title(f"{app_name} {version}")
        self.geometry("960x640")
        self.minsize(960, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._init_variables()
        self._init_style()
        self._build_layout()
        self._build_pages()
        self._show_page("overview")
        self._refresh_accounts()
        self._apply_theme()
        self._poll_logs()
        self.log_bus.info("程序已启动。已内置API；首次使用请登录监听账号和克隆账号。")
        if not TELETHON_AVAILABLE:
            self.log_bus.warning("未检测到 Telethon，登录和监听功能需先执行 pip install -r requirements.txt")

    def _init_variables(self) -> None:
        telegram = self.config.get("telegram", {})
        proxy = self.config.get("proxy", {})
        strategy = self.config.get("strategy", {})
        runtime = self.config.get("runtime", {})
        groups = self.config.get("groups", {})
        filters = self.config.get("filters", {})

        self.api_id_var = tk.StringVar(value=str(telegram.get("api_id", "")))
        self.api_hash_var = tk.StringVar(value=str(telegram.get("api_hash", "")))
        self.phone_var = tk.StringVar(value=str(telegram.get("phone", "")))
        self.monitor_session_var = tk.StringVar(value=str(telegram.get("monitor_session") or session_name_from_phone(str(telegram.get("phone", ""))) or "monitor"))
        self.desktop_fallback_var = tk.BooleanVar(value=bool(telegram.get("use_desktop_fallback", True)))

        self.proxy_enabled_var = tk.BooleanVar(value=bool(proxy.get("enabled", False)))
        self.proxy_type_var = tk.StringVar(value=str(proxy.get("type", "socks5")))
        self.proxy_host_var = tk.StringVar(value=str(proxy.get("host", "")))
        self.proxy_port_var = tk.StringVar(value=str(proxy.get("port", "")))
        self.proxy_username_var = tk.StringVar(value=str(proxy.get("username", "")))
        self.proxy_password_var = tk.StringVar(value=str(proxy.get("password", "")))

        self.target_group_var = tk.StringVar(value=str(groups.get("target", "")))
        self.sync_name_var = tk.BooleanVar(value=bool(strategy.get("sync_name", False)))
        self.sync_avatar_var = tk.BooleanVar(value=bool(strategy.get("sync_avatar", False)))
        self.identity_cooldown_var = tk.StringVar(value=str(strategy.get("identity_cooldown_seconds", 180)))
        self.daily_limit_var = tk.StringVar(value=str(strategy.get("daily_account_limit", 200)))
        self.shard_total_var = tk.StringVar(value=str(strategy.get("shard_total", 1)))
        self.shard_index_var = tk.StringVar(value=str(strategy.get("shard_index", 0)))
        self.send_min_var = tk.StringVar(value=str(strategy.get("send_interval_min", 2.0)))
        self.send_max_var = tk.StringVar(value=str(strategy.get("send_interval_max", 5.0)))
        self.adaptive_throttle_var = tk.BooleanVar(value=bool(strategy.get("adaptive_throttle", True)))
        self.flood_penalty_var = tk.StringVar(value=str(strategy.get("floodwait_penalty_seconds", 60)))
        self.max_interval_var = tk.StringVar(value=str(strategy.get("max_interval_seconds", 600)))
        self.replacement_mode_var = tk.StringVar(value=str(strategy.get("replacement_mode", "literal")))
        self.replacement_ignore_case_var = tk.BooleanVar(
            value=any(bool(item.get("ignore_case")) for item in self.config.get("replacements", []))
        )

        self.theme_var = tk.StringVar(value=str(runtime.get("theme", "system")))
        if runtime.get("log_panel") == "right" and not runtime.get("log_panel_user_set", False):
            runtime["log_panel"] = "bottom"
            runtime["log_panel_user_set"] = False
            self.config.setdefault("runtime", {}).update(runtime)
        self.log_panel_var = tk.StringVar(value=str(runtime.get("log_panel", "bottom")))
        self.account_search_var = tk.StringVar(value="")
        self.account_filter_var = tk.StringVar(value="全部")
        self.log_filter_var = tk.StringVar(value="全部")
        self.log_search_var = tk.StringVar(value="")
        self.auto_scroll_var = tk.BooleanVar(value=True)

        self._initial_sources = list_to_lines(normalize_sources(groups.get("sources", [])))
        self._initial_blocked_users = list_to_lines(filters.get("blocked_user_ids", []))
        self._initial_blocked_keywords = list_to_lines(filters.get("blocked_keywords", []))
        self._initial_replacements = replacements_to_lines(self.config.get("replacements", []))

    def _init_style(self) -> None:
        self.style = ttk.Style(self)
        themes = self.style.theme_names()
        if "vista" in themes:
            self.style.theme_use("vista")
        elif "xpnative" in themes:
            self.style.theme_use("xpnative")
        elif "clam" in themes:
            self.style.theme_use("clam")
        self.colors = {
            "bg": "#f5f7fb",
            "panel": "#ffffff",
            "text": "#1f2937",
            "muted": "#6b7280",
            "accent": "#2563eb",
            "nav": "#eef2ff",
            "danger": "#dc2626",
            "ok": "#16a34a",
            "warning": "#d97706",
        }

    def _apply_theme(self) -> None:
        theme = self.theme_var.get()
        if theme == "dark":
            self.colors.update(
                {
                    "bg": "#111827",
                    "panel": "#1f2937",
                    "text": "#e5e7eb",
                    "muted": "#9ca3af",
                    "accent": "#60a5fa",
                    "nav": "#172033",
                }
            )
        else:
            self.colors.update(
                {
                    "bg": "#f5f7fb",
                    "panel": "#ffffff",
                    "text": "#1f2937",
                    "muted": "#6b7280",
                    "accent": "#2563eb",
                    "nav": "#eef2ff",
                }
            )
        bg = self.colors["bg"]
        panel = self.colors["panel"]
        text = self.colors["text"]
        self.configure(bg=bg)
        self.style.configure(".", background=bg, foreground=text, fieldbackground=panel)
        self.style.configure("TFrame", background=bg)
        self.style.configure("Panel.TFrame", background=panel)
        self.style.configure("Nav.TFrame", background=self.colors["nav"])
        self.style.configure("TLabel", background=bg, foreground=text)
        self.style.configure("Panel.TLabel", background=panel, foreground=text)
        self.style.configure("Muted.TLabel", background=bg, foreground=self.colors["muted"])
        self.style.configure("Title.TLabel", background=bg, foreground=text, font=("Microsoft YaHei UI", 15, "bold"))
        self.style.configure("CardTitle.TLabel", background=panel, foreground=text, font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("TLabelframe", background=panel, foreground=text)
        self.style.configure("TLabelframe.Label", background=panel, foreground=text, font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("TButton", padding=(10, 5))
        self.style.configure("Compact.TButton", padding=(4, 3))
        self.style.configure("Accent.TButton", foreground="#ffffff", background=self.colors["accent"])
        self.style.configure("CompactAccent.TButton", foreground="#ffffff", background=self.colors["accent"], padding=(4, 3))
        self.style.map("Accent.TButton", background=[("active", self.colors["accent"])])
        self.style.map("CompactAccent.TButton", background=[("active", self.colors["accent"])])
        self.style.configure("Treeview", rowheight=28, background=panel, fieldbackground=panel, foreground=text)
        self.style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        if hasattr(self, "log_text"):
            self.log_text.configure(bg="#0f172a" if theme == "dark" else "#111827", fg="#e5e7eb", insertbackground="#e5e7eb")
        if hasattr(self, "nav_frame"):
            self.nav_frame.configure(style="Nav.TFrame")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.nav_frame = ttk.Frame(self, style="Nav.TFrame", width=170)
        self.nav_frame.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.nav_frame.grid_propagate(False)

        self.top_frame = ttk.Frame(self, padding=(16, 10))
        self.top_frame.grid(row=0, column=1, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.content_frame = ttk.Frame(self, padding=(16, 0, 12, 12))
        self.content_frame.grid(row=1, column=1, sticky="nsew")
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        self.log_frame = ttk.Frame(self, padding=(8, 10), style="Panel.TFrame")
        self._build_nav()
        self._build_top_bar()
        self._build_log_panel()
        self._place_log_panel()

    def _place_log_panel(self) -> None:
        self.log_frame.grid_forget()
        if self.log_panel_var.get() == "bottom":
            self.grid_columnconfigure(2, weight=0)
            self.grid_rowconfigure(2, weight=0)
            self.log_frame.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=(0, 8))
            self.log_frame.configure(height=180)
            self.log_frame.grid_propagate(False)
        else:
            self.grid_columnconfigure(2, weight=0)
            self.grid_rowconfigure(2, weight=0)
            self.log_frame.grid(row=0, column=2, rowspan=3, sticky="nsew")
            self.log_frame.configure(width=380)
            self.log_frame.grid_propagate(False)

    def _build_nav(self) -> None:
        ttk.Label(self.nav_frame, text="TG 控制台", font=("Microsoft YaHei UI", 13, "bold"), style="Panel.TLabel").pack(
            anchor="w", padx=14, pady=(16, 4)
        )
        ttk.Label(self.nav_frame, text="群组运营自动化", style="Panel.TLabel").pack(anchor="w", padx=14, pady=(0, 14))
        pages = [
            ("overview", "总览"),
            ("groups", "群组设置"),
            ("strategy", "转发策略"),
            ("accounts", "账号管理"),
            ("settings", "软件设置"),
            ("about", "关于软件"),
        ]
        for key, label in pages:
            button = ttk.Button(self.nav_frame, text=label, command=lambda name=key: self._show_page(name))
            button.pack(fill="x", padx=10, pady=4)
            self._nav_buttons[key] = button

        ttk.Separator(self.nav_frame).pack(fill="x", padx=10, pady=14)
        ttk.Label(self.nav_frame, text="主题", style="Panel.TLabel").pack(anchor="w", padx=14)
        for value, text in [("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")]:
            ttk.Radiobutton(self.nav_frame, text=text, value=value, variable=self.theme_var, command=self._on_theme_change).pack(
                anchor="w", padx=14, pady=2
            )

    def _build_top_bar(self) -> None:
        self.page_title_var = tk.StringVar(value="总览")
        self.page_desc_var = tk.StringVar(value="查看配置状态、账号池与运行提醒")
        ttk.Label(self.top_frame, textvariable=self.page_title_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.top_frame, textvariable=self.page_desc_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w")

        actions = ttk.Frame(self.top_frame)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self.status_badge_var = tk.StringVar(value="未运行")
        ttk.Label(actions, textvariable=self.status_badge_var).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="检查配置", width=7, style="Compact.TButton", command=self.validate_config).pack(side="left", padx=2)
        self.start_stop_button = ttk.Button(actions, text="开始监听", width=7, style="CompactAccent.TButton", command=self.toggle_monitoring)
        self.start_stop_button.pack(side="left", padx=3)

    def _build_log_panel(self) -> None:
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(2, weight=1)
        header = ttk.Frame(self.log_frame, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="运行日志", style="CardTitle.TLabel").pack(side="left")
        ttk.Checkbutton(header, text="自动滚动", variable=self.auto_scroll_var).pack(side="right")

        toolbar = ttk.Frame(self.log_frame, style="Panel.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        toolbar.grid_columnconfigure(1, weight=1, minsize=40)
        ttk.Combobox(
            toolbar,
            width=6,
            values=list(LOG_LEVEL_FILTERS.keys()),
            textvariable=self.log_filter_var,
            state="readonly",
        ).grid(row=0, column=0, sticky="w", padx=(0, 3))
        search = ttk.Entry(toolbar, textvariable=self.log_search_var)
        search.grid(row=0, column=1, sticky="ew", padx=3)
        search.bind("<KeyRelease>", lambda _event: self._render_logs())
        ttk.Button(toolbar, text="复制", width=4, style="Compact.TButton", command=self.copy_logs).grid(row=0, column=2, padx=(2, 0))
        ttk.Button(toolbar, text="导出", width=4, style="Compact.TButton", command=self.export_logs).grid(row=0, column=3, padx=(2, 0))
        ttk.Button(toolbar, text="清空", width=4, style="Compact.TButton", command=self.clear_logs).grid(row=0, column=4, padx=(2, 0))
        self.log_filter_var.trace_add("write", lambda *_: self._render_logs())

        self.log_text = tk.Text(self.log_frame, height=12, wrap="word", borderwidth=0, font=("Consolas", 9))
        self.log_text.grid(row=2, column=0, sticky="nsew")
        self.log_text.tag_configure("INFO", foreground="#93c5fd")
        self.log_text.tag_configure("OK", foreground="#86efac")
        self.log_text.tag_configure("SUCCESS", foreground="#86efac")
        self.log_text.tag_configure("WARNING", foreground="#fde68a")
        self.log_text.tag_configure("ERROR", foreground="#fca5a5")
        self.log_text.tag_configure("DEBUG", foreground="#c4b5fd")
        self.log_text.configure(state="disabled")

    def _build_pages(self) -> None:
        builders = {
            "overview": self._build_overview_page,
            "groups": self._build_groups_page,
            "strategy": self._build_strategy_page,
            "accounts": self._build_accounts_page,
            "settings": self._build_settings_page,
            "about": self._build_about_page,
        }
        for key, builder in builders.items():
            page = ScrollableFrame(self.content_frame)
            page.grid(row=0, column=0, sticky="nsew")
            builder(page.body)
            self._page_frames[key] = page

    def _show_page(self, key: str) -> None:
        for frame in self._page_frames.values():
            frame.grid_remove()
        self._page_frames[key].grid()
        title_desc = {
            "overview": ("总览", "查看首次配置引导、账号统计和当前任务摘要"),
            "groups": ("群组配置", "配置 Telegram API、代理、源群、目标群、过滤和替换规则"),
            "strategy": ("转发策略", "配置身份同步、频率、额度、分片和自适应节流"),
            "accounts": ("账号管理", "登录、导入、检测、删除和迁移账号"),
            "settings": ("软件设置", "配置主题、日志位置和运行目录"),
            "about": ("关于软件", "查看版本、目录和交付信息"),
        }
        self.page_title_var.set(title_desc[key][0])
        self.page_desc_var.set(title_desc[key][1])

    def _card(self, parent: tk.Widget, title: str, row: int, column: int = 0, colspan: int = 1) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        frame.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=4, pady=6)
        return frame

    def _build_overview_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        guide = self._card(parent, "首次配置引导", 0)
        steps = [
            "1. 在“群组配置”填写 API ID、API Hash、监听手机号和代理。",
            "2. 在“账号管理”登录监听账号，再登录或导入克隆账号。",
            "3. 配置源群、目标群、过滤词和替换规则后保存。",
            "4. 点击顶部“检查配置”，确认无缺项后点击“开始监听”。",
        ]
        for index, text in enumerate(steps):
            ttk.Label(guide, text=text, style="Panel.TLabel").grid(row=index, column=0, sticky="w", pady=2)

        stats = self._card(parent, "账号与任务概览", 1)
        for column in range(4):
            stats.grid_columnconfigure(column, weight=1)
        self.total_accounts_var = tk.StringVar(value="0")
        self.active_accounts_var = tk.StringVar(value="0")
        self.idle_accounts_var = tk.StringVar(value="0")
        self.banned_accounts_var = tk.StringVar(value="0")
        for column, (label, var) in enumerate(
            [
                ("账号总数", self.total_accounts_var),
                ("活跃账号", self.active_accounts_var),
                ("空闲账号", self.idle_accounts_var),
                ("封禁账号", self.banned_accounts_var),
            ]
        ):
            card = ttk.Frame(stats, padding=10, style="Panel.TFrame")
            card.grid(row=0, column=column, sticky="ew", padx=4)
            ttk.Label(card, text=label, style="Panel.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=var, font=("Microsoft YaHei UI", 18, "bold"), style="Panel.TLabel").pack(anchor="w")

        task = self._card(parent, "当前任务摘要", 2)
        self.task_summary_var = tk.StringVar(value="尚未开始监听")
        ttk.Label(task, textvariable=self.task_summary_var, style="Panel.TLabel", wraplength=760).grid(row=0, column=0, sticky="w")
        ttk.Button(task, text="保存当前配置", command=self.save_config).grid(row=1, column=0, sticky="w", pady=(10, 0))

        reminder = self._card(parent, "运行提醒", 3)
        reminder_text = "FloodWait、未授权、封禁、群组不可访问等异常会写入右侧日志；程序关闭时会主动停止监听任务并断开客户端。"
        ttk.Label(reminder, text=reminder_text, style="Panel.TLabel", wraplength=760).grid(row=0, column=0, sticky="w")

    def _build_groups_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)

        api = self._card(parent, "Telegram API", 0, 0)
        self._labeled_entry(api, "API ID", self.api_id_var, 0)
        self._labeled_entry(api, "API Hash", self.api_hash_var, 1, show=None)
        self._labeled_entry(api, "监听手机号", self.phone_var, 2)
        ttk.Label(api, text="监听账号会自动按手机号保存", style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(api, text="允许使用 Telegram Desktop 官方 API 作为兼容候选", variable=self.desktop_fallback_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        proxy = self._card(parent, "代理配置", 0, 1)
        ttk.Checkbutton(proxy, text="启用代理", variable=self.proxy_enabled_var).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(proxy, text="类型", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(proxy, values=["socks5", "socks4", "http"], textvariable=self.proxy_type_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=3
        )
        self._labeled_entry(proxy, "主机", self.proxy_host_var, 2)
        self._labeled_entry(proxy, "端口", self.proxy_port_var, 3)
        self._labeled_entry(proxy, "用户名", self.proxy_username_var, 4)
        self._labeled_entry(proxy, "密码", self.proxy_password_var, 5, show="*")
        proxy.grid_columnconfigure(1, weight=1)

        groups = self._card(parent, "群组配置", 1, 0, 2)
        groups.grid_columnconfigure(1, weight=1)
        ttk.Label(groups, text="源群（逗号或换行批量输入）", style="Panel.TLabel").grid(row=0, column=0, sticky="nw", pady=3)
        self.sources_text = tk.Text(groups, height=4, wrap="word")
        self.sources_text.insert("1.0", self._initial_sources)
        self.sources_text.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(groups, text="目标群", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(groups, textvariable=self.target_group_var).grid(row=1, column=1, sticky="ew", pady=3)
        action_bar = ttk.Frame(groups, style="Panel.TFrame")
        action_bar.grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Button(action_bar, text="测试目标群访问", command=self.test_target_access).pack(side="left", padx=(0, 6))
        ttk.Button(action_bar, text="尝试加入目标群", command=lambda: self.join_configured_groups(target_only=True)).pack(side="left", padx=6)
        ttk.Button(action_bar, text="尝试加入源群", command=lambda: self.join_configured_groups(target_only=False)).pack(side="left", padx=6)

        rules = self._card(parent, "过滤与替换", 2, 0, 2)
        rules.grid_columnconfigure(1, weight=1)
        rules.grid_columnconfigure(3, weight=1)
        ttk.Label(rules, text="黑名单用户 ID", style="Panel.TLabel").grid(row=0, column=0, sticky="nw", pady=3)
        self.blocked_users_text = tk.Text(rules, height=4, wrap="word")
        self.blocked_users_text.insert("1.0", self._initial_blocked_users)
        self.blocked_users_text.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=3)
        ttk.Label(rules, text="黑名单关键词", style="Panel.TLabel").grid(row=0, column=2, sticky="nw", pady=3)
        self.blocked_keywords_text = tk.Text(rules, height=4, wrap="word")
        self.blocked_keywords_text.insert("1.0", self._initial_blocked_keywords)
        self.blocked_keywords_text.grid(row=0, column=3, sticky="ew", pady=3)
        ttk.Label(rules, text="替换规则 old->new", style="Panel.TLabel").grid(row=1, column=0, sticky="nw", pady=3)
        self.replacements_text = tk.Text(rules, height=5, wrap="word")
        self.replacements_text.insert("1.0", self._initial_replacements)
        self.replacements_text.grid(row=1, column=1, columnspan=3, sticky="ew", pady=3)
        ttk.Label(rules, text="普通文本也兼容 old-new，例如 5-4", style="Muted.TLabel").grid(row=2, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(rules, text="普通文本替换", value="literal", variable=self.replacement_mode_var).grid(row=3, column=1, sticky="w")
        ttk.Radiobutton(rules, text="正则表达式", value="regex", variable=self.replacement_mode_var).grid(row=3, column=2, sticky="w")
        ttk.Checkbutton(rules, text="忽略大小写", variable=self.replacement_ignore_case_var).grid(row=3, column=3, sticky="w")

        footer = ttk.Frame(parent)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(footer, text="保存配置", style="Accent.TButton", command=self.save_config).pack(side="right", padx=4)

    def _build_strategy_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)

        identity = self._card(parent, "身份同步", 0, 0)
        ttk.Checkbutton(identity, text="同步昵称", variable=self.sync_name_var).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Checkbutton(identity, text="同步头像", variable=self.sync_avatar_var).grid(row=1, column=0, sticky="w", pady=3)
        self._labeled_entry(identity, "身份切换冷却（秒）", self.identity_cooldown_var, 2)

        quota = self._card(parent, "额度与分片", 0, 1)
        self._labeled_entry(quota, "每日克隆上限", self.daily_limit_var, 0)
        self._labeled_entry(quota, "分片总数", self.shard_total_var, 1)
        self._labeled_entry(quota, "当前分片编号", self.shard_index_var, 2)

        throttle = self._card(parent, "发送节流", 1, 0)
        self._labeled_entry(throttle, "最小发送间隔（秒）", self.send_min_var, 0)
        self._labeled_entry(throttle, "最大发送间隔（秒）", self.send_max_var, 1)
        ttk.Checkbutton(throttle, text="启用自适应节流", variable=self.adaptive_throttle_var).grid(row=2, column=0, columnspan=2, sticky="w")

        flood = self._card(parent, "FloodWait 惩罚", 1, 1)
        self._labeled_entry(flood, "惩罚等待（秒）", self.flood_penalty_var, 0)
        self._labeled_entry(flood, "最大间隔上限（秒）", self.max_interval_var, 1)
        ttk.Button(flood, text="保存策略", style="Accent.TButton", command=self.save_config).grid(row=2, column=1, sticky="e", pady=(8, 0))

    def _build_accounts_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(0, weight=1)
        search = ttk.Entry(toolbar, textvariable=self.account_search_var)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        search.bind("<KeyRelease>", lambda _event: self._render_accounts())
        ttk.Combobox(
            toolbar,
            width=8,
            values=["全部", "可用", "待检测", "未授权", "连接失败", "已封禁"],
            textvariable=self.account_filter_var,
            state="readonly",
        ).grid(row=0, column=1, padx=(0, 3))
        self.account_filter_var.trace_add("write", lambda *_: self._render_accounts())
        ttk.Button(toolbar, text="刷新", width=4, style="Compact.TButton", command=self._refresh_accounts).grid(row=0, column=2, padx=(2, 0))
        ttk.Button(toolbar, text="检测", width=4, style="Compact.TButton", command=self.inspect_selected_or_all).grid(row=0, column=3, padx=(2, 0))
        ttk.Button(toolbar, text="登录", width=4, style="CompactAccent.TButton", command=self.open_login_dialog).grid(row=0, column=4, padx=(2, 0))
        ttk.Button(toolbar, text="批量导入", width=7, style="Compact.TButton", command=self.import_session_dialog).grid(row=0, column=5, padx=(2, 0))
        ttk.Button(toolbar, text="删除", width=4, style="Compact.TButton", command=self.delete_selected_account).grid(row=0, column=6, padx=(2, 0))
        ttk.Button(toolbar, text="封禁", width=4, style="Compact.TButton", command=self.ban_selected_account).grid(row=0, column=7, padx=(2, 0))
        ttk.Button(toolbar, text="清头像", width=5, style="Compact.TButton", command=self.clear_avatar_cache).grid(row=0, column=8, padx=(2, 0))

        columns = ("role", "user", "phone", "status", "today", "last_active", "dir")
        self.accounts_tree = ttk.Treeview(parent, columns=columns, show="headings", height=14, selectmode="extended")
        headings = {
            "role": "角色",
            "user": "用户名",
            "phone": "手机号",
            "status": "状态",
            "today": "今日额度",
            "last_active": "最后活跃",
            "dir": "目录",
        }
        widths = {"role": 90, "user": 140, "phone": 150, "status": 90, "today": 80, "last_active": 170, "dir": 120}
        for column in columns:
            self.accounts_tree.heading(column, text=headings[column])
            self.accounts_tree.column(column, width=widths[column], anchor="w")
        self.accounts_tree.grid(row=1, column=0, sticky="nsew")
        parent.grid_rowconfigure(1, weight=1)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.accounts_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.accounts_tree.configure(yscrollcommand=scroll.set)
        self.accounts_tree.tag_configure("banned", foreground="#dc2626")
        self.accounts_tree.tag_configure("ok", foreground="#16a34a")
        self.accounts_tree.tag_configure("warn", foreground="#d97706")

        empty = ttk.Label(parent, text="暂无账号，登录第一个账号或导入现有 session。", style="Muted.TLabel")
        empty.grid(row=2, column=0, sticky="w", pady=6)
        self.accounts_empty_label = empty

    def _build_settings_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        theme = self._card(parent, "主题与日志", 0)
        ttk.Label(theme, text="主题", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        for column, (value, label) in enumerate([("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")], start=1):
            ttk.Radiobutton(theme, text=label, value=value, variable=self.theme_var, command=self._on_theme_change).grid(
                row=0, column=column, sticky="w", padx=6
            )
        ttk.Label(theme, text="日志位置", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Radiobutton(theme, text="右侧栏", value="right", variable=self.log_panel_var, command=self._on_log_panel_change).grid(
            row=1, column=1, sticky="w", pady=(8, 0)
        )
        ttk.Radiobutton(theme, text="底部栏", value="bottom", variable=self.log_panel_var, command=self._on_log_panel_change).grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(theme, text="保存设置", command=self.save_config).grid(row=2, column=0, sticky="w", pady=(12, 0))

        dirs = self._card(parent, "运行目录", 1)
        rows = [
            ("配置目录", self.paths.setting_dir),
            ("账号目录", self.paths.sessions_dir),
            ("封禁目录", self.paths.sessions_banned_dir),
            ("缓存目录", self.paths.cache_dir),
            ("导出目录", self.paths.exports_dir),
        ]
        for row, (label, path) in enumerate(rows):
            ttk.Label(dirs, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(dirs)
            entry.insert(0, str(path))
            entry.configure(state="readonly")
            entry.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
            ttk.Button(dirs, text="打开", command=lambda p=path: self.open_path(p)).grid(row=row, column=2, pady=3)
        dirs.grid_columnconfigure(1, weight=1)

    def _build_about_page(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        about = self._card(parent, "关于项目", 0)
        text = (
            f"{self.app_name} {self.version}\n"
            "这是面向 Telegram 群组运营的软件，支持配置保存、账号管理、验证码/扫码登录、"
            "源群监听、账号池轮换转发、日志导出。"
        )
        ttk.Label(about, text=text, style="Panel.TLabel", wraplength=760, justify="left").grid(row=0, column=0, sticky="w")
        paths = runtime_paths()
        path_text = f"程序目录：{paths.app_root}\n数据目录：{paths.data_root}\n配置文件：{paths.config_file}"
        entry = tk.Text(about, height=4, wrap="none")
        entry.insert("1.0", path_text)
        entry.configure(state="disabled")
        entry.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    def _labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int, show: str | None = None) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
        entry = ttk.Entry(parent, textvariable=var, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        parent.grid_columnconfigure(1, weight=1)
        return entry

    def _current_config_from_ui(self) -> dict[str, Any]:
        config = copy.deepcopy(self.config)
        monitor_session = session_name_from_phone(self.phone_var.get()) or self.monitor_session_var.get() or "monitor"
        api_id = self.api_id_var.get().strip() or TELEGRAM_DESKTOP_API_ID
        api_hash = self.api_hash_var.get().strip() or TELEGRAM_DESKTOP_API_HASH
        config.setdefault("telegram", {}).update(
            {
                "api_id": api_id,
                "api_hash": api_hash,
                "phone": self.phone_var.get().strip(),
                "monitor_session": monitor_session,
                "use_desktop_fallback": bool(self.desktop_fallback_var.get()),
            }
        )
        config.setdefault("proxy", {}).update(
            {
                "enabled": bool(self.proxy_enabled_var.get()),
                "type": self.proxy_type_var.get(),
                "host": self.proxy_host_var.get().strip(),
                "port": self.proxy_port_var.get().strip(),
                "username": self.proxy_username_var.get().strip(),
                "password": self.proxy_password_var.get(),
            }
        )
        config.setdefault("groups", {}).update(
            {
                "sources": normalize_sources(self.sources_text.get("1.0", "end")),
                "target": self.target_group_var.get().strip(),
            }
        )
        config.setdefault("filters", {}).update(
            {
                "blocked_user_ids": parse_int_list(self.blocked_users_text.get("1.0", "end")),
                "blocked_keywords": lines_to_list(self.blocked_keywords_text.get("1.0", "end")),
            }
        )
        replacements = parse_replacement_lines(self.replacements_text.get("1.0", "end"), self.replacement_mode_var.get())
        for item in replacements:
            item["ignore_case"] = bool(self.replacement_ignore_case_var.get())
        config["replacements"] = replacements
        config.setdefault("strategy", {}).update(
            {
                "sync_name": bool(self.sync_name_var.get()),
                "sync_avatar": bool(self.sync_avatar_var.get()),
                "identity_sync_user_set": True,
                "identity_cooldown_seconds": self._int_var(self.identity_cooldown_var, 180),
                "daily_account_limit": self._int_var(self.daily_limit_var, 200),
                "shard_total": max(1, self._int_var(self.shard_total_var, 1)),
                "shard_index": max(0, self._int_var(self.shard_index_var, 0)),
                "send_interval_min": self._float_var(self.send_min_var, 2.0),
                "send_interval_max": self._float_var(self.send_max_var, 5.0),
                "adaptive_throttle": bool(self.adaptive_throttle_var.get()),
                "floodwait_penalty_seconds": self._int_var(self.flood_penalty_var, 60),
                "max_interval_seconds": self._int_var(self.max_interval_var, 600),
                "replacement_mode": self.replacement_mode_var.get(),
            }
        )
        config.setdefault("runtime", {}).update(
            {
                "theme": self.theme_var.get(),
                "log_panel": self.log_panel_var.get(),
                "log_panel_user_set": bool(config.get("runtime", {}).get("log_panel_user_set", False)),
                "selected_accounts": [Path(item).name for item in self.accounts_tree.selection()] if hasattr(self, "accounts_tree") else [],
            }
        )
        return config

    def _int_var(self, var: tk.StringVar, default: int) -> int:
        try:
            return int(float(var.get()))
        except ValueError:
            return default

    def _float_var(self, var: tk.StringVar, default: float) -> float:
        try:
            return float(var.get())
        except ValueError:
            return default

    def save_config(self) -> None:
        self.config = self._current_config_from_ui()
        self.api_id_var.set(str(self.config.get("telegram", {}).get("api_id", TELEGRAM_DESKTOP_API_ID)))
        self.api_hash_var.set(str(self.config.get("telegram", {}).get("api_hash", TELEGRAM_DESKTOP_API_HASH)))
        self.store.save(self.config)
        self.log_bus.ok("配置已保存")
        self._refresh_task_summary()

    def validate_config(self) -> bool:
        config = self._current_config_from_ui()
        errors: list[str] = []
        telegram = config.get("telegram", {})
        if not telegram.get("api_id") or not telegram.get("api_hash"):
            if not telegram.get("use_desktop_fallback"):
                errors.append("未填写 API ID/API Hash，且未启用 Desktop API 兼容候选")
        if not config.get("groups", {}).get("sources"):
            errors.append("未配置源群")
        if not config.get("groups", {}).get("target"):
            errors.append("未配置目标群")
        monitor = self.paths.sessions_dir / f"{telegram.get('monitor_session', 'monitor')}.session"
        if not monitor.exists():
            errors.append(f"未找到监听账号 session：{monitor.name}")
        if not [record for record in self.account_manager.scan(config) if record.directory == "sessions" and record.role != "监听账号"]:
            errors.append("未找到克隆账号 session")
        if errors:
            for error in errors:
                self.log_bus.warning(error)
            messagebox.showwarning("配置未完成", "\n".join(errors))
            return False
        self.log_bus.ok("配置检查通过，可以开始监听")
        messagebox.showinfo("检查通过", "配置检查通过，可以开始监听。")
        return True

    def test_target_access(self) -> None:
        self.save_config()
        future = self.worker.submit(self._async_test_target_access(self.config))
        self._watch_future(future, lambda message: self.log_bus.ok(message), "测试目标群访问失败")

    async def _async_test_target_access(self, config: dict[str, Any]) -> str:
        from app.core.telethon_compat import api_candidates, connect_client_with_repair, safe_disconnect
        from app.core.account_manager import read_metadata

        target = str(config.get("groups", {}).get("target") or "").strip()
        if not target:
            raise RuntimeError("目标群为空")
        monitor_name = str(config.get("telegram", {}).get("monitor_session") or "monitor").removesuffix(".session")
        session_file = self.paths.sessions_dir / f"{monitor_name}.session"
        if not session_file.exists():
            raise RuntimeError(f"未找到监听账号 session：{session_file.name}")
        meta = read_metadata(session_file)
        last_error = ""
        for api in api_candidates(config, meta):
            client = None
            try:
                client = await connect_client_with_repair(session_file, api, config, receive_updates=False)
                if not await client.is_user_authorized():
                    raise RuntimeError("监听账号未授权")
                await client.get_entity(target)
                return f"目标群可访问，使用 {api.source}"
            except Exception as exc:
                last_error = chinese_error(exc)
            finally:
                if client:
                    await safe_disconnect(client)
        raise RuntimeError(last_error or "目标群访问失败")

    def join_configured_groups(self, target_only: bool) -> None:
        self.save_config()
        future = self.worker.submit(self._async_join_groups(self.config, target_only))
        label = "加入目标群" if target_only else "加入源群"
        self._watch_future(future, lambda message: self.log_bus.ok(message), f"{label}失败")

    async def _async_join_groups(self, config: dict[str, Any], target_only: bool) -> str:
        from app.core.telethon_compat import api_candidates, connect_client_with_repair, functions, safe_disconnect
        from app.core.account_manager import read_metadata

        if functions is None:
            raise RuntimeError("Telethon 不可用")
        groups = [str(config.get("groups", {}).get("target") or "").strip()] if target_only else normalize_sources(config.get("groups", {}).get("sources", []))
        groups = [item for item in groups if item]
        if not groups:
            raise RuntimeError("没有可加入的群组")
        records = [record for record in self.account_manager.scan(config) if record.directory == "sessions"]
        success = 0
        for record in records:
            meta = read_metadata(record.path)
            for api in api_candidates(config, meta):
                client = None
                try:
                    client = await connect_client_with_repair(record.path, api, config, receive_updates=False)
                    if not await client.is_user_authorized():
                        continue
                    for group in groups:
                        try:
                            await client(functions.channels.JoinChannelRequest(group))
                            success += 1
                        except Exception as exc:
                            self.log_bus.debug(f"{record.name} 加入 {group} 跳过：{chinese_error(exc)}")
                    break
                finally:
                    if client:
                        await safe_disconnect(client)
        return f"加入任务完成，成功请求 {success} 次"

    def toggle_monitoring(self) -> None:
        if self.forwarder.running:
            self.status_badge_var.set("停止中")
            self.start_stop_button.configure(state="disabled")
            self.worker.call_soon(self.forwarder.request_stop)
            self.log_bus.info("正在停止监听任务")
            return

        self.save_config()
        if not self.validate_config():
            return
        selected_paths = [Path(item) for item in self.accounts_tree.selection()] if hasattr(self, "accounts_tree") else []
        self.start_stop_button.configure(text="停止监听")
        self.status_badge_var.set("运行中")
        self.task_summary_var.set("监听任务正在运行")
        self._monitor_future = self.worker.submit(self.forwarder.run(self.config, selected_paths))
        self._watch_future(self._monitor_future, self._monitor_finished, "监听任务异常", reset_monitor_on_error=True)
        self.log_bus.info("已提交监听任务")

    def _monitor_finished(self, _result: Any) -> None:
        self.start_stop_button.configure(text="开始监听", state="normal")
        self.status_badge_var.set("未运行")
        self.task_summary_var.set("监听任务已停止")
        self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        self.accounts = self.account_manager.scan(self._current_config_from_ui() if hasattr(self, "sources_text") else self.config)
        self._render_accounts()
        self._refresh_account_stats()

    def _render_accounts(self) -> None:
        if not hasattr(self, "accounts_tree"):
            return
        self.accounts_tree.delete(*self.accounts_tree.get_children())
        keyword = self.account_search_var.get().strip().lower()
        status_filter = self.account_filter_var.get()
        count = 0
        for record in self.accounts:
            haystack = " ".join([record.name, record.role, record.user, record.phone, record.status, record.directory]).lower()
            if keyword and keyword not in haystack:
                continue
            if status_filter != "全部" and record.status != status_filter:
                continue
            tag = "ok" if record.status == "可用" else "banned" if record.status == "已封禁" else "warn"
            self.accounts_tree.insert(
                "",
                "end",
                iid=str(record.path),
                values=(
                    record.role,
                    record.user or record.name,
                    record.phone or record.name,
                    record.status,
                    record.today_count,
                    record.last_active,
                    record.directory,
                ),
                tags=(tag,),
            )
            count += 1
        if hasattr(self, "accounts_empty_label"):
            self.accounts_empty_label.configure(text="" if count else "暂无账号，登录第一个账号或导入现有 session。")

    def _refresh_account_stats(self) -> None:
        total = len([record for record in self.accounts if record.directory == "sessions"])
        active = len([record for record in self.accounts if record.status == "可用" and record.directory == "sessions"])
        banned = len([record for record in self.accounts if record.directory == "sessions_banned" or record.status == "已封禁"])
        idle = max(0, total - active)
        if hasattr(self, "total_accounts_var"):
            self.total_accounts_var.set(str(total))
            self.active_accounts_var.set(str(active))
            self.idle_accounts_var.set(str(idle))
            self.banned_accounts_var.set(str(banned))

    def _refresh_task_summary(self) -> None:
        if hasattr(self, "task_summary_var"):
            sources = normalize_sources(self.config.get("groups", {}).get("sources", []))
            target = self.config.get("groups", {}).get("target") or "未配置"
            self.task_summary_var.set(f"源群 {len(sources)} 个，目标群：{target}。监听状态：{'运行中' if self.forwarder.running else '未运行'}")

    def selected_account_paths(self) -> list[Path]:
        if not hasattr(self, "accounts_tree"):
            return []
        return [Path(item) for item in self.accounts_tree.selection()]

    def inspect_selected_or_all(self) -> None:
        self.save_config()
        selected = self.selected_account_paths()
        targets = selected or [record.path for record in self.accounts if record.directory == "sessions"]
        if not targets:
            self.log_bus.warning("没有可检测的 session")
            return
        self.log_bus.info(f"开始检测 {len(targets)} 个 session 授权状态")
        future = self.worker.submit(self._async_inspect_sessions(targets, self.config))
        self._watch_future(future, lambda _: self._refresh_accounts(), "检测授权状态失败")

    async def _async_inspect_sessions(self, targets: list[Path], config: dict[str, Any]) -> None:
        for path in targets:
            try:
                meta = await self.account_manager.inspect_session(path, config)
                api_source = meta.get("api_source") or "未确定"
                self.log_bus.info(f"{path.name} 状态：{meta.get('status', '未知')}；API：{api_source}")
            except Exception as exc:
                self.log_bus.warning(f"{path.name} 检测失败：{chinese_error(exc)}")

    def open_login_dialog(self) -> None:
        if self.login_dialog is not None and self.login_dialog.winfo_exists():
            self.login_dialog.show_window()
            return
        self.login_dialog = LoginDialog(self)

    def import_session_dialog(self) -> None:
        paths = filedialog.askopenfilenames(title="选择一个或多个 .session 文件", filetypes=[("Telegram session", "*.session")])
        if not paths:
            return
        role = simpledialog.askstring("账号角色", "请输入角色：监听账号 或 克隆账号", initialvalue="克隆账号", parent=self)
        if not role:
            return
        imported: list[Path] = []
        errors: list[str] = []
        config = self._current_config_from_ui()
        try:
            for raw_path in paths:
                try:
                    target = self.account_manager.import_session(Path(raw_path), role=role)
                    imported.append(target)
                    self.log_bus.ok(f"已导入 session：{target.name}")
                except Exception as exc:
                    errors.append(f"{Path(raw_path).name}：{exc}")
                    self.log_bus.error(f"导入失败 {Path(raw_path).name}：{exc}")
            self._refresh_accounts()
            if imported:
                self.log_bus.info(
                    f"已批量导入 {len(imported)} 个 session，开始检查账号状态"
                )
                future = self.worker.submit(self._async_inspect_sessions(imported, config))
                self._watch_future(future, lambda _: self._refresh_accounts(), "导入后批量授权检测失败")
            if errors:
                messagebox.showwarning("部分导入失败", "\n".join(errors[:10]))
        except Exception as exc:
            self.log_bus.error(f"导入失败：{exc}")
            messagebox.showerror("导入失败", str(exc))

    def delete_selected_account(self) -> None:
        paths = self.selected_account_paths()
        if not paths:
            self.log_bus.warning("请先选择要删除的账号")
            return
        if not messagebox.askyesno("二次确认", f"确定删除选中的 {len(paths)} 个 session 及同名 json/journal 文件吗？"):
            return
        self._release_pending_auth_for_sessions(paths)
        deleted_count = 0
        for path in paths:
            try:
                deleted = self.account_manager.delete_session(path)
                deleted_count += len(deleted)
            except Exception as exc:
                self.log_bus.error(f"删除 {path.name} 失败：{exc}")
        self.log_bus.ok(f"删除完成，共删除 {deleted_count} 个文件")
        self._refresh_accounts()

    def _release_pending_auth_for_sessions(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                future = self.worker.submit(self.auth_service.cancel(path.stem, cleanup_qr=path.stem == "qr_pending"))
                future.result(timeout=3)
            except Exception as exc:
                self.log_bus.warning(f"释放 {path.name} 登录占用失败：{chinese_error(exc)}")

    def ban_selected_account(self) -> None:
        paths = self.selected_account_paths()
        if not paths:
            self.log_bus.warning("请先选择要迁移的账号")
            return
        for path in paths:
            try:
                target = self.account_manager.ban_session(path, "手动迁移")
                self.log_bus.ok(f"已迁移到封禁目录：{target.name}")
            except Exception as exc:
                self.log_bus.error(f"迁移 {path.name} 失败：{exc}")
        self._refresh_accounts()

    def clear_avatar_cache(self) -> None:
        count = self.account_manager.clear_avatar_cache()
        self.log_bus.ok(f"已清空头像缓存：{count} 项")

    def copy_logs(self) -> None:
        text = "\n".join(self._format_log_record(record) for record in self._filtered_logs())
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log_bus.ok("日志已复制到剪贴板")

    def export_logs(self) -> None:
        target = self.log_bus.export(self._filtered_logs())
        self.log_bus.ok(f"日志已导出：{target}")

    def clear_logs(self) -> None:
        self.log_bus.clear()
        self._render_logs()

    def _filtered_logs(self) -> list[LogRecord]:
        selected_level = self.log_filter_var.get()
        levels = LOG_LEVEL_FILTERS.get(selected_level)
        if levels is None and selected_level not in LOG_LEVEL_FILTERS and selected_level != "全部":
            levels = {selected_level}
        keyword = self.log_search_var.get().strip().lower()
        records = []
        for record in self.log_bus.records():
            if levels is not None and record.level not in levels:
                continue
            formatted = self._format_log_record(record)
            if keyword and keyword not in formatted.lower() and keyword not in record.format().lower():
                continue
            records.append(record)
        return records

    def _format_log_record(self, record: LogRecord) -> str:
        label = LOG_LEVEL_LABELS.get(record.level, record.level)
        return f"{record.time.strftime('%H:%M:%S')} [{label}] {record.message}"

    def _render_logs(self) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for record in self._filtered_logs()[-1000:]:
            line = self._format_log_record(record) + "\n"
            self.log_text.insert("end", line, record.level)
        self.log_text.configure(state="disabled")
        if self.auto_scroll_var.get():
            self.log_text.see("end")

    def _poll_logs(self) -> None:
        records = self.log_bus.drain()
        if records:
            self._render_logs()
        self.after(200, self._poll_logs)

    def _watch_future(
        self,
        future: Future[Any],
        on_success: Callable[[Any], None] | None = None,
        error_prefix: str = "任务失败",
        reset_monitor_on_error: bool = False,
    ) -> None:
        def poll() -> None:
            if future.done():
                try:
                    result = future.result()
                except Exception as exc:
                    self.log_bus.error(f"{error_prefix}：{chinese_error(exc)}")
                    if reset_monitor_on_error:
                        self.start_stop_button.configure(state="normal", text="开始监听")
                        self.status_badge_var.set("未运行")
                else:
                    if on_success:
                        on_success(result)
                return
            self.after(150, poll)

        self.after(150, poll)

    def _on_theme_change(self) -> None:
        self._apply_theme()
        self.save_config()

    def _on_log_panel_change(self) -> None:
        self.config.setdefault("runtime", {})["log_panel_user_set"] = True
        self._place_log_panel()
        self.save_config()

    def open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True) if path.suffix == "" else path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def on_close(self) -> None:
        try:
            if self.forwarder.running:
                self.worker.call_soon(self.forwarder.request_stop)
            try:
                future = self.worker.submit(self.auth_service.close())
                future.result(timeout=2)
            except Exception:
                pass
            self.worker.close()
        finally:
            self.destroy()


class LoginDialog(tk.Toplevel):
    def __init__(self, app: TelegramClonerApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("登录账号")
        self.geometry("720x640")
        self.minsize(640, 560)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.pending_phone_key: str | None = None
        self.pending_qr_key: str | None = None

        self.role_var = tk.StringVar(value="克隆账号")
        self.phone_var = tk.StringVar(value=app.phone_var.get())
        self.code_var = tk.StringVar(value="")
        self.phone_password_var = tk.StringVar(value="")
        self.qr_password_var = tk.StringVar(value="")
        self.import_role_var = tk.StringVar(value="克隆账号")
        self.phone_waiting_password = False
        self.qr_waiting_password = False
        self.qr_photo: Any | None = None

        self._build()
        self.after(80, self.show_window)

    def show_window(self) -> None:
        if not self.winfo_exists():
            return
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(500, lambda: self.attributes("-topmost", False) if self.winfo_exists() else None)
        except tk.TclError:
            return

    def close(self) -> None:
        self._cancel_pending_logins()
        self.app.login_dialog = None
        self.destroy()

    def _cancel_pending_logins(self) -> None:
        keys = [self.pending_phone_key, self.pending_qr_key]
        for key in [item for item in keys if item]:
            try:
                future = self.app.worker.submit(self.app.auth_service.cancel(key, cleanup_qr=key == "qr_pending"))
                future.result(timeout=3)
            except Exception as exc:
                self.app.log_bus.warning(f"取消未完成登录失败：{chinese_error(exc)}")

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        role_bar = ttk.Frame(self, padding=10)
        role_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(role_bar, text="账号角色").pack(side="left")
        ttk.Combobox(role_bar, values=["监听账号", "克隆账号"], textvariable=self.role_var, state="readonly", width=12).pack(
            side="left", padx=8
        )
        ttk.Label(role_bar, text="账号会自动按手机号保存").pack(side="left", padx=8)

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        phone_tab = ttk.Frame(notebook, padding=12)
        qr_tab = ttk.Frame(notebook, padding=12)
        import_tab = ttk.Frame(notebook, padding=12)
        notebook.add(phone_tab, text="手机验证码登录")
        notebook.add(qr_tab, text="扫码登录")
        notebook.add(import_tab, text="导入现有 session")
        self._build_phone_tab(phone_tab)
        self._build_qr_tab(qr_tab)
        self._build_import_tab(import_tab)

    def _build_phone_tab(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(1, weight=1)
        self._entry(parent, "手机号", self.phone_var, 0)
        ttk.Label(parent, text="验证码", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.code_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(parent, text="二级验证密码", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.phone_password_entry = ttk.Entry(parent, textvariable=self.phone_password_var, show="*")
        self.phone_password_entry.grid(row=2, column=1, sticky="ew", pady=6)
        tips = (
            "提示：如果验证码类型是 App，请到已登录 Telegram 客户端查看验证码；"
            "验证码输入框也支持输入 resend 重新请求，输入 sms 尝试短信通道。"
            "如果账号开启了两步验证，请在“二级验证密码”中输入 Telegram 云密码。"
            "登录文件会自动按手机号保存。"
        )
        ttk.Label(parent, text=tips, wraplength=520).grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        self.phone_status_var = tk.StringVar(value="等待请求验证码")
        ttk.Label(parent, textvariable=self.phone_status_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        buttons = ttk.Frame(parent)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(buttons, text="获取验证码", command=lambda: self.request_code(force_sms=False)).pack(side="left", padx=4)
        ttk.Button(buttons, text="请求短信", command=lambda: self.request_code(force_sms=True)).pack(side="left", padx=4)
        ttk.Button(buttons, text="完成登录", style="Accent.TButton", command=self.complete_phone_login).pack(side="left", padx=4)

    def _build_qr_tab(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        ttk.Button(parent, text="生成/刷新二维码", style="Accent.TButton", command=self.start_qr_login).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=8
        )
        qr_box = ttk.Frame(parent, padding=10)
        qr_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 8))
        qr_box.grid_columnconfigure(0, weight=1)
        self.qr_image_label = ttk.Label(qr_box, text="点击“生成/刷新二维码”后，这里会显示可直接扫描的二维码。", anchor="center")
        self.qr_image_label.grid(row=0, column=0)
        ttk.Label(parent, text="二级验证密码").grid(row=2, column=0, sticky="w", pady=6, padx=(0, 8))
        self.qr_password_entry = ttk.Entry(parent, textvariable=self.qr_password_var, show="*")
        self.qr_password_entry.grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(parent, text="请用手机 Telegram：设置 > 设备 > 连接桌面设备，直接扫描上方二维码。登录成功后账号文件会自动按手机号保存，下方链接仅作为复制备用。").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=6
        )
        self.qr_text = tk.Text(parent, height=3, wrap="word")
        self.qr_text.grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        buttons = ttk.Frame(parent)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="复制链接", command=self.copy_qr_link).pack(side="left", padx=4)
        ttk.Button(buttons, text="完成二级验证", command=self.complete_qr_password).pack(side="left", padx=4)
        self.qr_status_var = tk.StringVar(value="等待生成二维码")
        ttk.Label(parent, textvariable=self.qr_status_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=8)

    def _build_import_tab(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        ttk.Label(parent, text="可一次选择多个 .session 文件，程序会复制到 sessions 目录；同名 .json 会一并导入。").grid(
            row=0, column=0, sticky="w", pady=8
        )
        ttk.Button(parent, text="批量选择并导入 session", style="Accent.TButton", command=self.import_session).grid(row=1, column=0, sticky="w")

    def _entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 8))
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=6)

    def request_code(self, force_sms: bool) -> None:
        phone = self.phone_var.get().strip()
        self.phone_waiting_password = False
        self.phone_status_var.set("正在请求验证码...")
        future = self.app.worker.submit(
            self.app.auth_service.request_phone_code(phone, self.role_var.get(), self.app._current_config_from_ui(), force_sms)
        )
        self._watch(
            future,
            self._phone_code_requested,
            lambda exc: self.phone_status_var.set(f"请求失败：{chinese_error(exc)}"),
        )

    def _phone_code_requested(self, result: dict[str, Any]) -> None:
        self.pending_phone_key = result["key"]
        self.phone_status_var.set(f"验证码类型：{result['code_type']}；API：{result['api_source']}；{result['message']}")
        self.app.log_bus.info(self.phone_status_var.get())

    def complete_phone_login(self) -> None:
        if self.phone_waiting_password:
            self.complete_phone_password()
            return
        code = self.code_var.get().strip()
        if code.lower() == "resend":
            self.request_code(force_sms=False)
            return
        if code.lower() == "sms":
            self.request_code(force_sms=True)
            return
        if not self.pending_phone_key:
            self.phone_status_var.set("请先获取验证码")
            return
        future = self.app.worker.submit(self.app.auth_service.complete_phone_login(self.pending_phone_key, code))
        self._watch(future, self._phone_login_completed, lambda exc: self.phone_status_var.set(f"登录失败：{chinese_error(exc)}"))

    def _phone_login_completed(self, result: dict[str, Any]) -> None:
        if result.get("need_password"):
            self.phone_waiting_password = True
            self.phone_status_var.set(result.get("message", "账号开启了两步验证，请输入二级验证密码后再次点击完成登录"))
            self.phone_password_entry.focus_set()
            if self.phone_password_var.get().strip():
                self.complete_phone_password()
            return
        self.phone_waiting_password = False
        self._apply_monitor_login_result(result)
        self.phone_status_var.set(f"登录成功：{result.get('session')}")
        self.app.log_bus.ok(self.phone_status_var.get())
        self.app._refresh_accounts()

    def complete_phone_password(self) -> None:
        password = self.phone_password_var.get()
        if not password.strip() or not self.pending_phone_key:
            self.phone_status_var.set("请输入二级验证密码后再完成登录")
            self.phone_password_entry.focus_set()
            return
        future = self.app.worker.submit(self.app.auth_service.complete_phone_password(self.pending_phone_key, password))
        self._watch(future, self._phone_login_completed, lambda exc: self.phone_status_var.set(f"二级验证失败：{chinese_error(exc)}"))

    def start_qr_login(self) -> None:
        self.qr_status_var.set("正在生成扫码链接...")
        future = self.app.worker.submit(
            self.app.auth_service.start_qr_login(self.role_var.get(), self.app._current_config_from_ui())
        )
        self._watch(future, self._qr_started, lambda exc: self.qr_status_var.set(f"生成失败：{chinese_error(exc)}"))

    def _qr_started(self, result: dict[str, Any]) -> None:
        self.pending_qr_key = result["key"]
        self.qr_waiting_password = False
        self.qr_text.delete("1.0", "end")
        self.qr_text.insert("1.0", result["url"])
        self._render_qr_image(result["url"])
        self.qr_status_var.set(f"二维码已生成，API：{result['api_source']}，请用手机 Telegram 扫描确认...")
        self.app.log_bus.info(self.qr_status_var.get())
        future = self.app.worker.submit(self.app.auth_service.wait_qr_login(self.pending_qr_key))
        self._watch(future, self._qr_completed, lambda exc: self.qr_status_var.set(f"扫码失败：{chinese_error(exc)}"))

    def _render_qr_image(self, url: str) -> None:
        try:
            import qrcode
            from PIL import ImageTk

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=3,
            )
            qr.add_data(url)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((260, 260))
            self.qr_photo = ImageTk.PhotoImage(image)
            self.qr_image_label.configure(image=self.qr_photo, text="")
        except Exception as exc:
            self.qr_photo = None
            self.qr_image_label.configure(image="", text="二维码生成失败，请复制下方链接登录。")
            self.app.log_bus.warning(f"二维码图片生成失败：{exc}")

    def _qr_completed(self, result: dict[str, Any]) -> None:
        if result.get("need_password"):
            self.qr_waiting_password = True
            self.qr_status_var.set(result.get("message", "扫码已确认，账号开启了两步验证，请输入二级验证密码"))
            self.qr_password_entry.focus_set()
            if self.qr_password_var.get().strip():
                self.complete_qr_password()
            return
        self.qr_waiting_password = False
        self._apply_monitor_login_result(result)
        self.qr_status_var.set(f"扫码登录成功：{result.get('session')}")
        self.app.log_bus.ok(self.qr_status_var.get())
        self.app._refresh_accounts()

    def _apply_monitor_login_result(self, result: dict[str, Any]) -> None:
        if self.role_var.get() != "监听账号":
            return
        session_name = Path(str(result.get("session") or "")).stem
        if session_name:
            self.app.monitor_session_var.set(session_name)
        phone = str(result.get("phone") or "").strip()
        if phone:
            self.app.phone_var.set(phone)
        self.app.save_config()

    def complete_qr_password(self) -> None:
        if not self.pending_qr_key:
            self.qr_status_var.set("请先生成扫码链接并完成手机确认")
            return
        password = self.qr_password_var.get()
        if not password.strip():
            self.qr_status_var.set("请输入二级验证密码")
            self.qr_password_entry.focus_set()
            return
        future = self.app.worker.submit(self.app.auth_service.complete_qr_password(self.pending_qr_key, password))
        self._watch(future, self._qr_completed, lambda exc: self.qr_status_var.set(f"二级验证失败：{chinese_error(exc)}"))

    def copy_qr_link(self) -> None:
        text = self.qr_text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.qr_status_var.set("扫码链接已复制")

    def import_session(self) -> None:
        self.app.import_session_dialog()

    def _watch(self, future: Future[Any], on_success: Callable[[Any], None], on_error: Callable[[BaseException], None]) -> None:
        def poll() -> None:
            if not self.winfo_exists():
                return
            if future.done():
                try:
                    result = future.result()
                except Exception as exc:
                    on_error(exc)
                    self.app.log_bus.error(chinese_error(exc))
                else:
                    on_success(result)
                return
            self.after(150, poll)

        self.after(150, poll)
