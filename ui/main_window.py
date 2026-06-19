# -*- coding: utf-8 -*-
"""① メインウィンドウ（サイドバー＋3ページ構成）"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import rules
from config import HISTORY_PATH, save_settings
from core.history import History
from core.organizer import (archive_files, create_site, ensure_structure,
                            ingest_drop, preflight, scan_inbox, send_to_inbox)
from core.worker import CapacityWorker, SortWorker
from ui import dialogs, theme
from ui.archive_dialog import ArchiveDialog
from ui.retry_dialog import RetryDialog
from ui.rule_editor import RuleEditor
from ui.theme import COLORS

try:
    import qtawesome as qta
except ImportError:
    qta = None

MAX_SITES = 10
NAV_ITEMS = [("fa5s.inbox", "ダッシュボード"),
             ("fa5s.history", "履歴・Undo"),
             ("fa5s.cog", "設定")]


def _icon(btn, name, color):
    if qta:
        btn.setIcon(qta.icon(name, color=color))


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


class DropFrame(QFrame):
    """「Inboxへ仮置き」専用ドロップ枠（仕分けせずInboxへストック）"""
    dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropframe")
        self.setAcceptDrops(True)
        self.setMinimumHeight(84)
        lay = QVBoxLayout(self)
        self.label = QLabel("📥 ここにドロップで 00_Inbox へ仮置き\n（仕分けはしません）",
                            alignment=Qt.AlignCenter)
        lay.addWidget(self.label)

    def _set_hot(self, hot: bool):
        self.setProperty("hot", "true" if hot else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if self.isEnabled() and e.mimeData().hasUrls():
            self._set_hot(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._set_hot(False)

    def dropEvent(self, e):
        self._set_hot(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        if paths:
            self.dropped.emit(paths)
        e.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.history = History(HISTORY_PATH)
        self.worker = None
        self.cap_worker = None
        self.zone = None
        self.retry_items = []
        self._archive_checked_paths: set = set()
        self.setWindowTitle("SiteSorter - 現場フォルダ自動整理")
        self.resize(860, 640)
        self.setMinimumSize(760, 560)
        self._build_ui()
        if self.settings.get("site_folder"):
            self._set_folder(self.settings["site_folder"], save=False)

    def attach_zone(self, zone) -> None:
        self.zone = zone
        base = self.settings.get("site_folder")
        if base:
            zone.set_site(os.path.basename(base))

    # ================= UI構築 =================
    def _build_ui(self):
        root = QWidget()
        hbox = QHBoxLayout(root)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(168)
        for icon_name, label in NAV_ITEMS:
            item = QListWidgetItem(label)
            if qta:
                item.setIcon(qta.icon(icon_name, color=COLORS["muted"]))
            self.nav.addItem(item)
        hbox.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_dashboard())
        self.stack.addWidget(self._page_history())
        self.stack.addWidget(self._page_settings())
        hbox.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)
        self.setCentralWidget(root)
        self._update_buttons()

    def _on_nav(self, row: int):
        self.stack.setCurrentIndex(row)
        if row == 1:
            self._refresh_history_list()

    # ---------- ページ1: ダッシュボード ----------
    def _page_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)

        row = QHBoxLayout()
        row.addWidget(QLabel("現場:"))
        self.site_combo = QComboBox()
        self.site_combo.addItems(self.settings.get("site_history", []))
        self.site_combo.activated.connect(
            lambda i: self._set_folder(self.site_combo.itemText(i)))
        row.addWidget(self.site_combo, 1)
        btn_browse = QPushButton("参照...")
        _icon(btn_browse, "fa5s.folder-open", COLORS["sec_text"])
        btn_browse.clicked.connect(self._browse)
        row.addWidget(btn_browse)
        btn_zone = QPushButton("ゾーン再表示")
        _icon(btn_zone, "fa5s.crosshairs", COLORS["sec_text"])
        btn_zone.setToolTip("ドロップゾーンが見当たらない時に画面内へ呼び戻します")
        btn_zone.clicked.connect(self._reset_zone)
        row.addWidget(btn_zone)
        layout.addLayout(row)

        rowA = QHBoxLayout()
        btn_new = QPushButton("新規現場セットアップ")
        _icon(btn_new, "fa5s.plus", COLORS["sec_text"])
        btn_new.clicked.connect(self._new_site)
        rowA.addWidget(btn_new)
        btn_old = QPushButton("旧版検知 → 99_Archive")
        _icon(btn_old, "fa5s.box-open", COLORS["sec_text"])
        btn_old.clicked.connect(self._detect_old)
        rowA.addWidget(btn_old)
        self.btn_retry = QPushButton("ロック中: 0")
        _icon(self.btn_retry, "fa5s.lock", COLORS["sec_text"])
        self.btn_retry.setEnabled(False)
        self.btn_retry.setToolTip("使用中でスキップされたファイルの再試行リスト")
        self.btn_retry.clicked.connect(self._open_retry)
        rowA.addWidget(self.btn_retry)
        rowA.addStretch()
        self.cap_warn = QLabel("")
        self.cap_warn.setObjectName("capwarn")
        rowA.addWidget(self.cap_warn)
        layout.addLayout(rowA)

        rowC = QHBoxLayout()
        self.cap_bar = QProgressBar()
        self.cap_bar.setRange(0, 100)
        self.cap_bar.setTextVisible(True)
        self.cap_bar.setFormat("容量 -")
        rowC.addWidget(self.cap_bar, 1)
        self.cap_label = QLabel("")
        rowC.addWidget(self.cap_label)
        btn_recalc = QPushButton("再計算")
        btn_recalc.clicked.connect(self._recalc_capacity)
        rowC.addWidget(btn_recalc)
        layout.addLayout(rowC)

        self.drop_frame = DropFrame()
        self.drop_frame.dropped.connect(self._stock_to_inbox)
        layout.addWidget(self.drop_frame)

        row2 = QHBoxLayout()
        self.inbox_label = QLabel("00_Inbox 待機: -")
        row2.addWidget(self.inbox_label, 1)
        btn_refresh = QPushButton("更新")
        _icon(btn_refresh, "fa5s.sync-alt", COLORS["sec_text"])
        btn_refresh.clicked.connect(self.refresh_inbox)
        row2.addWidget(btn_refresh)
        layout.addLayout(row2)
        self.inbox_list = QListWidget()
        layout.addWidget(self.inbox_list, 1)

        row3 = QHBoxLayout()
        self.btn_run = QPushButton("Inboxを処理（一括仕分け）")
        self.btn_run.setObjectName("primary")
        self.btn_run.setMinimumHeight(36)
        _icon(self.btn_run, "fa5s.play", COLORS["text"])
        self.btn_run.clicked.connect(self._run)
        row3.addWidget(self.btn_run, 2)
        self.btn_undo = QPushButton("直前の処理を元に戻す")
        _icon(self.btn_undo, "fa5s.undo-alt", COLORS["sec_text"])
        self.btn_undo.clicked.connect(self._undo)
        row3.addWidget(self.btn_undo, 1)
        layout.addLayout(row3)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setObjectName("log")
        self.log_view.setMaximumHeight(120)
        layout.addWidget(self.log_view)
        return page

    # ---------- ページ2: 履歴・Undo ----------
    def _page_history(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        row = QHBoxLayout()
        row.addWidget(QLabel("操作履歴（直近50操作・新しい順）"), 1)
        btn_re = QPushButton("更新")
        btn_re.clicked.connect(self._refresh_history_list)
        row.addWidget(btn_re)
        layout.addLayout(row)
        self.hist_list = QListWidget()
        layout.addWidget(self.hist_list, 1)
        self.btn_undo2 = QPushButton("直前の処理を元に戻す（バッチ単位）")
        _icon(self.btn_undo2, "fa5s.undo-alt", COLORS["sec_text"])
        self.btn_undo2.clicked.connect(self._undo)
        layout.addWidget(self.btn_undo2)
        return page

    def _refresh_history_list(self):
        self.hist_list.clear()
        kinds = {"move": "移動", "copy": "コピー", "copy_dual": "同時コピー"}
        for op in reversed(self.history.recent()):
            t = str(op.get("time", ""))[5:16].replace("T", " ")
            name = os.path.basename(str(op.get("src", "")))
            dst = str(op.get("dst", ""))
            tail = os.path.join(os.path.basename(os.path.dirname(dst)),
                                os.path.basename(dst))
            self.hist_list.addItem(
                f"{t}  [{kinds.get(op.get('op'), op.get('op'))}] {name} → {tail}")
        self._update_buttons()

    # ---------- ページ3: 設定 ----------
    def _page_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)

        row = QHBoxLayout()
        row.addWidget(QLabel("テーマ:"))
        self.theme_combo = QComboBox()
        for key in theme.THEMES:
            self.theme_combo.addItem(theme.THEMES[key]["label"], key)
        cur = self.settings.get("theme", "earth")
        self.theme_combo.setCurrentIndex(
            max(0, list(theme.THEMES).index(cur) if cur in theme.THEMES else 0))
        self.theme_combo.activated.connect(self._change_theme)
        row.addWidget(self.theme_combo)
        row.addStretch()
        btn_rules = QPushButton("ルール編集（拡張子・キーワード）")
        _icon(btn_rules, "fa5s.cog", COLORS["sec_text"])
        btn_rules.clicked.connect(self._edit_rules)
        row.addWidget(btn_rules)
        layout.addLayout(row)

        rowT = QHBoxLayout()
        rowT.addWidget(QLabel("容量警告の閾値:"))
        self.th_spin = QSpinBox()
        self.th_spin.setRange(10, 100000)
        self.th_spin.setSuffix(" GB")
        self.th_spin.setValue(int(self.settings.get("capacity_threshold_gb", 100)))
        self.th_spin.valueChanged.connect(self._save_threshold)
        rowT.addWidget(self.th_spin)
        rowT.addStretch()
        layout.addLayout(rowT)

        layout.addWidget(QLabel("新規現場の雛形ファイル（テンプレート）:"))
        self.tpl_table = QTableWidget(0, 2)
        self.tpl_table.setHorizontalHeaderLabels(["雛形ファイル", "配置先フォルダ"])
        self.tpl_table.horizontalHeader().setStretchLastSection(True)
        self.tpl_table.setColumnWidth(0, 320)
        self.tpl_table.setMaximumHeight(140)
        for t in self.settings.get("templates", []):
            r = self.tpl_table.rowCount()
            self.tpl_table.insertRow(r)
            self.tpl_table.setItem(r, 0, QTableWidgetItem(t.get("src", "")))
            self.tpl_table.setItem(r, 1, QTableWidgetItem(t.get("dst", "")))
        self.tpl_table.itemChanged.connect(lambda *_: self._save_templates())
        layout.addWidget(self.tpl_table)
        rowP = QHBoxLayout()
        btn_tadd = QPushButton("雛形を追加...")
        btn_tadd.clicked.connect(self._add_template)
        btn_tdel = QPushButton("選択行を削除")
        btn_tdel.clicked.connect(self._del_template)
        rowP.addWidget(btn_tadd)
        rowP.addWidget(btn_tdel)
        rowP.addStretch()
        layout.addLayout(rowP)

        layout.addWidget(QLabel("仕分けルール（優先順位: トグル → キーワード → 拡張子 → 90_その他）:"))
        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setHorizontalHeaderLabels(["フォルダ", "対象拡張子", "キーワード"])
        self.rules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rules_table.setAlternatingRowColors(True)
        self.rules_table.verticalHeader().setVisible(False)
        self._fill_rules_table()
        layout.addWidget(self.rules_table, 1)
        return page

    def _fill_rules_table(self):
        t = self.rules_table
        photo = rules.photo_dir()
        folders = sorted(set(rules.FOLDERS) | set(rules.KEYWORDS))
        t.setRowCount(len(folders) + 2)
        for i, folder in enumerate(folders):
            exts = " ".join(sorted(rules.FOLDERS.get(folder, set())))
            if folder == photo:
                exts += "　※撮影日別"
            kws = " ".join(rules.KEYWORDS.get(folder, []))
            t.setItem(i, 0, QTableWidgetItem(folder))
            t.setItem(i, 1, QTableWidgetItem(exts))
            t.setItem(i, 2, QTableWidgetItem(kws))
        t.setItem(len(folders), 0, QTableWidgetItem(rules.SUBMIT_DIR))
        t.setItem(len(folders), 1, QTableWidgetItem("提出トグル専用（聖域）"))
        t.setItem(len(folders), 2, QTableWidgetItem("-"))
        t.setItem(len(folders) + 1, 0, QTableWidgetItem(rules.OTHERS))
        t.setItem(len(folders) + 1, 1, QTableWidgetItem("上記以外すべて"))
        t.setItem(len(folders) + 1, 2, QTableWidgetItem("-"))
        t.resizeColumnsToContents()

    # ================= 動作 =================
    def _change_theme(self, idx: int):
        key = self.theme_combo.itemData(idx)
        theme.set_theme(key)
        self.settings["theme"] = key
        save_settings(self.settings)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(theme.qss())
        if self.zone:
            self.zone.apply_theme()
        self.log(f"テーマを「{theme.THEMES[key]['label']}」に変更しました")

    def _edit_rules(self):
        dlg = RuleEditor(self)
        if dlg.exec():
            self._fill_rules_table()
            base = self.settings.get("site_folder")
            if base and os.path.isdir(base):
                ensure_structure(base)
            self.log("仕分けルールを更新しました (rules.json)")
            self.refresh_inbox()

    def _reset_zone(self):
        if self.zone:
            self.zone.reset_position()
            self.log("ドロップゾーンを画面内に再表示しました")

    def _stock_to_inbox(self, paths: list):
        base = self.settings.get("site_folder")
        if not base:
            return
        send_to_inbox(base, paths, log_cb=self.log)
        self.refresh_inbox()

    # ---------- 容量モニター ----------
    def _recalc_capacity(self):
        base = self.settings.get("site_folder")
        if not base or not os.path.isdir(base):
            return
        if self.cap_worker is not None and self.cap_worker.isRunning():
            return
        self.cap_bar.setFormat("容量 計算中…")
        self.cap_worker = CapacityWorker(base)
        self.cap_worker.done.connect(self._on_capacity)
        self.cap_worker.start()

    def _on_capacity(self, base, res):
        from datetime import datetime
        cache = self.settings.setdefault("capacity_cache", {})
        cache[base] = {"total": res["total"], "scan3d": res["scan3d"],
                       "time": datetime.now().isoformat(timespec="seconds")}
        save_settings(self.settings)
        if base == self.settings.get("site_folder"):
            self._show_capacity(cache[base])

    def _show_capacity(self, res):
        gb = 1024 ** 3
        th = max(1, int(self.settings.get("capacity_threshold_gb", 100)))
        total, scan3d = res.get("total", 0), res.get("scan3d", 0)
        self.cap_bar.setValue(min(100, int(total * 100 / (th * gb))))
        self.cap_bar.setFormat(f"総容量 {total / gb:.1f} GB / 閾値 {th} GB（%p%）")
        self.cap_label.setText(f"3Dスキャン: {scan3d / gb:.1f} GB")
        self.cap_warn.setText("⚠ 容量警告: 閾値を超えています"
                              if total >= th * gb else "")

    def _save_threshold(self, v):
        self.settings["capacity_threshold_gb"] = int(v)
        save_settings(self.settings)
        cached = self.settings.get("capacity_cache", {}).get(
            self.settings.get("site_folder"))
        if cached:
            self._show_capacity(cached)

    # ---------- テンプレート設定 ----------
    def _save_templates(self):
        tpls = []
        for r in range(self.tpl_table.rowCount()):
            i0, i1 = self.tpl_table.item(r, 0), self.tpl_table.item(r, 1)
            src = (i0.text() if i0 else "").strip()
            dst = (i1.text() if i1 else "").strip()
            if src:
                tpls.append({"src": src, "dst": dst})
        self.settings["templates"] = tpls
        save_settings(self.settings)

    def _add_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "雛形ファイルを選択")
        if not path:
            return
        r = self.tpl_table.rowCount()
        self.tpl_table.insertRow(r)
        self.tpl_table.setItem(r, 0, QTableWidgetItem(path))
        self.tpl_table.setItem(r, 1, QTableWidgetItem("40_報告書・書類"))
        self._save_templates()

    def _del_template(self):
        r = self.tpl_table.currentRow()
        if r >= 0:
            self.tpl_table.removeRow(r)
            self._save_templates()

    # ---------- 新規現場・旧版検知 ----------
    def _new_site(self):
        name, ok = QInputDialog.getText(self, "新規現場セットアップ",
                                        "現場名（フォルダ名）:")
        if not ok or not name.strip():
            return
        parent = QFileDialog.getExistingDirectory(self, "作成先（親フォルダ）を選択")
        if not parent:
            return
        try:
            base = create_site(parent, name.strip(),
                               self.settings.get("templates", []),
                               log_cb=self.log)
        except ValueError as e:
            QMessageBox.warning(self, "SiteSorter", str(e))
            return
        self.log(f"新規現場を作成しました: {base}")
        self.switch_site(base)

    def _detect_old(self):
        base = self.settings.get("site_folder")
        if not base or not os.path.isdir(base):
            return
        dlg = ArchiveDialog(self, base, preselected=self._archive_checked_paths)
        if not dlg.exec():
            self._archive_checked_paths = set(dlg.selected())
            return
        self._archive_checked_paths = set()
        sel = dlg.selected()
        if not sel:
            return
        ops = archive_files(base, sel, log_cb=self.log)
        self.history.record(ops)
        self.log(f"--- 旧版アーカイブ: {len(ops)}件 ---")
        self.refresh_inbox()
        self._recalc_capacity()

    # ---------- ロック中リトライ ----------
    def add_retry_items(self, items: list):
        known = {it["path"] for it in self.retry_items}
        for it in items:
            if it["path"] not in known:
                self.retry_items.append(it)
                known.add(it["path"])
        self._update_retry_button()

    def _update_retry_button(self):
        self.retry_items = [it for it in self.retry_items
                            if os.path.exists(it["path"])]
        n = len(self.retry_items)
        self.btn_retry.setText(f"ロック中: {n}")
        self.btn_retry.setEnabled(n > 0)

    def _open_retry(self):
        base = self.settings.get("site_folder")
        if not base or not self.retry_items:
            return
        dlg = RetryDialog(self, self.retry_items)
        if not dlg.exec():
            self._update_retry_button()
            return
        sel = dlg.selected()
        resolver = dialogs.gui_resolver(self)
        still = []
        done_paths = set()
        groups = {}
        for it in sel:
            groups.setdefault(it.get("toggle"), []).append(it["path"])
        for toggle, paths in groups.items():
            sk = []
            ops = ingest_drop(base, paths, toggle=toggle,
                              log_cb=self.log, resolver=resolver, skipped=sk)
            self.history.record(ops)
            done_paths |= {p for p in paths}
            still += sk
        sel_paths = {it["path"] for it in sel}
        self.retry_items = ([it for it in self.retry_items
                             if it["path"] not in sel_paths] + still)
        self._update_retry_button()
        self.refresh_inbox()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "現場の作業フォルダを選択")
        if path:
            self._set_folder(path)

    def switch_site(self, path: str):
        self._set_folder(path)

    def _set_folder(self, path: str, save: bool = True):
        path = (path or "").strip()
        if not path:
            return
        self.settings["site_folder"] = path
        hist = [p for p in self.settings.get("site_history", []) if p != path]
        hist.insert(0, path)
        self.settings["site_history"] = hist[:MAX_SITES]
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        self.site_combo.addItems(self.settings["site_history"])
        self.site_combo.setCurrentIndex(0)
        self.site_combo.blockSignals(False)
        if save:
            save_settings(self.settings)
        if os.path.isdir(path):
            ensure_structure(path)
            self.log(f"対象フォルダ: {path}")
        if self.zone:
            self.zone.set_site(os.path.basename(path))
        self.refresh_inbox()
        cached = self.settings.get("capacity_cache", {}).get(path)
        if cached:
            self._show_capacity(cached)
        self._recalc_capacity()

    def refresh_inbox(self):
        self.inbox_list.clear()
        base = self.settings.get("site_folder")
        ok = bool(base) and os.path.isdir(base)
        self.drop_frame.setEnabled(ok)
        if not ok:
            self.inbox_label.setText("00_Inbox 待機: 現場フォルダ未指定")
            self._update_buttons()
            return
        inbox = os.path.join(base, rules.INBOX)
        dirs = []
        if os.path.isdir(inbox):
            dirs = sorted(d for d in os.listdir(inbox)
                          if os.path.isdir(os.path.join(inbox, d)))
        files = scan_inbox(base)
        total = sum(os.path.getsize(f) for f in files)
        for d in dirs:
            self.inbox_list.addItem(f"📁 {d}/")
        for f in files:
            self.inbox_list.addItem(
                f"{os.path.basename(f)}  ({fmt_size(os.path.getsize(f))})")
        self.inbox_label.setText(
            f"00_Inbox 待機: <b style='color:{COLORS['accent']}'>"
            f"{len(files)}件</b>"
            + (f" ＋フォルダ{len(dirs)}" if dirs else "")
            + f" / 合計 {fmt_size(total)}")
        self._update_buttons()

    def _update_buttons(self):
        running = self.worker is not None and self.worker.isRunning()
        has_folder = bool(self.settings.get("site_folder"))
        self.btn_run.setEnabled(has_folder and not running)
        can = self.history.can_undo() and not running
        self.btn_undo.setEnabled(can)
        if hasattr(self, "btn_undo2"):
            self.btn_undo2.setEnabled(can)

    def log(self, msg: str):
        self.log_view.appendPlainText(msg)

    def _run(self):
        base = self.settings.get("site_folder")
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "SiteSorter", "現場フォルダを指定してください。")
            return
        files = scan_inbox(base)
        if not files:
            self.log("00_Inbox にファイルがありません。")
            return
        reply = QMessageBox.question(
            self, "一括仕分けの確認",
            f"00_Inbox 内の {len(files)} 件のファイルを仕分けします。\nよろしいですか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        # 要確認項目（複数マッチ・zip）をメインスレッドで先に解決
        decisions = dialogs.confirm_inbox_pending(self, preflight(base))
        resolver = ((lambda kind, name, cands: decisions.get(name))
                    if decisions else None)
        self.progress.setValue(0)
        self.worker = SortWorker(base, resolver=resolver)
        self.worker.progress.connect(
            lambda v, name: (self.progress.setValue(v),
                             self.progress.setFormat(f"%p%  {name}")))
        self.worker.log.connect(self.log)
        self.worker.skipped_found.connect(self.add_retry_items)
        self.worker.finished_batch.connect(self._on_finished)
        self._update_buttons()
        self.worker.start()

    def _on_finished(self, ops: list):
        self.history.record(ops)
        self.progress.setValue(100)
        self.progress.setFormat("完了")
        self.log(f"--- 処理完了: {len(ops)}操作 ---")
        self.refresh_inbox()
        self._recalc_capacity()

    def _undo(self):
        n = self.history.undo_last(log_cb=self.log)
        self.log(f"--- Undo完了: {n}操作を元に戻しました ---")
        self.refresh_inbox()
        if self.stack.currentIndex() == 1:
            self._refresh_history_list()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
