# -*- coding: utf-8 -*-
"""SiteSorter エントリポイント（タスクトレイ常駐）"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import load_settings, resource_path
from ui import theme
from ui.drop_zone import DropZone
from ui.main_window import MainWindow


def make_tray(app, window, zone) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(app.windowIcon(), parent=app)
    tray.setToolTip("SiteSorter - 現場フォルダ自動整理")
    menu = QMenu()
    act_main = menu.addAction("メインウィンドウを表示")
    act_main.triggered.connect(
        lambda: (window.show(), window.raise_(), window.activateWindow()))
    act_zone = menu.addAction("ドロップゾーンを表示/隠す")
    act_zone.triggered.connect(lambda: zone.setVisible(not zone.isVisible()))
    act_reset = menu.addAction("ドロップゾーンを画面内へ再表示")
    act_reset.triggered.connect(zone.reset_position)
    menu.addSeparator()
    act_quit = menu.addAction("終了")
    act_quit.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: (window.show(), window.raise_(), window.activateWindow())
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
        else None)
    tray.show()
    return tray


def main():
    try:  # HiDPI（125〜150%スケール）での端数処理を滑らかに
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    settings = load_settings()
    theme.set_theme(settings.get("theme", "earth"))
    app.setStyleSheet(theme.qss())

    ico = resource_path(os.path.join("assets", "app.ico"))
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    window = MainWindow(settings)
    zone = DropZone(settings, window)
    window.attach_zone(zone)
    tray = make_tray(app, window, zone)  # noqa: F841

    window.show()
    if settings.get("drop_zone_visible", True):
        zone.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
