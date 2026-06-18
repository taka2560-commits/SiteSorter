# -*- coding: utf-8 -*-
"""容量計算（UI非依存）。21_3Dスキャン配下は別集計。"""
import os

SCAN_DIR = "21_3Dスキャン"


def calc(base: str) -> dict:
    """現場フォルダの総容量と3Dスキャン配下容量（バイト）を返す"""
    total = scan3d = 0
    scan_prefix = os.path.join(base, SCAN_DIR)
    for dirpath, _dirs, files in os.walk(base):
        in_scan = dirpath == scan_prefix or dirpath.startswith(
            scan_prefix + os.sep)
        for f in files:
            try:
                sz = os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
            total += sz
            if in_scan:
                scan3d += sz
    return {"total": total, "scan3d": scan3d}
