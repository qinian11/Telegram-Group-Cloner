# -*- coding: utf-8 -*-
import tkinter as tk
import customtkinter as ctk

from .theme import DesignTokens as T


class Tooltip:
    """轻量 Tooltip，用于侧栏收起和图标按钮说明。"""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        colors = T.colors()
        label = tk.Label(
            self.tip,
            text=self.text,
            bg=colors["surface_3"],
            fg=colors["text_primary"],
            padx=8,
            pady=4,
            font=(T.font_family, 10),
            relief="solid",
            borderwidth=1,
        )
        label.pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Toast(ctk.CTkFrame):
    """非阻塞提示条，替代普通保存成功弹窗。"""

    def __init__(self, master):
        super().__init__(master, corner_radius=T.radius_sm)
        self.label = ctk.CTkLabel(self, text="", font=T.font(13))
        self.label.pack(padx=12, pady=8)
        self.place_forget()

    def show(self, text, kind="info", duration=2400):
        colors = T.colors()
        tone = {
            "success": colors["success"],
            "warning": colors["warning"],
            "error": colors["danger"],
        }.get(kind, colors["brand"])
        self.configure(fg_color=colors["surface_3"], border_width=1, border_color=tone)
        self.label.configure(text=text, text_color=colors["text_primary"])
        self.place(relx=1.0, rely=0.0, x=-24, y=78, anchor="ne")
        self.after(duration, self.place_forget)


def button(master, text, command=None, kind="secondary", width=None, height=None, **kwargs):
    colors = T.colors()
    height = height or T.button_h
    if kind == "primary":
        opts = {
            "fg_color": colors["brand"],
            "hover_color": colors["brand_hover"],
            "text_color": "#FFFFFF",
            "border_width": 0,
        }
    elif kind == "danger":
        opts = {
            "fg_color": "transparent",
            "hover_color": colors["surface_3"],
            "text_color": colors["danger"],
            "border_width": 1,
            "border_color": colors["danger"],
        }
    elif kind == "ghost":
        opts = {
            "fg_color": "transparent",
            "hover_color": colors["surface_3"],
            "text_color": colors["text_secondary"],
            "border_width": 0,
        }
    else:
        opts = {
            "fg_color": colors["surface_2"],
            "hover_color": colors["surface_3"],
            "text_color": colors["text_primary"],
            "border_width": 1,
            "border_color": colors["border"],
        }
    opts.update(kwargs)
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        height=height,
        width=width or 0,
        corner_radius=T.radius_sm,
        font=T.font(13, "bold" if kind == "primary" else None),
        **opts,
    )


def card(master, title=None, subtitle=None, compact=False):
    colors = T.colors()
    frame = ctk.CTkFrame(master, fg_color=colors["surface_1"], corner_radius=T.radius_lg, border_width=1, border_color=colors["border"])
    frame.grid_columnconfigure(0, weight=1)
    padx = T.space_4 if compact else T.space_5
    title_top = T.space_3 if compact else T.space_4
    subtitle_bottom = T.space_2 if compact else T.space_3
    if title:
        ctk.CTkLabel(frame, text=title, font=T.font(15 if compact else 16, "bold"), text_color=colors["text_primary"]).grid(
            row=0, column=0, sticky="w", padx=padx, pady=(title_top, 0)
        )
        if subtitle:
            ctk.CTkLabel(frame, text=subtitle, font=T.font(12), text_color=colors["text_muted"]).grid(
                row=1, column=0, sticky="w", padx=padx, pady=(2, subtitle_bottom)
            )
    return frame


def field_label(master, text, row, column=0, padx=None, pady=(0, 6)):
    colors = T.colors()
    ctk.CTkLabel(master, text=text, font=T.font(13), text_color=colors["text_secondary"]).grid(
        row=row, column=column, sticky="w", padx=padx or T.space_5, pady=pady
    )


def entry(master, **kwargs):
    colors = T.colors()
    return ctk.CTkEntry(
        master,
        height=T.input_h,
        corner_radius=T.radius_sm,
        border_width=1,
        border_color=colors["border"],
        fg_color=colors["surface_2"],
        text_color=colors["text_primary"],
        font=T.font(13),
        **kwargs,
    )


def badge(master, text, tone="muted"):
    colors = T.colors()
    tone_color = {
        "success": colors["success"],
        "warning": colors["warning"],
        "danger": colors["danger"],
        "brand": colors["brand"],
    }.get(tone, colors["text_muted"])
    return ctk.CTkLabel(
        master,
        text=text,
        height=26,
        corner_radius=999,
        fg_color=colors["surface_2"],
        text_color=tone_color,
        font=T.font(12, "bold"),
        padx=10,
    )
