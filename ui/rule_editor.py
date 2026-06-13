# -*- coding: utf-8 -*-
"""仕分けルールの編集ダイアログ（拡張子タブ＋キーワードタブ → rules.json）"""
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import rules

FIXED = (rules.INBOX, rules.OTHERS, rules.SUBMIT_DIR, rules.ARCHIVE)


def _table(headers, col0_width=200):
    t = QTableWidget(0, 2)
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.setColumnWidth(0, col0_width)
    return t


def _add_row(t, a, b):
    r = t.rowCount()
    t.insertRow(r)
    t.setItem(r, 0, QTableWidgetItem(a))
    t.setItem(r, 1, QTableWidgetItem(b))


def _rows(t):
    out = []
    for r in range(t.rowCount()):
        i0, i1 = t.item(r, 0), t.item(r, 1)
        a = (i0.text() if i0 else "").strip()
        b = (i1.text() if i1 else "").strip()
        if a or b:
            out.append((r, a, b))
    return out


class RuleEditor(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("仕分けルールの編集")
        self.resize(560, 440)
        lay = QVBoxLayout(self)

        tabs = QTabWidget()

        # --- タブ1: 拡張子 ---
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        info1 = QLabel("拡張子はスペース区切り（例: .dwg .dxf）。"
                       "サブフォルダは「21_3Dスキャン/03_エクスポート点群」のように / 区切りで指定。\n"
                       ".jpg/.jpeg を含むフォルダに撮影日サブフォルダが作られます。")
        info1.setWordWrap(True)
        l1.addWidget(info1)
        self.ext_table = _table(["フォルダ名", "対象拡張子"])
        for folder in sorted(rules.FOLDERS):
            _add_row(self.ext_table, folder, " ".join(sorted(rules.FOLDERS[folder])))
        l1.addWidget(self.ext_table)
        r1 = QHBoxLayout()
        b1a = QPushButton("行を追加")
        b1a.clicked.connect(lambda: _add_row(self.ext_table, "", ""))
        b1d = QPushButton("選択行を削除")
        b1d.clicked.connect(lambda: self._del(self.ext_table))
        r1.addWidget(b1a); r1.addWidget(b1d); r1.addStretch()
        l1.addLayout(r1)
        tabs.addTab(w1, "拡張子ルール")

        # --- タブ2: キーワード ---
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        info2 = QLabel("ファイル名に含まれる語で判定（拡張子より優先）。スペース区切りで複数指定。\n"
                       f"複数フォルダに同じ語があると投入時に確認になります。"
                       f"{rules.SUBMIT_DIR} は指定不可（提出トグル専用）。")
        info2.setWordWrap(True)
        l2.addWidget(info2)
        self.kw_table = _table(["フォルダ名", "キーワード"])
        for folder in sorted(rules.KEYWORDS):
            _add_row(self.kw_table, folder, " ".join(rules.KEYWORDS[folder]))
        l2.addWidget(self.kw_table)
        r2 = QHBoxLayout()
        b2a = QPushButton("行を追加")
        b2a.clicked.connect(lambda: _add_row(self.kw_table, "", ""))
        b2d = QPushButton("選択行を削除")
        b2d.clicked.connect(lambda: self._del(self.kw_table))
        r2.addWidget(b2a); r2.addWidget(b2d); r2.addStretch()
        l2.addLayout(r2)
        tabs.addTab(w2, "キーワード辞書")

        lay.addWidget(tabs)

        row = QHBoxLayout()
        row.addStretch()
        b_save = QPushButton("保存")
        b_save.setObjectName("primary")
        b_save.clicked.connect(self._save)
        b_cancel = QPushButton("キャンセル")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_save); row.addWidget(b_cancel)
        lay.addLayout(row)

    def _del(self, t):
        if t.currentRow() >= 0:
            t.removeRow(t.currentRow())

    def _err(self, msg):
        QMessageBox.warning(self, "ルール編集", msg)

    def _save(self):
        folders, seen = {}, {}
        for r, folder, raw in _rows(self.ext_table):
            if not folder:
                return self._err(f"拡張子タブ {r + 1}行目: フォルダ名が空です。")
            if folder in FIXED:
                return self._err(f"「{folder}」は固定フォルダのため指定できません。")
            if folder in folders:
                return self._err(f"フォルダ名「{folder}」が重複しています。")
            exts = set()
            for token in raw.replace(",", " ").split():
                e = token.lower().lstrip("*")
                if not e.startswith("."):
                    e = "." + e
                if len(e) < 2:
                    return self._err(f"「{token}」は拡張子として無効です。")
                if e in seen:
                    return self._err(
                        f"拡張子 {e} が「{seen[e]}」と「{folder}」の両方にあります。")
                seen[e] = folder
                exts.add(e)
            folders[folder] = exts
        if not folders:
            return self._err("拡張子ルールが1件もありません。")

        keywords = {}
        for r, folder, raw in _rows(self.kw_table):
            if not folder:
                return self._err(f"キーワードタブ {r + 1}行目: フォルダ名が空です。")
            if folder == rules.SUBMIT_DIR:
                return self._err(f"{rules.SUBMIT_DIR} にキーワードは設定できません（聖域）。")
            if folder in (rules.INBOX, rules.OTHERS, rules.ARCHIVE):
                return self._err(f"「{folder}」にキーワードは設定できません。")
            if folder in keywords:
                return self._err(f"キーワードタブでフォルダ名「{folder}」が重複しています。")
            kws = [k for k in raw.replace(",", " ").split() if k]
            if kws:
                keywords[folder] = kws

        rules.save_rules(folders=folders, keywords=keywords)
        self.accept()
