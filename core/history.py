# -*- coding: utf-8 -*-
"""操作履歴 v2: 操作単位で記録、直近50操作。バッチ単位Undo対応。

op種別: move（src←dstへ戻す） / copy（dstを削除） / copy_dual（dst,dst2を削除）
旧形式（バッチの入れ子配列）は読み込み時に自動移行。
"""
import json
import os

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
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.ops[-MAX_OPS:], f, ensure_ascii=False, indent=1)

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
    def _undo_op(self, op: dict, log_cb=None) -> bool:
        from core.organizer import move_file
        kind = op.get("op", "move")
        try:
            if kind == "move":
                if not os.path.exists(op["dst"]):
                    raise FileNotFoundError(op["dst"])
                actual = move_file(op["dst"], op["src"])
                if log_cb:
                    log_cb(f"[Undo] {os.path.basename(op['dst'])} → {actual}")
            elif kind in ("copy", "copy_dual"):
                targets = [op["dst"]] + ([op["dst2"]] if kind == "copy_dual" else [])
                for t in targets:
                    if os.path.exists(t):
                        os.remove(t)
                if log_cb:
                    log_cb(f"[Undo] コピー削除: {os.path.basename(op['dst'])}"
                           + ("（2箇所）" if kind == "copy_dual" else ""))
            else:
                return False
            return True
        except (OSError, IOError, FileNotFoundError) as e:
            if log_cb:
                log_cb(f"[Undo失敗] {os.path.basename(str(op.get('dst')))}: {e}")
            return False

    def undo_last(self, log_cb=None) -> int:
        """直近バッチ（同一batch IDの操作一式）をまとめてUndo"""
        if not self.ops:
            return 0
        last_batch = self.ops[-1].get("batch")
        count = 0
        while self.ops and self.ops[-1].get("batch") == last_batch:
            op = self.ops.pop()
            if self._undo_op(op, log_cb):
                count += 1
        self._save()
        return count

    def undo_one(self, log_cb=None) -> int:
        """直近1操作のみUndo"""
        if not self.ops:
            return 0
        op = self.ops.pop()
        ok = self._undo_op(op, log_cb)
        self._save()
        return 1 if ok else 0
