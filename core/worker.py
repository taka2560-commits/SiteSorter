# -*- coding: utf-8 -*-
"""QThreadワーカー: 仕分け処理を別スレッドで実行し、進捗をSignalで通知

resolver はワーカースレッドから呼ばれるため、GUIダイアログは不可。
メイン側で事前確認した決定辞書を引く軽量関数のみ渡すこと。
"""
from PySide6.QtCore import QThread, Signal

from core.organizer import organize


class SortWorker(QThread):
    progress = Signal(int, str)      # (0-100, 処理中ファイル名)
    log = Signal(str)
    finished_batch = Signal(list)    # 操作リスト（Undo用）
    skipped_found = Signal(list)     # ロック中等のスキップ項目

    def __init__(self, base: str, resolver=None, parent=None):
        super().__init__(parent)
        self.base = base
        self.resolver = resolver

    def run(self):
        def on_progress(done, total, name):
            self.progress.emit(int(done * 100 / total), name)

        skipped = []
        ops = organize(self.base, progress_cb=on_progress,
                       log_cb=self.log.emit, resolver=self.resolver,
                       skipped=skipped)
        if skipped:
            self.skipped_found.emit(skipped)
        self.finished_batch.emit(ops)


class CapacityWorker(QThread):
    """容量計算ワーカー（非同期・結果はキャッシュへ）"""
    done = Signal(str, dict)  # (base, {"total":…, "scan3d":…})

    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self.base = base

    def run(self):
        from core.capacity import calc
        self.done.emit(self.base, calc(self.base))
