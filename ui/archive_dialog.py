# -*- coding: utf-8 -*-
"""旧バージョン検知ダイアログ（完全承認制: チェックした項目だけ99へ）"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from core.versions import find_old_candidates


class ArchiveDialog(QDialog):
    def __init__(self, parent, base: str, preselected: set = None):
        super().__init__(parent)
        self.base = base
        self.setWindowTitle("旧バージョンの検知")
        self.resize(620, 420)
        lay = QVBoxLayout(self)

        self.cands = find_old_candidates(base)
        info = QLabel(
            f"旧版候補: {len(self.cands)}件（同名ベース＋版番号/日付のうち最新以外）\n"
            "チェックした項目だけを 99_Archive_旧データ へ移動します。自動移動はしません。")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.list = QListWidget()
        for c in self.cands:
            item = QListWidgetItem(f"{c['rel']}　← 最新: {c['keep']}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            pre = preselected and c["path"] in preselected
            item.setCheckState(Qt.Checked if pre else Qt.Unchecked)
            item.setData(Qt.UserRole, c["path"])
            self.list.addItem(item)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        b_all = QPushButton("すべて選択")
        b_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        b_none = QPushButton("すべて解除")
        b_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch()
        b_ok = QPushButton("チェックした項目を 99 へ移動")
        b_ok.setObjectName("primary")
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("キャンセル")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_ok)
        row.addWidget(b_cancel)
        lay.addLayout(row)

        if not self.cands:
            b_ok.setEnabled(False)

    def _set_all(self, state):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def selected(self) -> list:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out
