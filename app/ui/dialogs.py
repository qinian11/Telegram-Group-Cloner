# -*- coding: utf-8 -*-
import customtkinter as ctk


class CustomInputDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="输入", prompt="", show=None, width=420, height=208):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.grab_set()

        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 20)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 2, 20)
        self.geometry(f"{width}x{height}+{x}+{y}")

        outer = ctk.CTkFrame(self, corner_radius=16)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            outer,
            text=prompt,
            font=ctk.CTkFont(size=13),
            justify="left",
            wraplength=width - 64,
        ).pack(anchor="w", padx=16, pady=(16, 10))

        self._entry = ctk.CTkEntry(outer, height=34, font=ctk.CTkFont(size=13), corner_radius=10)
        if show:
            self._entry.configure(show=show)
        self._entry.pack(fill="x", padx=16)
        self._entry.focus()

        button_row = ctk.CTkFrame(outer, fg_color="transparent")
        button_row.pack(fill="x", padx=16, pady=(14, 16))
        ctk.CTkButton(
            button_row,
            text="取消",
            width=96,
            height=32,
            command=self._cancel_event,
            fg_color=("#475569", "#334155"),
            hover_color=("#334155", "#1F2937"),
            font=ctk.CTkFont(size=12),
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            button_row,
            text="确定",
            width=96,
            height=32,
            command=self._ok_event,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="right")

        self.bind("<Return>", self._ok_event)
        self.bind("<Escape>", self._cancel_event)
        self._result = None
        self.wait_window()

    def _ok_event(self, _=None):
        self._result = self._entry.get()
        self.destroy()

    def _cancel_event(self, _=None):
        self._result = None
        self.destroy()

    def get_input(self):
        return self._result
