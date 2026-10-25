# -*- coding: utf-8 -*-
"""SiteSorter エントリポイント（タスクトレイ常駐）"""
import os
import sys
import traceback
import warnings
from datetime import datetime

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from config import DATA_DIR, load_settings, resource_path

ERROR_LOG = os.path.join(DATA_DIR, "error.log")
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


def install_excepthook(window_ref):
    """想定外のエラーを error.log とメイン画面のログに残す。

    EXE（--noconsole）ではエラーの出力先が無く、操作が黙って失敗したように見えるため。
    """
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}")
        except OSError:
            pass
        win = window_ref()
        if win is not None:
            try:
                win.log(f"[エラー] 想定外のエラーが発生しました: {exc}"
                        f"（詳細: {ERROR_LOG}）")
            except Exception:
                pass
    sys.excepthook = hook


def main():
    try:  # HiDPI（125〜150%スケール）での端数処理を滑らかに
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 二重起動の防止（2つ動くと履歴・設定を互いに上書きし、元に戻せなくなる）
    lock = QLockFile(os.path.join(DATA_DIR, "SiteSorter.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "SiteSorter",
            "SiteSorter は既に起動しています。\n"
            "タスクトレイのアイコンから画面を開いてください。")
        return 0

    window = None
    install_excepthook(lambda: window)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = load_settings()
    theme.set_theme(settings.get("theme", "earth"))
    app.setStyleSheet(theme.qss())

    ico = resource_path(os.path.join("assets", "app.ico"))
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    window = MainWindow(settings)
    for w in caught:  # 設定ファイル破損などの警告を画面に出す（EXEではコンソールが無い）
        window.log(f"[注意] {w.message}")
    zone = DropZone(settings, window)
    window.attach_zone(zone)
    tray = make_tray(app, window, zone)  # noqa: F841
    app.aboutToQuit.connect(window.wait_for_worker)

    window.show()
    if settings.get("drop_zone_visible", True):
        zone.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
