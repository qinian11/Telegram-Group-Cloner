# -*- coding: utf-8 -*-
import customtkinter as ctk

class DesignTokens:
    space_1 = 4
    space_2 = 8
    space_3 = 12
    space_4 = 16
    space_5 = 20
    space_6 = 24
    space_8 = 32

    sidebar_width = 168
    sidebar_collapsed_width = 64
    topbar_height = 64
    log_default_height = 220
    log_min_height = 120
    log_side_width = 260
    log_side_collapsed_width = 48

    radius_sm = 8
    radius_md = 10
    radius_lg = 12

    button_h = 40
    button_sm_h = 34
    input_h = 40
    nav_h = 34

    font_family = "Microsoft YaHei UI"
    mono_family = "Consolas"

    dark = {
        "app_bg": "#0F1115",
        "sidebar_bg": "#14171C",
        "surface_1": "#181C22",
        "surface_2": "#1E232B",
        "surface_3": "#252B34",
        "border": "#2D343E",
        "border_hover": "#3B4552",
        "text_primary": "#F2F4F7",
        "text_secondary": "#AAB2BF",
        "text_muted": "#7F8997",
        "brand": "#4C8DFF",
        "brand_hover": "#3F7DE8",
        "success": "#37B878",
        "warning": "#E6A740",
        "danger": "#E05A5A",
    }

    light = {
        "app_bg": "#F4F6F8",
        "sidebar_bg": "#FFFFFF",
        "surface_1": "#FFFFFF",
        "surface_2": "#F8F9FB",
        "surface_3": "#EEF1F5",
        "border": "#D9DEE7",
        "border_hover": "#C6CDD8",
        "text_primary": "#1B1F24",
        "text_secondary": "#5D6672",
        "text_muted": "#7D8794",
        "brand": "#256FD1",
        "brand_hover": "#1F5FB3",
        "success": "#16875D",
        "warning": "#A96800",
        "danger": "#C63D3D",
    }

    @classmethod
    def colors(cls):
        return cls.light if ctk.get_appearance_mode().lower() == "light" else cls.dark

    @classmethod
    def font(cls, size=14, weight=None):
        return ctk.CTkFont(family=cls.font_family, size=size, weight=weight)

    @classmethod
    def mono_font(cls, size=12):
        return ctk.CTkFont(family=cls.mono_family, size=size)
