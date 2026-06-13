# -*- coding: utf-8 -*-
"""② クイック・インボックサー（常時最前面・高透過・提出/受領トグル付き）"""
import os

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from config import save_settings
from core.organizer import ingest_drop
from ui import dialogs, theme

SITE_LABEL_CSS = ("font-size: 10px; color: rgba(255, 255, 255, 180); "
                  "background: transparent;")
IDLE_TEXT = "📥\nここにドロップ\n＝即仕分け"
W, H = 150, 196


class DropZone(QWidget):
    def __init__(self, settings: dict, main_window):
        super().__init__()
        self.settings = settings
        self.main_window = main_window
        self._drag_pos = None
        self._idle = theme.drop_idle()
        self._active = theme.drop_active()

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedSize(W, H)

        inner = QWidget(self)
        inner.setObjectName("zone")
        inner.setGeometry(0, 0, W, H)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(8, 8, 8, 8)
        self.label = QLabel(IDLE_TEXT, alignment=Qt.AlignCenter)
        lay.addWidget(self.label, 1)

        trow = QHBoxLayout()
        self.tg_submit = QPushButton("提出用")
        self.tg_receive = QPushButton("受領用")
        for tg in (self.tg_submit, self.tg_receive):
            tg.setCheckable(True)
            tg.setFixedHeight(24)
            trow.addWidget(tg)
        self.tg_submit.toggled.connect(
            lambda on: on and self.tg_receive.setChecked(False))
        self.tg_receive.toggled.connect(
            lambda on: on and self.tg_submit.setChecked(False))
        self.tg_submit.setToolTip("ON中のドロップ: 10_図面_作業用 と 11_図面_提出済\\日付_提出 に同時コピー（zipは11のみ）")
        self.tg_receive.setToolTip("ON中のドロップ: 12_社外受領データ へ原本保管（フォルダは丸ごと）")
        lay.addLayout(trow)

        self.site_label = QLabel("（現場未設定）", alignment=Qt.AlignCenter)
        self.site_label.setStyleSheet(SITE_LABEL_CSS)
        lay.addWidget(self.site_label)

        self.apply_theme()
        pos = self.settings.get("drop_zone_pos")
        if pos:
            self.move(QPoint(*pos))

    # ---------- テーマ・表示 ----------
    def apply_theme(self):
        self._idle = theme.drop_idle()
        self._active = theme.drop_active()
        self.setStyleSheet(self._idle)
        c = theme.COLORS
        tg_css = (
            f"QPushButton {{ background: {c['surface']}; color: {c['muted']};"
            f" border: 1px solid {c['border']}; border-radius: 6px;"
            f" font-size: 10px; padding: 2px; }}"
            f"QPushButton:checked {{ background: {c['accent']}; color: {c['bg']};"
            f" border: none; font-weight: bold; }}")
        self.tg_submit.setStyleSheet(tg_css)
        self.tg_receive.setStyleSheet(tg_css)

    def set_site(self, name: str) -> None:
        self.site_label.setText(name or "（現場未設定）")

    def reset_position(self):
        """画面外・裏に行ったゾーンを画面内へ呼び戻す"""
        g = QApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.width() - 40,
                  g.bottom() - self.height() - 60)
        self.show()
        self.raise_()
        self.settings["drop_zone_pos"] = [self.x(), self.y()]
        self.settings["drop_zone_visible"] = True
        save_settings(self.settings)

    def _toggle(self):
        if self.tg_submit.isChecked():
            return "submit"
        if self.tg_receive.isChecked():
            return "receive"
        return None

    # ---------- D&D（即時仕分け） ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.setStyleSheet(self._active)
            mode = {"submit": "提出処理", "receive": "受領保管"}.get(
                self._toggle(), "仕分け")
            self.label.setText(f"⬇\n離して{mode}")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._reset_label()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        e.acceptProposedAction()
        # エクスプローラ側を待たせないため、ドロップ完了後に処理
        QTimer.singleShot(0, lambda: self._process(paths))

    def _process(self, paths: list):
        base = self.settings.get("site_folder")
        if not base:
            self.setStyleSheet(self._idle)
            self.label.setText("⚠\n現場フォルダ\n未設定")
            QTimer.singleShot(1500, self._reset_label)
            return
        toggle = self._toggle()
        resolver = dialogs.gui_resolver(self.main_window)
        sk = []
        ops = ingest_drop(base, paths, toggle=toggle,
                          log_cb=self.main_window.log, resolver=resolver,
                          skipped=sk)
        self.main_window.history.record(ops)
        if sk:
            self.main_window.add_retry_items(sk)
        self.setStyleSheet(self._idle)
        mode = {"submit": "提出", "receive": "受領"}.get(toggle, "処理")
        self.label.setText(f"✔\n{len(ops)}件 {mode}")
        self.tg_submit.setChecked(False)   # 事故防止: 処理後は自動OFF
        self.tg_receive.setChecked(False)
        self.main_window.refresh_inbox()
        QTimer.singleShot(1500, self._reset_label)

    def _reset_label(self):
        self.setStyleSheet(self._idle)
        self.label.setText(IDLE_TEXT)

    # ---------- ウィンドウのドラッグ移動 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self.settings["drop_zone_pos"] = [self.x(), self.y()]
            save_settings(self.settings)
        self._drag_pos = None

    # ---------- 右クリックメニュー ----------
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        sites = self.settings.get("site_history", [])
        if sites:
            sub = menu.addMenu("現場を切り替え")
            current = self.settings.get("site_folder")
            for p in sites:
                mark = "● " if p == current else "　 "
                act = QAction(mark + os.path.basename(p), self)
                act.triggered.connect(
                    lambda checked=False, path=p:
                    self.main_window.switch_site(path))
                sub.addAction(act)
            menu.addSeparator()
        act_show = QAction("メインウィンドウを表示", self)
        act_show.triggered.connect(self._show_main)
        menu.addAction(act_show)
        menu.addSeparator()
        act_quit = QAction("終了", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)
        menu.exec(e.globalPos())

    def _show_main(self):
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _quit(self):
        QApplication.quit()
