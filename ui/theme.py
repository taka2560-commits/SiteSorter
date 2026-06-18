# -*- coding: utf-8 -*-
"""テーマ定義（2種切替: earth=アース / night=ナイト）"""

THEMES = {
    "earth": {
        "label": "アース",
        "primary": "#31658F", "secondary": "#246169", "accent": "#F5993D",
        "bg": "#222629", "surface": "#2B3036", "surface2": "#262B2F",
        "log_bg": "#1B1F22", "border": "#3A4046",
        "text": "#EFF2F5", "muted": "#9AA4AD",
        "primary_hi": "#3A77A8", "head_text": "#7FB4D9",
        "sec_text": "#7FCBD4", "disabled": "#5A636B",
    },
    "night": {
        "label": "ナイト",
        "primary": "#1F74C1", "secondary": "#183095", "accent": "#F5CD3D",
        "bg": "#181B1E", "surface": "#24292E", "surface2": "#1F2428",
        "log_bg": "#121518", "border": "#30363D",
        "text": "#E0E5EA", "muted": "#8B949E",
        "primary_hi": "#2B86D9", "head_text": "#7FB0E0",
        "sec_text": "#9DB3F0", "disabled": "#586069",
    },
}

CURRENT = "earth"
COLORS = dict(THEMES["earth"])  # 参照保持のため中身を入れ替える


def set_theme(name: str) -> None:
    global CURRENT
    if name in THEMES:
        CURRENT = name
    COLORS.clear()
    COLORS.update(THEMES[CURRENT])


_QSS = """
QWidget {{
    background: {bg}; color: {text};
    font-family: "Yu Gothic UI", "Meiryo UI", sans-serif; font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLineEdit, QListWidget, QTableWidget, QComboBox, QPlainTextEdit {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px;
    padding: 4px 6px; selection-background-color: {primary};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border};
    selection-background-color: {primary};
}}
QTableWidget {{ alternate-background-color: {surface2}; gridline-color: {border}; }}
QHeaderView::section {{
    background: {surface}; color: {head_text}; border: none;
    border-bottom: 1px solid {border}; padding: 4px 8px; font-weight: bold;
}}
QTableCornerButton::section {{ background: {surface}; border: none; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; }}
QTabBar::tab {{
    background: {surface}; color: {muted}; padding: 6px 18px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: {primary}; color: {text}; }}
QPushButton {{
    background: transparent; border: 1px solid {secondary}; border-radius: 6px;
    color: {sec_text}; padding: 7px 14px;
}}
QPushButton:hover {{ background: {secondary}; color: {text}; }}
QPushButton:disabled {{ border-color: {border}; color: {disabled}; }}
QPushButton#primary {{
    background: {primary}; border: none; color: {text}; font-weight: bold;
}}
QPushButton#primary:hover {{ background: {primary_hi}; }}
QPushButton#primary:disabled {{ background: {surface}; color: {disabled}; }}
QProgressBar {{
    background: {surface}; border: none; border-radius: 5px;
    min-height: 18px; text-align: center; color: {text}; font-size: 11px;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
QPlainTextEdit#log {{
    background: {log_bg}; border: 1px solid {border}; border-radius: 6px;
    color: {muted}; font-family: Consolas, monospace; font-size: 12px;
}}
QMenu {{ background: {surface}; border: 1px solid {border}; }}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: {primary}; }}
QScrollBar:vertical {{ background: {bg}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QListWidget#nav {{
    background: {surface}; border: none; border-radius: 0;
    font-size: 14px; padding: 8px 0;
}}
QListWidget#nav::item {{ padding: 12px 18px; border-left: 3px solid transparent; }}
QListWidget#nav::item:selected {{
    background: {bg}; border-left: 3px solid {accent}; color: {text};
}}
QFrame#dropframe {{
    background: {surface}; border: 2px dashed {secondary}; border-radius: 12px;
}}
QFrame#dropframe[hot="true"] {{ border: 2px dashed {accent}; background: {surface2}; }}
QFrame#dropframe:disabled {{ border: 2px dashed {border}; }}
QLabel#capwarn {{ color: {accent}; font-weight: bold; }}
QMessageBox QLabel {{ color: {text}; }}
"""


def qss() -> str:
    return _QSS.format(**COLORS)


def _rgba(hexcolor: str, alpha: int) -> str:
    h = hexcolor.lstrip("#")
    return (f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, "
            f"{int(h[4:6], 16)}, {alpha})")


def drop_idle() -> str:
    """ドロップゾーン通常時（高透過 約0.4）"""
    return (
        "QWidget#zone {{ background: {bg}; border: 2px dashed {bd};"
        " border-radius: 16px; }}"
        " QLabel {{ color: {tx}; font-size: 13px; background: transparent; }}"
    ).format(bg=_rgba(COLORS["bg"], 100), bd=_rgba(COLORS["head_text"], 170),
             tx=COLORS["text"])


def drop_active() -> str:
    """ドラッグ中（不透明度0.85・アクセント色で明示）"""
    return (
        "QWidget#zone {{ background: {bg}; border: 2px dashed #FFFFFF;"
        " border-radius: 16px; }}"
        " QLabel {{ color: {tx}; font-size: 13px; font-weight: bold;"
        " background: transparent; }}"
    ).format(bg=_rgba(COLORS["accent"], 217), tx=COLORS["bg"])


# v1互換（旧コードからの参照用）
QSS = qss()
DROP_IDLE = drop_idle()
DROP_ACTIVE = drop_active()
