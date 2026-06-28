# -*- coding: utf-8 -*-

STATUS_STYLE = {
    "idle": {
        "label": "待命",
        "hint": "配置就绪后可以开始监听。",
        "text_color": ("#475569", "#CBD5E1"),
        "badge_fg": ("#E2E8F0", "#132033"),
    },
    "starting": {
        "label": "启动中",
        "hint": "正在连接监听账号并加载账号池。",
        "text_color": ("#A16207", "#FACC15"),
        "badge_fg": ("#FEF3C7", "#3A2A05"),
    },
    "running": {
        "label": "运行中",
        "hint": "监听任务正在后台运行。",
        "text_color": ("#047857", "#34D399"),
        "badge_fg": ("#DCFCE7", "#072C1D"),
    },
    "stopping": {
        "label": "停止中",
        "hint": "正在断开连接并释放资源。",
        "text_color": ("#B45309", "#F59E0B"),
        "badge_fg": ("#FDE68A", "#3A2104"),
    },
    "error": {
        "label": "异常",
        "hint": "最近一次操作失败，请查看下方日志。",
        "text_color": ("#B91C1C", "#F87171"),
        "badge_fg": ("#FEE2E2", "#3A1111"),
    },
}
