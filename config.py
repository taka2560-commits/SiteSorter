# -*- coding: utf-8 -*-
"""設定の読み書き。保存先は %APPDATA%\SiteSorter（exe化対応）。

旧配置（アプリフォルダ直下）の settings.json / history.json / rules.json は
初回起動時に自動で新配置へコピーされる。
"""
import json
import os
import shutil
import sys

APP_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))

if os.name == "nt":
    DATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "SiteSorter")
else:
    DATA_DIR = os.path.join(os.path.expanduser("~"), ".config", "SiteSorter")
os.makedirs(DATA_DIR, exist_ok=True)

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
RULES_PATH = os.path.join(DATA_DIR, "rules.json")

# 旧配置からの自動移行
for _name in ("settings.json", "history.json", "rules.json"):
    _old = os.path.join(APP_DIR, _name)
    _new = os.path.join(DATA_DIR, _name)
    if os.path.exists(_old) and not os.path.exists(_new):
        try:
            shutil.copy2(_old, _new)
        except OSError:
            pass

DEFAULTS = {
    "theme": "earth",            # "earth" | "night"
    "site_folder": "",           # 現在の現場フォルダ
    "site_history": [],          # 現場履歴（先頭が最新）
    "drop_zone_pos": None,       # [x, y]
    "drop_zone_visible": True,
    "capacity_threshold_gb": 100,
    "capacity_cache": {},        # {現場パス: {total, scan3d, time}}
    "templates": [],             # [{src, dst}] 新規現場の雛形配置
}


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def resource_path(rel: str) -> str:
    """同梱リソースのパス解決（PyInstaller --onefile の _MEIPASS 対応）"""
    base = getattr(sys, "_MEIPASS", APP_DIR)
    return os.path.join(base, rel)
