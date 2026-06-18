# -*- coding: utf-8 -*-
"""確認ダイアログ群（複数マッチ / zip移動先 / フォルダ投入）"""
from PySide6.QtWidgets import QInputDialog, QMessageBox

import rules


def ask_multi(parent, name: str, candidates: list):
    """複数カテゴリ該当 → 移動先を選択。キャンセル=None"""
    item, ok = QInputDialog.getItem(
        parent, "移動先の選択",
        f"「{name}」は複数カテゴリに該当します。\n移動先を選んでください:",
        list(candidates), 0, False)
    return item if ok else None

def ask_zip(parent, name: str):
    """zip（トグルなし）→ 移動先を選択。キャンセル=None"""
    cands = []
    for f in sorted(rules.FOLDERS) + [rules.RECEIVE_DIR, rules.OTHERS]:
        if f not in cands:
            cands.append(f)
    item, ok = QInputDialog.getItem(
        parent, "zipファイルの移動先",
        f"「{name}」の移動先を選んでください。\n"
        "※納品zipはドロップゾーンの「提出用」トグルで 11_図面_提出済 へ入ります。",
        cands, cands.index(rules.OTHERS), False)
    return item if ok else None


def ask_folder(parent, name: str):
    """フォルダ投入（トグルなし）→ expand / keep / None（キャンセル）"""
    box = QMessageBox(parent)
    box.setWindowTitle("フォルダの処理方法")
    box.setText(f"フォルダ「{name}」が投入されました。\nどう処理しますか？")
    b_expand = box.addButton("個別仕分け（直下1階層のみ）", QMessageBox.AcceptRole)
    b_keep = box.addButton("丸ごとInboxへ維持移動", QMessageBox.AcceptRole)
    box.addButton("キャンセル", QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is b_expand:
        return "expand"
    if clicked is b_keep:
        return "keep"
    return None


def gui_resolver(parent):
    """ドロップ即時仕分け用（メインスレッドで同期的に呼ばれる前提）"""
    def resolver(kind, name, candidates):
        if kind == "multi":
            return ask_multi(parent, name, candidates)
        if kind == "zip":
            return ask_zip(parent, name)
        if kind == "folder":
            return ask_folder(parent, name)
        return None
    return resolver


def confirm_inbox_pending(parent, pending: list) -> dict:
    """Inbox一括処理前の要確認項目をまとめて解決 → {ファイル名: 移動先}

    キャンセルした項目は辞書に含めない（=スキップされInboxに残る）。
    """
    decisions = {}
    for name, kind, cands in pending:
        if kind == "multi":
            folder = ask_multi(parent, name, cands)
        else:
            folder = ask_zip(parent, name)
        if folder:
            decisions[name] = folder
    return decisions
