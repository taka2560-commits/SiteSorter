# -*- coding: utf-8 -*-
"""エンジンv2テスト（setup.batから実行される）"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules
from core.organizer import ensure_structure, organize, ingest_drop, scan_inbox, send_to_inbox
from core.history import History

ok = ng = 0
def check(name, cond):
    global ok, ng
    print(("  OK " if cond else "  NG ") + name)
    ok += bool(cond); ng += not cond

TODAY = datetime.now().strftime("%Y-%m-%d")
base = tempfile.mkdtemp(prefix="v2_")
inbox = os.path.join(base, rules.INBOX)
ensure_structure(base)
p = lambda *a: os.path.join(base, *a)
def put(d, name, data=b"x"):
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, name); open(fp, "wb").write(data); return fp

print("[1] classify 優先順位")
check("キーワード>拡張子: 座標一覧.pdf→20", rules.get_destination("座標一覧.pdf") == "20_測量データ")
check("csv既定→20", rules.get_destination("data.csv") == "20_測量データ")
check("csv+キーワード→40", rules.get_destination("報告書一覧.csv") == "40_報告書・書類")
check("受領キーワード→12", rules.get_destination("支給データ.dwg") == rules.RECEIVE_DIR)
check("複数マッチ検出", "multi" in rules.classify("座標報告書.pdf"))
check("zip要確認", "zip" in rules.classify("納品.zip"))
check("点群→21/03", rules.get_destination("scan.las") == "21_3Dスキャン/03_エクスポート点群")
check("ルール外→90", rules.get_destination("メモ.txt") == rules.OTHERS)

print("[1b] 図面PDF判定（13_図面_PDF）")
check("拡張子.pdf既定→13", rules.get_destination("資料.pdf") == rules.DRAWING_PDF_DIR)
check("図面キーワード→13", rules.get_destination("A-1平面図.pdf") == rules.DRAWING_PDF_DIR)
check("報告書キーワード優先→40", rules.get_destination("完成報告書.pdf") == "40_報告書・書類")
check("DWGの「図」は誤爆しない", rules.get_destination("平面図.dwg") == rules.WORK_DIR)
check("13_図面_PDFがall_dirsに含まれる", rules.DRAWING_PDF_DIR in rules.all_dirs())

print("[2] Inbox一括仕分け（multi/zipはスキップ、ロック検知）")
put(inbox, "道路.dwg"); put(inbox, "座標.csv"); put(inbox, "納品.zip")
put(inbox, "座標報告書.pdf"); put(inbox, "支給図面.dxf")
put(inbox, "編集中.dwg"); put(inbox, "編集中.dwl")  # ロック
logs = []
ops = organize(base, log_cb=logs.append)
check("dwg→10", os.path.exists(p(rules.WORK_DIR, "道路.dwg")))
check("受領キーワードは12/日付_受領へ", os.path.exists(p(rules.RECEIVE_DIR, f"{TODAY}_受領", "支給図面.dxf")))
check("zipはInboxに残る", os.path.exists(p(rules.INBOX, "納品.zip")))
check("multiはInboxに残る", os.path.exists(p(rules.INBOX, "座標報告書.pdf")))
check("ロック中はスキップ", os.path.exists(p(rules.INBOX, "編集中.dwg")))
check("スキップ理由がログに", any("複数カテゴリ" in l for l in logs) and any("ロック検知" in l for l in logs))

print("[3] resolverで解決")
ops2 = organize(base, resolver=lambda kind, name, cands: (cands[0] if kind == "multi" else rules.OTHERS))
check("multi解決→20", os.path.exists(p("20_測量データ", "座標報告書.pdf")))
check("zip解決→90", os.path.exists(p(rules.OTHERS, "納品.zip")))

print("[4] 提出トグル（同時コピー・zip例外・元ファイル維持）")
desk = tempfile.mkdtemp(prefix="desk_")
f1 = put(desk, "平面図.dwg"); f2 = put(desk, "納品物.zip")
ops3 = ingest_drop(base, [f1, f2], toggle="submit")
check("10へコピー", os.path.exists(p(rules.WORK_DIR, "平面図.dwg")))
check("11/日付_提出へコピー", os.path.exists(p(rules.SUBMIT_DIR, f"{TODAY}_提出", "平面図.dwg")))
check("元ファイル維持", os.path.exists(f1) and os.path.exists(f2))
check("zipは11のみ", os.path.exists(p(rules.SUBMIT_DIR, f"{TODAY}_提出", "納品物.zip"))
      and not os.path.exists(p(rules.WORK_DIR, "納品物.zip")))
check("copy_dual記録", any(o["op"] == "copy_dual" for o in ops3))

print("[5] 受領トグル（ファイル=日付フォルダ / フォルダ=丸ごと）")
f3 = put(desk, "元図.pdf")
d1 = os.path.join(desk, "受領フォルダ"); put(d1, "中身.dwg")
ops4 = ingest_drop(base, [f3, d1], toggle="receive")
check("ファイル→12/日付_受領", os.path.exists(p(rules.RECEIVE_DIR, f"{TODAY}_受領", "元図.pdf")))
check("フォルダ→12直下丸ごと", os.path.exists(p(rules.RECEIVE_DIR, "受領フォルダ", "中身.dwg")))

print("[6] トグルなしドロップ（即仕分け、未確定はInbox仮置き、フォルダ=維持移動）")
f4 = put(desk, "断面.dxf"); f5 = put(desk, "謎ファイル.zip")
d2 = os.path.join(desk, "現場データ一式"); put(d2, "x.csv")
ops5 = ingest_drop(base, [f4, f5, d2])
check("dxf即仕分け→10", os.path.exists(p(rules.WORK_DIR, "断面.dxf")))
check("zip未確定→Inbox仮置き", os.path.exists(p(rules.INBOX, "謎ファイル.zip")))
check("フォルダ維持移動→Inbox", os.path.exists(p(rules.INBOX, "現場データ一式", "x.csv")))

print("[7] フォルダexpand（直下1階層のみ）")
d3 = os.path.join(desk, "展開対象"); put(d3, "y.sim"); 
sub = os.path.join(d3, "深い階層"); put(sub, "z.dwg")
ops6 = ingest_drop(base, [d3], resolver=lambda k, n, c: "expand" if k == "folder" else None)
check("直下ファイルは仕分け", os.path.exists(p("20_測量データ", "y.sim")))
check("サブフォルダはInboxへ", os.path.exists(p(rules.INBOX, "深い階層", "z.dwg")))

print("[8] 履歴v2: バッチUndo・copy_dual Undo・50件制限・旧形式移行")
hist = History(os.path.join(base, "h.json"))
hist.record(ops3)  # 提出（copy_dual + copy）
n = hist.undo_last()
check("提出Undoで2箇所削除", not os.path.exists(p(rules.WORK_DIR, "平面図.dwg"))
      and not os.path.exists(p(rules.SUBMIT_DIR, f"{TODAY}_提出", "平面図.dwg"))
      and not os.path.exists(p(rules.SUBMIT_DIR, f"{TODAY}_提出", "納品物.zip")))
check("元ファイルは残る", os.path.exists(f1))
hist.record(ops4)
hist.undo_last()
check("受領Undoで復元", os.path.exists(f3) and os.path.exists(os.path.join(d1, "中身.dwg")))
big = [{"op": "move", "src": f"/a/{i}", "dst": f"/b/{i}", "time": "t", "batch": str(i)} for i in range(80)]
hist.record(big)
check("50件制限", len(hist.recent()) == 50)
old_path = os.path.join(base, "old.json")
json.dump([[{"src": "/s1", "dst": "/d1", "time": "t"}], [{"src": "/s2", "dst": "/d2", "time": "t"}]],
          open(old_path, "w"))
h2 = History(old_path)
check("旧形式の自動移行", len(h2.recent()) == 2 and h2.recent()[0]["op"] == "move")

print("[9] rules.json v1→v2移行")
v1 = {"10_図面・CAD": [".dwg"], "20_測量データ": [".csv"]}
json.dump(v1, open(rules.RULES_PATH, "w", encoding="utf-8"), ensure_ascii=False)
rules.load_rules()
check("v1フォルダ維持", "10_図面・CAD" in rules.FOLDERS)
check("キーワード辞書が補完される", rules.KEYWORDS.get("20_測量データ"))
saved = json.load(open(rules.RULES_PATH, encoding="utf-8"))
check("v2形式で保存", "folders" in saved and "keywords" in saved)
os.remove(rules.RULES_PATH)
rules.load_rules()
check("既定に復帰", rules.WORK_DIR in rules.FOLDERS)

print("[9b] 既存rules.json(v2)への13_図面_PDF自動追加")
old_v2 = {
    "folders": {rules.WORK_DIR: [".dwg"], "40_報告書・書類": [".pdf", ".xlsx"]},
    "keywords": {"40_報告書・書類": ["報告書"]},
    "project_exts": [],
}
json.dump(old_v2, open(rules.RULES_PATH, "w", encoding="utf-8"), ensure_ascii=False)
rules.load_rules()
check("13_図面_PDFが追加される", rules.DRAWING_PDF_DIR in rules.FOLDERS)
check("図面PDFキーワードが追加される",
      rules.KEYWORDS.get(rules.DRAWING_PDF_DIR) == rules.DRAWING_PDF_KEYWORDS)
check("40から.pdfが除去される", ".pdf" not in rules.FOLDERS["40_報告書・書類"])
check("既存設定(40のxlsx等)は維持", ".xlsx" in rules.FOLDERS["40_報告書・書類"])
saved2 = json.load(open(rules.RULES_PATH, encoding="utf-8"))
check("移行結果が保存される", rules.DRAWING_PDF_DIR in saved2["folders"])
os.remove(rules.RULES_PATH)
rules.load_rules()

print("[10] project_exts反映")
rules.save_rules(project_exts=[".lsproj", "rcp"])
check("21/02に反映（.付与/正規化）", {".lsproj", ".rcp"} <= rules.FOLDERS[rules.PROJECT_FOLDER])
os.remove(rules.RULES_PATH); rules.load_rules()


print("[12] preflight（事前確認リスト）とフォルダキャンセル")
from core.organizer import preflight
base3 = tempfile.mkdtemp(prefix="v2c_")
ensure_structure(base3)
ib = os.path.join(base3, rules.INBOX)
open(os.path.join(ib, "座標報告書.pdf"), "wb").write(b"x")
open(os.path.join(ib, "謎.zip"), "wb").write(b"x")
open(os.path.join(ib, "普通.dwg"), "wb").write(b"x")
pend = preflight(base3)
kinds = {k for _, k, _ in pend}
check("multi/zipのみ検出", len(pend) == 2 and kinds == {"multi", "zip"})
desk3 = tempfile.mkdtemp(prefix="desk3_")
dC = os.path.join(desk3, "キャンセル対象"); os.makedirs(dC)
open(os.path.join(dC, "f.dwg"), "wb").write(b"x")
opsC = ingest_drop(base3, [dC], resolver=lambda k, n, c: None)
check("フォルダキャンセルで元の場所に残る", os.path.exists(os.path.join(dC, "f.dwg")) and not opsC)
# 決定辞書resolver（メイン処理の方式）
decisions = {"座標報告書.pdf": "40_報告書・書類", "謎.zip": rules.OTHERS}
ops_d = organize(base3, resolver=lambda k, n, c: decisions.get(n))
check("決定辞書で一括解決", os.path.exists(os.path.join(base3, "40_報告書・書類", "座標報告書.pdf"))
      and os.path.exists(os.path.join(base3, rules.OTHERS, "謎.zip"))
      and os.path.exists(os.path.join(base3, rules.WORK_DIR, "普通.dwg")))
shutil.rmtree(base3); shutil.rmtree(desk3)


print("[13] 写真EXIF撮影日（既存機能の退行確認）")
base2 = tempfile.mkdtemp(prefix="v2p_")
ensure_structure(base2)
from PIL import Image
img = Image.new("RGB", (10, 10))
ex = Image.Exif(); ex[36867] = "2026:05:20 10:00:00"
img.save(os.path.join(base2, rules.INBOX, "現場A.jpg"), exif=ex)
Image.new("RGB", (10, 10)).save(os.path.join(base2, rules.INBOX, "スクショ.png"))
organize(base2)
check("EXIF日付フォルダ", os.path.exists(os.path.join(base2, "30_現場写真", "2026-05-20", "現場A.jpg")))
pdirs = os.listdir(os.path.join(base2, "30_現場写真"))
check("EXIFなしフォールバック", any(
    os.path.exists(os.path.join(base2, "30_現場写真", d, "スクショ.png")) for d in pdirs))
shutil.rmtree(base2)

shutil.rmtree(base); shutil.rmtree(desk)
print(f"\n結果: OK={ok} NG={ng}")
sys.exit(1 if ng else 0)
