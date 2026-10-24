# -*- coding: utf-8 -*-
"""旧バージョン検知（UI非依存・完全承認制のための候補抽出のみ）

同名ベース＋版番号/日付サフィックス（_v2 / (2) / _20260601 / 2026-06-01 / rev3 等）
のグループから、最新（更新日時が最も新しい）以外を旧版候補として返す。
00_Inbox / 11_図面_提出済 / 12_社外受領データ / 99_Archive / 30_現場写真 /
21_3Dスキャン は対象外。
"""
import os
import re

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rules

SUFFIX_RE = re.compile(
    r"(?:[\s_\-]*(?:[vV]\.?\d{1,3}|\(\d+\)|\d{8}(?:_\d{6})?"
    r"|\d{4}-\d{2}-\d{2}|[rR][eE][vV]\.?\d{1,3}))+$")

# 写真（「現場 (2).jpg」「現場_20260601.jpg」は別の写真）と3Dスキャン（連番・日付付きの
# スキャンデータ）は版違いではないので対象外
EXCLUDE_TOPS = {rules.INBOX, rules.SUBMIT_DIR, rules.RECEIVE_DIR, rules.ARCHIVE,
                "30_現場写真", "21_3Dスキャン"}


def base_key(stem: str) -> str:
    """版番号・日付サフィックスを除いたベース名"""
    k = SUFFIX_RE.sub("", stem).rstrip(" _-")
    return k or stem


def find_old_candidates(base: str) -> list:
    """旧版候補 [{"path", "rel", "keep"}...] を返す（keep=残す最新版の相対パス）"""
    out = []
    exclude = set(EXCLUDE_TOPS)
    photo = rules.photo_dir()
    if photo:  # ルール編集で写真フォルダ名を変えていても除外する
        exclude.add(photo.replace("\\", "/").split("/")[0])
    for dirpath, dirs, files in os.walk(base):
        rel = os.path.relpath(dirpath, base)
        if rel != ".":
            top = rel.split(os.sep)[0]
            if top in exclude:
                dirs[:] = []
                continue
        groups = {}
        for f in files:
            stem, ext = os.path.splitext(f)
            groups.setdefault(
                (base_key(stem).lower(), ext.lower()), []).append(f)
        for names in groups.values():
            if len(names) < 2:
                continue
            paths = [os.path.join(dirpath, n) for n in names]
            try:
                newest = max(paths, key=os.path.getmtime)
            except OSError:
                continue
            for p in paths:
                if p != newest:
                    out.append({"path": p,
                                "rel": os.path.relpath(p, base),
                                "keep": os.path.relpath(newest, base)})
    return sorted(out, key=lambda d: d["rel"])
