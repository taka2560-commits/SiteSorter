# -*- coding: utf-8 -*-
"""ロック中ファイルのリトライリストダイアログ"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

TOGGLE_LABEL = {None: "通常", "submit": "提出", "receive": "受領"}


class RetryDialog(QDialog):
    def __init__(self, parent, items: list):
        super().__init__(parent)
        self.setWindowTitle("ロック中ファイルのリトライ")
        self.resize(560, 360)
        lay = QVBoxLayout(self)

        info = QLabel("使用中（ロック検知）でスキップされたファイルです。\n"
                      "AutoCAD等を閉じてから、チェックして「再試行」してください。")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.list = QListWidget()
        for it in items:
            exists = os.path.exists(it["path"])
            text = (f"{os.path.basename(it['path'])}"
                    f"　[{TOGGLE_LABEL.get(it.get('toggle'), '通常')}] "
                    f"{it.get('reason', '')}"
                    + ("" if exists else "　※ファイルが見当たりません"))
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if exists else Qt.Unchecked)
            item.setData(Qt.UserRole, it)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.addStretch()
        b_ok = QPushButton("チェックした項目を再試行")
        b_ok.setObjectName("primary")
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("閉じる")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_ok)
        row.addWidget(b_cancel)
        lay.addLayout(row)

    def selected(self) -> list:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out
