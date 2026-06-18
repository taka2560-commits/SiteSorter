# -*- coding: utf-8 -*-
"""仕分けルール定義 v2（rules.json: 拡張子＋キーワード辞書。GUIから編集可能）"""
import json
import os
import sys

from config import RULES_PATH as _CONFIG_RULES_PATH

RULES_PATH = _CONFIG_RULES_PATH  # %APPDATA%\SiteSorter\rules.json

INBOX = "00_Inbox"
WORK_DIR = "10_図面_作業用"
SUBMIT_DIR = "11_図面_提出済"      # 聖域（提出トグル専用）
RECEIVE_DIR = "12_社外受領データ"  # 原本保管
DRAWING_PDF_DIR = "13_図面_PDF"    # 図面PDF専用
OTHERS = "90_その他"
ARCHIVE = "99_Archive_旧データ"
PROJECT_FOLDER = "21_3Dスキャン/02_プロジェクトデータ"

# 図面PDF判定用キーワード（ファイル名にこれらを含むPDFは13_図面_PDFへ）
DRAWING_PDF_KEYWORDS = ["図面", "図"]

DEFAULT = {
    "folders": {
        WORK_DIR: [".dwg", ".dxf", ".lsp"],
        DRAWING_PDF_DIR: [".pdf"],
        "20_測量データ": [".sim", ".sima", ".csv"],
        "21_3Dスキャン/01_RAWデータ_FLS": [".fls"],
        PROJECT_FOLDER: [],
        "21_3Dスキャン/03_エクスポート点群": [".e57", ".las", ".xyz", ".pts"],
        "30_現場写真": [".jpg", ".jpeg", ".png"],
        "40_報告書・書類": [".xlsx", ".docx"],
    },
    "keywords": {
        DRAWING_PDF_DIR: list(DRAWING_PDF_KEYWORDS),
        RECEIVE_DIR: ["支給", "参考", "元図", "貸与データ"],
        "20_測量データ": ["座標", "観測", "水準", "トラバース", "野帳", "手簿", "網平均"],
        "40_報告書・書類": ["報告書", "計算書", "打合せ", "議事録", "台帳", "計画書", "安全"],
    },
    "project_exts": [],
}

FOLDERS = {}
KEYWORDS = {}
PROJECT_EXTS = []
RULES = {}  # v1互換エイリアス（= FOLDERS）


def _norm_exts(exts):
    out = set()
    for e in exts:
        e = str(e).lower().strip()
        if e and not e.startswith("."):
            e = "." + e
        if len(e) >= 2:
            out.add(e)
    return out


def _apply(data: dict) -> None:
    global FOLDERS, KEYWORDS, PROJECT_EXTS, RULES
    FOLDERS = {str(f).strip(): _norm_exts(x)
               for f, x in data.get("folders", {}).items() if str(f).strip()}
    KEYWORDS = {str(f).strip(): [str(k) for k in kws if str(k).strip()]
                for f, kws in data.get("keywords", {}).items() if str(f).strip()}
    PROJECT_EXTS = sorted(_norm_exts(data.get("project_exts", [])))
    if PROJECT_FOLDER in FOLDERS:
        FOLDERS[PROJECT_FOLDER] |= set(PROJECT_EXTS)
    RULES = FOLDERS


def _migrate_v1(old: dict) -> dict:
    """v1（{フォルダ: [拡張子]} フラット形式）→ v2"""
    return {"folders": old,
            "keywords": json.loads(json.dumps(DEFAULT["keywords"])),
            "project_exts": []}


def _migrate_drawing_pdf(data: dict) -> bool:
    """既存rules.jsonに13_図面_PDF（図面PDF専用）を後付け追加する移行処理。

    既存の設定（フォルダ・キーワードの追加/変更内容）はそのまま維持し、
    13_図面_PDFが無い場合のみ追加する。また .pdf が既に他フォルダの
    拡張子ルールに含まれている場合は、判定が競合しないようそこから外す。
    変更があった場合はTrueを返す（呼び出し側で保存）。
    """
    changed = False
    folders = data.setdefault("folders", {})
    keywords = data.setdefault("keywords", {})

    if DRAWING_PDF_DIR not in folders:
        folders[DRAWING_PDF_DIR] = [".pdf"]
        changed = True
    if DRAWING_PDF_DIR not in keywords:
        keywords[DRAWING_PDF_DIR] = list(DRAWING_PDF_KEYWORDS)
        changed = True

    for folder, exts in folders.items():
        if folder == DRAWING_PDF_DIR or not isinstance(exts, list):
            continue
        if ".pdf" in exts:
            exts.remove(".pdf")
            changed = True

    return changed


def _save_raw(data: dict) -> None:
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_rules() -> None:
    try:
        with open(RULES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if "folders" not in data:  # v1形式 → 自動移行
            data = _migrate_v1(data)
            _save_raw(data)
        if _migrate_drawing_pdf(data):  # 図面PDFフォルダを後付け追加
            _save_raw(data)
        _apply(data)
        if not FOLDERS:
            raise ValueError("empty")
    except (OSError, ValueError, AttributeError):
        _apply(json.loads(json.dumps(DEFAULT)))


def save_rules(folders=None, keywords=None, project_exts=None) -> None:
    data = {
        "folders": {f: sorted(x) for f, x in
                    (folders if folders is not None else FOLDERS).items()},
        "keywords": {f: list(k) for f, k in
                     (keywords if keywords is not None else KEYWORDS).items()},
        "project_exts": sorted(project_exts if project_exts is not None
                               else PROJECT_EXTS),
    }
    _save_raw(data)
    _apply(data)


def photo_dir() -> str:
    for folder in sorted(FOLDERS):
        if FOLDERS[folder] & {".jpg", ".jpeg"}:
            return folder
    return ""


def all_dirs() -> list:
    fixed = {INBOX, WORK_DIR, SUBMIT_DIR, RECEIVE_DIR, OTHERS, ARCHIVE}
    return sorted(fixed | set(FOLDERS))


def classify(filename: str) -> dict:
    """仕分け判定（優先順位: ②キーワード → ③拡張子 → ④90_その他）

    ①トグルは呼び出し側（ingest_drop）で処理。
    13_図面_PDF（図面PDF）のキーワードはPDF限定で、③拡張子と同じ段で判定する
    （他フォルダのキーワード一致がDWG等のファイルに誤爆しないようにするため）。
    戻り値: {"folder": str} / {"multi": [候補,...]} / {"zip": True}
    """
    ext = os.path.splitext(filename)[1].lower()
    hits = [f for f in sorted(KEYWORDS)
            if f not in (SUBMIT_DIR, DRAWING_PDF_DIR)
            and any(kw in filename for kw in KEYWORDS[f])]
    if len(hits) > 1:
        return {"multi": hits}
    if len(hits) == 1:
        return {"folder": hits[0]}
    if ext == ".zip":
        return {"zip": True}
    if ext == ".pdf" and DRAWING_PDF_DIR in FOLDERS:
        dp_kws = KEYWORDS.get(DRAWING_PDF_DIR, [])
        if (any(kw in filename for kw in dp_kws)
                or ".pdf" in FOLDERS[DRAWING_PDF_DIR]):
            return {"folder": DRAWING_PDF_DIR}
    for folder in sorted(FOLDERS):
        if ext in FOLDERS[folder]:
            return {"folder": folder}
    return {"folder": OTHERS}


def get_destination(filename: str) -> str:
    """v1互換: 単純判定（multi/zipはOTHERS扱いにせず先頭候補/90）"""
    c = classify(filename)
    if "folder" in c:
        return c["folder"]
    if "multi" in c:
        return c["multi"][0]
    return OTHERS


load_rules()
