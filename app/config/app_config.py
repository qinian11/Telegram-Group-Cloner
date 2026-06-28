# -*- coding: utf-8 -*-
import configparser
import os


DEFAULT_CONFIG = {
    "telegram": {
        "api_id": "3642180",
        "api_hash": "636c15dbfe0b01f6fab88600d62667d0",
        "monitor_phone": "+8613800000000",
        "source_group": "https://t.me/souba8",
        "target_group": "https://t.me/souba8",
    },
    "proxy": {
        "is_enabled": "false",
        "host": "127.0.0.1",
        "port": "7890",
        "type": "socks5",
    },
    "blacklist": {
        "user_ids": "",
        "keywords": "",
    },
    "replacements": {
        "浣犲ソ": "鎮ㄥソ",
    },
    "strategy": {
        "clone_name": "true",
        "clone_avatar": "true",
        "daily_clone_limit": "30",
        "identity_cooldown_sec": "3600",
        "min_send_interval": "1.0",
        "max_send_interval": "3.0",
        "shard_total": "1",
        "shard_index": "0",
        "replacements_mode": "literal",
        "replacements_case_insensitive": "false",
        "adaptive_throttle": "true",
        "adaptive_decay": "0.85",
        "adaptive_penalty": "1.25",
        "adaptive_cap": "30.0",
    },
}


class Config:
    def __init__(self, config_path="setting/config.ini"):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.config.optionxform = str
        self.load_config()

    def load_config(self):
        self.config.read_dict(DEFAULT_CONFIG)
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding="utf-8-sig")
        else:
            self.save_config()

    def reload(self):
        self.config = configparser.ConfigParser()
        self.config.optionxform = str
        self.load_config()

    def get(self, section, option, fallback=None):
        return self.config.get(section, option, fallback=fallback)

    def getint(self, section, option, fallback=None):
        try:
            return self.config.getint(section, option, fallback=fallback)
        except Exception:
            return fallback

    def getfloat(self, section, option, fallback=None):
        try:
            return self.config.getfloat(section, option, fallback=fallback)
        except Exception:
            return fallback

    def getboolean(self, section, option, fallback=None):
        try:
            return self.config.getboolean(section, option, fallback=fallback)
        except Exception:
            return fallback

    def save_config(self):
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as file:
            self.config.write(file)

    def set(self, section, option, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, str(value))
