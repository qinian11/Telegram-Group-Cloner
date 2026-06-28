# -*- coding: utf-8 -*-
import os
from datetime import datetime
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk


class LogMixin:
    def _apply_log_theme(self):
        if self.log_text is None:
            return
        mode = ctk.get_appearance_mode().lower()
        if mode == "light":
            bg = "#F8FAFC"
            fg = "#0F172A"
            select = "#BFDBFE"
            insert = "#0F172A"
            info = "#334155"
        else:
            bg = "#0F172A"
            fg = "#D8DEE9"
            select = "#2563EB"
            insert = "#E2E8F0"
            info = "#CBD5E1"
        self.log_text.configure(bg=bg, fg=fg, selectbackground=select, insertbackground=insert)
        self.log_text.tag_configure("INFO", foreground=info)

    def _export_log(self):
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
                title="导出日志",
            )
            if filename:
                with open(filename, "w", encoding="utf-8") as file:
                    file.write(self.log_text.get(1.0, tk.END))
                self.log(f"日志已导出：{filename}", level="SUCCESS")
        except Exception as error:
            self.log(f"导出日志失败：{error}", level="ERROR")

    def _clear_log(self):
        if self.log_text:
            self.log_text.config(state="normal")
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state="disabled")

    def log(self, message: str, level="INFO"):
        def _write():
            try:
                if not self.log_text or not self.winfo_exists():
                    return
                timestamp = datetime.now().strftime("%H:%M:%S")
                normalized = (level or "INFO").upper()
                prefix = {
                    "INFO": "[INFO]",
                    "SUCCESS": "[OK]",
                    "WARNING": "[WARN]",
                    "ERROR": "[ERROR]",
                }.get(normalized, "[INFO]")
                tag = normalized if normalized in {"INFO", "SUCCESS", "WARNING", "ERROR"} else "INFO"
                self.log_text.config(state="normal")
                self.log_text.insert(tk.END, f"[{timestamp}] {prefix} {message}\n", tag)
                self.log_text.config(state="disabled")
                self.log_text.yview(tk.END)
                lines = int(self.log_text.index("end-1c").split(".")[0])
                if lines > 1000:
                    self.log_text.config(state="normal")
                    self.log_text.delete(1.0, f"{lines - 800}.0")
                    self.log_text.config(state="disabled")
            except Exception:
                pass

        try:
            if self.winfo_exists():
                self.after(0, _write)
        except Exception:
            pass

    def _open_directory(self, path):
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(abs_path, exist_ok=True)
            os.startfile(abs_path)
        except Exception as error:
            self.log(f"打开目录失败：{error}", level="ERROR")
