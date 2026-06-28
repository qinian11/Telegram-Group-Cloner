# -*- coding: utf-8 -*-
import os
import time
from tkinter import messagebox, ttk

import customtkinter as ctk


class PoolTabMixin:
    def _build_pool_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(tab, corner_radius=18)
        card.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="账号池", font=self.font_lg).grid(row=0, column=0, sticky="w")
        self.pool_summary_label = ctk.CTkLabel(
            header,
            text="显示 0/0 个账号",
            font=self.font_xs,
            text_color=("#64748B", "#94A3B8"),
        )
        self.pool_summary_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        toolbar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(toolbar, text="筛选", font=self.font_xs).grid(row=0, column=0, sticky="w")
        self.pool_filter_entry = ctk.CTkEntry(
            toolbar,
            textvariable=self.pool_filter_var,
            height=32,
            placeholder_text="手机号 / Session / 用户 ID / 状态 / 目录",
            font=self.font_sm,
        )
        self.pool_filter_entry.grid(row=0, column=1, sticky="ew", padx=(8, 10))
        ctk.CTkButton(
            toolbar,
            text="刷新",
            width=72,
            height=32,
            command=lambda: self._refresh_pool_view(schedule_next=False),
            font=self.font_xs,
            fg_color=("#475569", "#334155"),
            hover_color=("#334155", "#1F2937"),
        ).grid(row=0, column=2, padx=(0, 6))
        self.delete_account_btn = ctk.CTkButton(
            toolbar,
            text="删除账号",
            width=94,
            height=32,
            command=self._delete_selected_account,
            font=self.font_xs,
            fg_color=("#A63D40", "#7F1D1D"),
            hover_color=("#922D31", "#6B1111"),
        )
        self.delete_account_btn.grid(row=0, column=3)

        table_card = ctk.CTkFrame(card, corner_radius=14)
        table_card.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_card,
            columns=("phone", "user_id", "last_used", "last_switch", "daily", "state", "folder"),
            show="headings",
            height=16,
            style="Pool.Treeview",
        )
        headings = {
            "phone": "手机号 / Session",
            "user_id": "绑定用户 ID",
            "last_used": "最后活跃",
            "last_switch": "最后切换",
            "daily": "当日额度",
            "state": "状态",
            "folder": "目录",
        }
        for key, text in headings.items():
            self.tree.heading(key, text=text)
        self.tree.column("phone", width=168, anchor="center")
        self.tree.column("user_id", width=118, anchor="center")
        self.tree.column("last_used", width=158, anchor="center")
        self.tree.column("last_switch", width=158, anchor="center")
        self.tree.column("daily", width=88, anchor="center")
        self.tree.column("state", width=86, anchor="center")
        self.tree.column("folder", width=110, anchor="center")
        self.tree.tag_configure("active", foreground="#86EFAC")
        self.tree.tag_configure("idle", foreground="#CBD5E1")
        self.tree.tag_configure("banned", foreground="#FCA5A5")

        scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _refresh_pool_view(self, schedule_next=True):
        if not self._ui_alive():
            return
        try:
            snapshot = self.cloner.snapshot_pool()
            previous_selection = set()
            if getattr(self, "tree", None) is not None:
                for item_id in self.tree.selection():
                    values = self.tree.item(item_id, "values")
                    if values:
                        previous_selection.add(str(values[0]))
            for item in self.tree.get_children():
                self.tree.delete(item)

            snapshot.sort(
                key=lambda item: (
                    item.get("banned", False),
                    item.get("user_id") is None,
                    str(item.get("phone") or item.get("session_name") or ""),
                )
            )

            def fmt(ts):
                if not ts:
                    return "-"
                try:
                    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                except Exception:
                    return "-"

            keyword = self.pool_filter_var.get().strip().lower()
            daily_limit = self.config_obj.getint("strategy", "daily_clone_limit", fallback=30)
            visible = 0
            for row in snapshot:
                user_id = row.get("user_id")
                banned = row.get("banned", False)
                loaded = row.get("loaded", False)
                has_json = row.get("has_json", False)
                folder = row.get("folder") or ("sessions_banned" if banned else "sessions")
                phone = row.get("phone") or row.get("session_name") or "未知"
                if banned:
                    status_text = "已封禁"
                elif user_id:
                    status_text = "使用中"
                elif loaded:
                    status_text = "已加载"
                elif has_json:
                    status_text = "未加载(JSON)"
                else:
                    status_text = "未加载"
                searchable = f"{phone} {user_id or ''} {status_text} {folder}".lower()
                if keyword and keyword not in searchable:
                    continue
                tag = "banned" if banned else ("active" if user_id else "idle")
                item_id = f"{folder}:{phone}"
                self.tree.insert(
                    "",
                    "end",
                    iid=item_id,
                    values=(
                        phone,
                        str(user_id) if user_id else "-",
                        fmt(row.get("last_used")),
                        fmt(row.get("last_identity_switch")),
                        f"{row.get('daily_clones', 0)}/{daily_limit}",
                        status_text,
                        folder,
                    ),
                    tags=(tag,),
                )
                if str(phone) in previous_selection:
                    self.tree.selection_add(item_id)
                visible += 1

            if self.pool_summary_label is not None:
                self.pool_summary_label.configure(text=f"显示 {visible}/{len(snapshot)} 个账号")
            if hasattr(self, "_update_pool_selection_state"):
                self._update_pool_selection_state()
        except Exception as error:
            self.log(f"刷新账号池失败：{error}", level="ERROR")
        finally:
            if schedule_next:
                self._schedule_pool_refresh()

    def _refresh_stats(self, schedule_next=True):
        if not self._ui_alive():
            return
        try:
            stats = self.cloner.get_stats() if hasattr(self.cloner, "get_stats") else {}
            if not stats:
                snapshot = self.cloner.snapshot_pool()
                total = len(snapshot)
                active = sum(1 for item in snapshot if item.get("user_id") is not None and not item.get("banned", False))
                banned = sum(1 for item in snapshot if item.get("banned", False))
                idle = total - active - banned
                stats = {
                    "total_accounts": total,
                    "active_accounts": active,
                    "idle_accounts": idle,
                    "banned_accounts": banned,
                    "total_messages_forwarded": 0,
                }

            if self.stats_label is not None:
                self.stats_label.configure(
                    text=(
                        f"总账号：{stats.get('total_accounts', 0)}  活跃：{stats.get('active_accounts', 0)}\n"
                        f"空闲：{stats.get('idle_accounts', 0)}  封禁：{stats.get('banned_accounts', 0)}\n"
                        f"已转发：{stats.get('total_messages_forwarded', 0)}"
                    )
                )
            for key, label in self.stat_value_labels.items():
                label.configure(text=str(stats.get(key, 0)))
            self._refresh_config_summary()
            self._sync_runtime_state()
        except Exception as error:
            self.log(f"刷新统计信息失败：{error}", level="ERROR")
        finally:
            if schedule_next:
                self._schedule_stats_refresh()

    def _configure_tree_style(self):
        mode = ctk.get_appearance_mode().lower()
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        if mode == "light":
            row_bg = "#FFFFFF"
            fg = "#0F172A"
            heading_bg = "#E2E8F0"
            heading_fg = "#0F172A"
            selected = "#2563EB"
        else:
            row_bg = "#0F172A"
            fg = "#E5E7EB"
            heading_bg = "#1E293B"
            heading_fg = "#F8FAFC"
            selected = "#1D4ED8"

        style.configure(
            "Pool.Treeview",
            background=row_bg,
            foreground=fg,
            fieldbackground=row_bg,
            rowheight=26,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Pool.Treeview.Heading",
            background=heading_bg,
            foreground=heading_fg,
            font=("Segoe UI", 9, "bold"),
            padding=(6, 6),
        )
        style.map("Pool.Treeview", background=[("selected", selected)], foreground=[("selected", "#FFFFFF")])

    def _delete_selected_account(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个账号。")
            return
        if not messagebox.askyesno(
            "确认删除",
            "确定要删除选中的账号吗？\n此操作会删除对应 Session 文件，无法恢复。",
        ):
            return

        identifiers = []
        for item_id in selected:
            values = self.tree.item(item_id, "values")
            identifier = values[0] if values else None
            if identifier and identifier not in {"未知", "-"}:
                identifiers.append(identifier)

        if not identifiers:
            messagebox.showwarning("提示", "没有可删除的有效账号。")
            return

        async def remove_accounts():
            for identifier in identifiers:
                if hasattr(self.cloner, "delete_account"):
                    await self.cloner.delete_account(identifier)
                else:
                    session_path = os.path.join("sessions", f"{identifier}.session")
                    if os.path.exists(session_path):
                        os.remove(session_path)

        self._run_async(remove_accounts(), error_context="删除账号")
        self.after(400, lambda: self._refresh_pool_view(schedule_next=False))
        self.log(f"已提交 {len(identifiers)} 个账号的删除请求。", level="SUCCESS")

