# -*- coding: utf-8 -*-
"""操作履歴 v2: 操作単位で記録、直近50操作。バッチ単位Undo対応。

op種別: move（src←dstへ戻す） / copy（dstを削除） / copy_dual（dst,dst2を削除）
旧形式（バッチの入れ子配列）は読み込み時に自動移行。
"""
import json
import os

from config import write_json_atomic

MAX_OPS = 50


class History:
    def __init__(self, path: str):
        self.path = path
        self.ops = self._load()

    def _load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        if data and isinstance(data[0], list):  # 旧形式: [[{src,dst,time},..],..]
            ops = []
            for i, batch in enumerate(data):
                for m in batch:
                    ops.append({"op": "move", "src": m.get("src"),
                                "dst": m.get("dst"), "time": m.get("time"),
                                "batch": f"legacy_{i}"})
            return ops[-MAX_OPS:]
        return [o for o in data if isinstance(o, dict)][-MAX_OPS:]

    def _save(self) -> None:
        write_json_atomic(self.path, self.ops[-MAX_OPS:], indent=1)

    # ---------- 記録 ----------
    def record(self, ops: list) -> None:
        """1回の処理結果（操作リスト）を追記"""
        if ops:
            self.ops = (self.ops + list(ops))[-MAX_OPS:]
            self._save()

    # ---------- 参照 ----------
    def can_undo(self) -> bool:
        return bool(self.ops)

    def recent(self, n: int = MAX_OPS) -> list:
        return list(self.ops[-n:])

    # ---------- Undo ----------
    # 1操作のUndo結果: 戻せた / 戻す対象が無い（削除済み等） / 失敗（使用中等・再試行可）
    OK, GONE, FAILED = "ok", "gone", "failed"

    def _undo_op(self, op: dict, log_cb=None) -> str:
        from core.organizer import _remove_file, move_file, move_tree, unique_path
        kind = op.get("op", "move")
        try:
            if kind == "move":
                if not os.path.exists(op["dst"]):
                    raise FileNotFoundError(op["dst"])
                if os.path.isdir(op["dst"]):
                    # フォルダは別ドライブでも戻せるよう専用の移動を使う
                    actual = move_tree(op["dst"], unique_path(op["src"]), log_cb)
                else:
                    actual = move_file(op["dst"], op["src"])
                if log_cb:
                    log_cb(f"[Undo] {os.path.basename(op['dst'])} → {actual}")
            elif kind in ("copy", "copy_dual"):
                targets = [op["dst"]] + ([op["dst2"]] if kind == "copy_dual" else [])
                for t in targets:
                    if os.path.exists(t):
                        _remove_file(t)
                if log_cb:
                    log_cb(f"[Undo] コピー削除: {os.path.basename(op['dst'])}"
                           + ("（2箇所）" if kind == "copy_dual" else ""))
            else:
                return self.GONE
            return self.OK
        except (OSError, IOError) as e:
            if kind == "move" and not os.path.exists(op["dst"]):
                # 移動先から消えている（削除・移動済み）→ 何度試しても戻せない
                if log_cb:
                    log_cb(f"[Undo不可] {os.path.basename(str(op.get('dst')))}: "
                           f"移動先にありません（削除・移動済み）")
                return self.GONE
            # 使用中・元のドライブが未接続など → ファイルは残っているので後で再試行できる
            if log_cb:
                log_cb(f"[Undo失敗] {os.path.basename(str(op.get('dst')))}: {e}"
                       "（履歴に残しました。使用中のファイルを閉じてから再度お試しください）")
            return self.FAILED

    def _undo_ops(self, targets: list, log_cb=None) -> int:
        """targets（self.ops から取り除き済み）を新しい順にUndo。

        失敗した操作は再試行できるよう元の順番で履歴の末尾に戻す。
        """
        count, failed = 0, []
        for op in reversed(targets):
            res = self._undo_op(op, log_cb)
            if res == self.OK:
                count += 1
            elif res == self.FAILED:
                failed.append(op)
        self.ops = self.ops + list(reversed(failed))
        self._save()
        return count

    def undo_last(self, log_cb=None) -> int:
        """直近バッチ（同一batch IDの操作一式）をまとめてUndo"""
        if not self.ops:
            return 0
        last_batch = self.ops[-1].get("batch")
        targets = []
        while self.ops and self.ops[-1].get("batch") == last_batch:
            targets.insert(0, self.ops.pop())
        return self._undo_ops(targets, log_cb)

    def undo_batch(self, batch, log_cb=None) -> int:
        """指定バッチの操作一式をUndo（ドロップ直後の「元に戻す」用）。

        その後に別の処理が記録されていても、このバッチだけを戻す。
        既にUndo済み・履歴から押し出された場合は 0。
        """
        targets = [o for o in self.ops if o.get("batch") == batch]
        if not targets:
            return 0
        self.ops = [o for o in self.ops if o.get("batch") != batch]
        return self._undo_ops(targets, log_cb)

    def undo_one(self, log_cb=None) -> int:
        """直近1操作のみUndo"""
        if not self.ops:
            return 0
        return self._undo_ops([self.ops.pop()], log_cb)
