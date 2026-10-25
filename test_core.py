# -*- coding: utf-8 -*-
"""エンジンv2テスト（setup.batから実行される）"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

# 設定の保存先を一時フォルダへ切り替えてから本体を読み込む。
# このテストは rules.json を書き換え・削除するため、実環境の
# %APPDATA%\SiteSorter（ユーザーのルール）を壊さないよう隔離する。
DATA_TMP = tempfile.mkdtemp(prefix="sitesorter_data_")
os.environ["APPDATA"] = DATA_TMP  # Windows
os.environ["HOME"] = DATA_TMP     # Linux（~/.config）

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules
from core.organizer import ensure_structure, organize, ingest_drop
from core.history import History

if not rules.RULES_PATH.startswith(DATA_TMP):
    sys.exit("中止: rules.json の保存先が一時フォルダではありません: " + rules.RULES_PATH)

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

print("[14] ドロップの書き込み中チェック（待機は1回だけ・判定は維持）")
import threading
import time
base4 = tempfile.mkdtemp(prefix="v2w_")
ensure_structure(base4)
desk4 = tempfile.mkdtemp(prefix="desk4_")
many = [put(desk4, "w%02d.dwg" % i) for i in range(6)]
t0 = time.perf_counter()
ops_w = ingest_drop(base4, many)
check("6件でも待ちは1回分（2秒未満）", time.perf_counter() - t0 < 2.0 and len(ops_w) == 6)
growing = put(desk4, "書込中.dwg")
stop = threading.Event()
def _writer():
    with open(growing, "ab") as fw:
        while not stop.is_set():
            fw.write(b"x"); fw.flush(); time.sleep(0.02)
th = threading.Thread(target=_writer); th.start()
time.sleep(0.1)
sk_w = []
try:
    ingest_drop(base4, [growing], toggle="receive", skipped=sk_w)
finally:
    stop.set(); th.join()
check("書き込み中はスキップ（toggle付きで収集）", len(sk_w) == 1
      and sk_w[0]["reason"] == "書き込み中" and sk_w[0]["toggle"] == "receive")
check("書き込み中のファイルは元の場所に残る", os.path.exists(growing))
shutil.rmtree(base4); shutil.rmtree(desk4)

print("[15] 一括仕分け中にInboxのファイルが消えても止まらない")
base5 = tempfile.mkdtemp(prefix="v2g_")
ensure_structure(base5)
ib5 = os.path.join(base5, rules.INBOX)
for n in ("a.dwg", "b.dwg", "c.dwg"):
    put(ib5, n)
def _vanish(done, total, name):
    gone = os.path.join(ib5, "c.dwg")
    if name == "a.dwg" and os.path.exists(gone):
        os.remove(gone)  # 処理中にエクスプローラで削除された想定
logs5 = []
try:
    ops_g = organize(base5, progress_cb=_vanish, log_cb=logs5.append)
    raised = None
except Exception as e:
    ops_g, raised = [], e
check("例外で止まらない", raised is None)
check("移動済みの2件は操作リストに残る（Undo可能）", len(ops_g) == 2)
check("消えたファイルは理由がログに出る",
      any("c.dwg" in l and "見つかりません" in l for l in logs5))
shutil.rmtree(base5)

print("[16] フォルダの個別仕分けで1件失敗しても残りと履歴は失われない")
import core.organizer as org
base6 = tempfile.mkdtemp(prefix="v2h_")
ensure_structure(base6)
d6 = os.path.join(tempfile.mkdtemp(prefix="desk6_"), "展開失敗")
for n in ("a.dwg", "b.dwg", "c.dwg"):
    put(d6, n)
_orig_move = org.move_file
def _flaky_move(src, dst, progress_cb=None):
    if os.path.basename(src) == "b.dwg":
        raise OSError("テスト用の移動失敗")
    return _orig_move(src, dst, progress_cb)
org.move_file = _flaky_move
logs6 = []
try:
    ops_h = ingest_drop(base6, [d6], log_cb=logs6.append,
                        resolver=lambda k, n, c: "expand" if k == "folder" else None)
finally:
    org.move_file = _orig_move
check("失敗した1件以外は仕分けされる",
      os.path.exists(os.path.join(base6, rules.WORK_DIR, "a.dwg"))
      and os.path.exists(os.path.join(base6, rules.WORK_DIR, "c.dwg")))
check("移動済みの2件は操作リストに残る", len(ops_h) == 2)
check("失敗した1件は元の場所に残り理由がログに出る",
      os.path.exists(os.path.join(d6, "b.dwg"))
      and any("b.dwg" in l and "テスト用の移動失敗" in l for l in logs6))
shutil.rmtree(base6); shutil.rmtree(os.path.dirname(d6))

print("[17] 仕分けワーカー: 途中で例外が出ても完了通知を出す")
from PySide6.QtCore import QCoreApplication
from core.worker import SortWorker
qapp = QCoreApplication.instance() or QCoreApplication([])
not_dir = put(tempfile.mkdtemp(prefix="v2x_"), "フォルダではない")
got, wlogs = [], []
wk = SortWorker(not_dir)  # 現場フォルダが壊れている想定（ensure_structureで失敗）
wk.finished_batch.connect(got.append)
wk.log.connect(wlogs.append)
wk.run()  # スレッドを起こさず同期実行
check("finished_batch が必ず出る", got == [[]])
check("エラー内容がログに出る", any(l.startswith("[エラー]") for l in wlogs))
shutil.rmtree(os.path.dirname(not_dir))

print("[18] ドロップの書き込み中チェック（GUIで待たない経路: drop_snapshot）")
from core.organizer import drop_snapshot
base7 = tempfile.mkdtemp(prefix="v2w_")
desk7 = tempfile.mkdtemp(prefix="desk7_")
f_ok = put(desk7, "静止.dwg")
f_wr = put(desk7, "書込中.dwg")
snap7 = drop_snapshot([f_ok, f_wr, desk7])
check("スナップショットは通常ファイルのみ", set(snap7) == {f_ok, f_wr})
with open(f_wr, "ab") as fh:  # 待機中にサイズが変わった＝コピー途中
    fh.write(b"more")
sk7 = []
t0 = time.time()
ops7 = ingest_drop(base7, [f_ok, f_wr], skipped=sk7, snapshot=snap7)
check("snapshot指定時はingest_dropが待機しない", time.time() - t0 < 0.4)
check("変化なしのファイルは仕分けされる",
      os.path.exists(os.path.join(base7, rules.WORK_DIR, "静止.dwg")) and len(ops7) == 1)
check("変化したファイルは書き込み中としてスキップ",
      os.path.exists(f_wr) and [s["reason"] for s in sk7] == ["書き込み中"])
shutil.rmtree(base7); shutil.rmtree(desk7)

print("[19] しばらく変化のないファイルは待たずに仕分け（エクスプローラからすぐ消える）")
base8 = tempfile.mkdtemp(prefix="v2q_")
desk8 = tempfile.mkdtemp(prefix="desk8_")
f_old = put(desk8, "既存.dwg")
_orig_quiet = org.QUIET_SECONDS
org.QUIET_SECONDS = 0.2  # 作成日時は戻せないので、閾値を縮めて「古いファイル」を作る
try:
    time.sleep(0.3)
    check("変化のないファイルはスナップショット対象外", drop_snapshot([f_old]) == {})
    f_new = put(desk8, "作成直後.dwg")
    check("作成直後のファイルはスナップショット対象", set(drop_snapshot([f_new])) == {f_new})
    t0 = time.time()
    ops8 = ingest_drop(base8, [f_old])
    check("変化のないファイルだけなら待機しない", time.time() - t0 < 0.4)
    check("待機なしでも仕分けされる",
          os.path.exists(os.path.join(base8, rules.WORK_DIR, "既存.dwg")) and len(ops8) == 1)
finally:
    org.QUIET_SECONDS = _orig_quiet
shutil.rmtree(base8); shutil.rmtree(desk8)

print("[20] ドロップ結果の集計（移動先フォルダごと）")
from core.organizer import summarize_ops
base9 = tempfile.mkdtemp(prefix="v2s_")
desk9 = tempfile.mkdtemp(prefix="desk9_")
fs9 = [put(desk9, n) for n in ("a.dwg", "b.dwg", "c.sim", "d.dwg")]
ops9 = ingest_drop(base9, fs9)
sm9 = summarize_ops(base9, ops9)
check("件数の多い順に集計", sm9 == [(rules.WORK_DIR, 3), ("20_測量データ", 1)])
g9 = put(desk9, "提出図.dwg")
check("提出の同時コピーは10と11の両方に数える",
      dict(summarize_ops(base9, ingest_drop(base9, [g9], toggle="submit")))
      == {rules.WORK_DIR: 1, rules.SUBMIT_DIR: 1})
check("操作なしは空", summarize_ops(base9, []) == [])

print("[21] ドロップ単位の元に戻す（後から別の処理があっても対象バッチだけ戻す）")
h9 = History(os.path.join(base9, "h9.json"))
h9.record(ops9)
other = put(desk9, "別処理.dwg")
ops_other = ingest_drop(base9, [other])
h9.record(ops_other)
n9 = h9.undo_batch(ops9[0]["batch"])
check("対象バッチの4件が元の場所へ戻る",
      n9 == 4 and all(os.path.exists(f) for f in fs9))
check("後から行った別の処理は残る",
      os.path.exists(os.path.join(base9, rules.WORK_DIR, "別処理.dwg"))
      and len(h9.recent()) == len(ops_other))
check("Undo済みのバッチは0件", h9.undo_batch(ops9[0]["batch"]) == 0)
check("連続ドロップでもバッチIDは別", ops9[0]["batch"] != ops_other[0]["batch"])
shutil.rmtree(base9); shutil.rmtree(desk9)

print("[22] zipの移動先候補（最近使った先を上に）")
z0 = rules.zip_destinations()
check("履歴なしは90_その他が先頭（従来の初期値）", z0[0] == rules.OTHERS and z0[1] == rules.RECEIVE_DIR)
z1 = rules.zip_destinations(["20_測量データ", rules.OTHERS])
check("最近使った先が先頭に来る", z1[:3] == ["20_測量データ", rules.OTHERS, rules.RECEIVE_DIR])
check("候補の集合は変わらない（重複なし）", sorted(z1) == sorted(z0) and len(set(z1)) == len(z1))
check("ルールから消えたフォルダは無視", rules.zip_destinations(["存在しない"]) == z0)

print("[23] フォルダを丸ごと90_その他へ")
base10 = tempfile.mkdtemp(prefix="v2o_")
dO = os.path.join(tempfile.mkdtemp(prefix="desk10_"), "雑多な資料")
put(dO, "a.dwg"); put(os.path.join(dO, "sub"), "b.txt")
opsO = ingest_drop(base10, [dO], resolver=lambda k, n, c: "others" if k == "folder" else None)
moved = os.path.join(base10, rules.OTHERS, "雑多な資料")
check("フォルダが中身ごと90_その他へ（解体しない）",
      os.path.exists(os.path.join(moved, "a.dwg"))
      and os.path.exists(os.path.join(moved, "sub", "b.txt")) and not os.path.exists(dO))
check("1操作として記録・集計は90_その他",
      len(opsO) == 1 and summarize_ops(base10, opsO) == [(rules.OTHERS, 1)])
hO = History(os.path.join(base10, "hO.json")); hO.record(opsO)
check("元に戻すと元の場所へ戻る",
      hO.undo_batch(opsO[0]["batch"]) == 1 and os.path.exists(os.path.join(dO, "sub", "b.txt")))
shutil.rmtree(base10); shutil.rmtree(os.path.dirname(dO))

import errno
import stat
import config
import core.organizer as org
from core.organizer import is_protected, move_file, move_tree
from core.versions import find_old_candidates

class _CrossDevice:
    """os.rename を失敗させ、別ドライブ間の移動（コピー＋元削除）を再現する"""
    def __enter__(self):
        self.real = os.rename
        def fail(a, b):
            raise OSError(errno.EXDEV, "別ドライブ（テスト）")
        os.rename = fail
    def __exit__(self, *a):
        os.rename = self.real

print("[24] 読み取り専用ファイルを「使用中」と誤判定しない")
d24 = tempfile.mkdtemp(prefix="ro_")
ro = put(d24, "受領図.dwg")
os.chmod(ro, stat.S_IREAD)
real_open = open
def _ro_open(path, mode="r", *a, **k):  # 読み取り専用ファイルは書き込みで開けない（Windowsの挙動）
    if path == ro and "+" in mode:
        raise PermissionError(13, "読み取り専用")
    return real_open(path, mode, *a, **k)
org.open = _ro_open
try:
    check("読み取り専用は使用中ではない", not org.is_locked(ro))
finally:
    del org.open
base24 = tempfile.mkdtemp(prefix="v2ro_")
with _CrossDevice():
    ops24 = ingest_drop(base24, [ro])
check("読み取り専用ファイルも別ドライブから移動できる",
      len(ops24) == 1 and not os.path.exists(ro)
      and os.path.exists(os.path.join(base24, rules.WORK_DIR, "受領図.dwg")))
src24 = put(d24, "提出図.dwg"); os.chmod(src24, stat.S_IREAD)
ops24b = ingest_drop(base24, [src24], toggle="submit")
h24 = History(os.path.join(base24, "h.json")); h24.record(ops24b)
check("読み取り専用のコピーも元に戻す（削除）できる",
      h24.undo_last() == 1 and not os.path.exists(ops24b[0]["dst"])
      and not os.path.exists(ops24b[0]["dst2"]))

print("[25] 別ドライブ移動で元を消せないとき、移動先にコピーを残さない")
base25 = tempfile.mkdtemp(prefix="v2rm_")
src25 = put(tempfile.mkdtemp(), "使用中.dwg")
real_remove = os.remove
def _no_remove(path):
    if path == src25:
        raise PermissionError(13, "使用中（テスト）")
    return real_remove(path)
os.remove = _no_remove
try:
    with _CrossDevice():
        logs25 = []
        ops25 = ingest_drop(base25, [src25], log_cb=logs25.append)
finally:
    os.remove = real_remove
check("元は残り、移動先には無く、記録もしない",
      os.path.exists(src25) and not ops25
      and not os.path.exists(os.path.join(base25, rules.WORK_DIR, "使用中.dwg")))
check("失敗理由がログに出る", any("使用中.dwg" in l for l in logs25))

print("[26] 現場フォルダ・構成フォルダはドロップしても移動しない")
base26 = tempfile.mkdtemp(prefix="v2pr_")
ensure_structure(base26)
put(os.path.join(base26, rules.WORK_DIR), "a.dwg")
logs26 = []
ops26 = ingest_drop(base26, [os.path.join(base26, rules.WORK_DIR)],
                    resolver=lambda k, n, c: "others", log_cb=logs26.append)
check("10_図面_作業用 を丸ごと90へ → 移動しない",
      not ops26 and os.path.exists(os.path.join(base26, rules.WORK_DIR, "a.dwg")))
ops26b = ingest_drop(base26, [base26], resolver=lambda k, n, c: "expand")
check("現場フォルダそのものを個別仕分け → 何も動かさない",
      not ops26b and os.listdir(os.path.join(base26, rules.INBOX)) == [])
check("現場の親フォルダ・入れ子の構成フォルダも保護",
      is_protected(base26, os.path.dirname(base26))
      and is_protected(base26, os.path.join(base26, "21_3Dスキャン"))
      and is_protected(base26, os.path.join(base26, "21_3Dスキャン", "03_エクスポート点群")))
inbox_file = put(os.path.join(base26, rules.INBOX), "座標.sim")
check("Inbox内のファイル・フォルダは通常どおり扱える",
      not is_protected(base26, inbox_file)
      and len(ingest_drop(base26, [inbox_file])) == 1)
check("Inbox仮置き（メイン画面）でも構成フォルダは移動しない",
      org.send_to_inbox(base26, [os.path.join(base26, rules.OTHERS)]) == []
      and os.path.isdir(os.path.join(base26, rules.OTHERS)))

print("[27] 別ドライブのフォルダ移動とその「元に戻す」")
base27 = tempfile.mkdtemp(prefix="v2xd_")
d27 = os.path.join(tempfile.mkdtemp(), "受領一式")
put(d27, "a.dwg"); put(os.path.join(d27, "sub"), "b.txt")
with _CrossDevice():
    ops27 = ingest_drop(base27, [d27], resolver=lambda k, n, c: "keep")
    moved27 = os.path.join(base27, rules.INBOX, "受領一式")
    check("フォルダごとコピーされ、元は消える",
          len(ops27) == 1 and not os.path.exists(d27)
          and os.path.exists(os.path.join(moved27, "sub", "b.txt")))
    h27 = History(os.path.join(base27, "h.json")); h27.record(ops27)
    check("元に戻すと元の場所へ戻る（別ドライブでも）",
          h27.undo_last() == 1 and os.path.exists(os.path.join(d27, "sub", "b.txt"))
          and not os.path.exists(moved27))
d27b = os.path.join(tempfile.mkdtemp(), "途中失敗")
put(d27b, "a.dwg")
real_copytree = shutil.copytree
def _half_copytree(src, dst, **kw):
    os.makedirs(dst); open(os.path.join(dst, "途中.tmp"), "w").close()
    raise OSError(28, "空き容量不足（テスト）")
shutil.copytree = _half_copytree
try:
    with _CrossDevice():
        move_tree(d27b, os.path.join(base27, "dst"))
except OSError:
    pass
finally:
    shutil.copytree = real_copytree
check("フォルダのコピーに失敗したら途中のコピーを消し、元はそのまま",
      not os.path.exists(os.path.join(base27, "dst")) and os.path.exists(os.path.join(d27b, "a.dwg")))
real_rename27 = os.rename
def _in_use(a, b):
    raise PermissionError(13, "中のファイルが使用中（テスト）")
os.rename = _in_use
try:
    move_tree(d27b, os.path.join(base27, "dst2"))
    raised27 = False
except OSError:
    raised27 = True
finally:
    os.rename = real_rename27
check("同じドライブで移動できないときはコピーに切り替えない（中途半端に消さない）",
      raised27 and not os.path.exists(os.path.join(base27, "dst2"))
      and os.path.exists(os.path.join(d27b, "a.dwg")))

print("[28] 使用中で元に戻せなかった操作は履歴に残し、後で再試行できる")
base28 = tempfile.mkdtemp(prefix="v2uf_")
f28 = put(tempfile.mkdtemp(), "開いている.dwg")
ops28 = ingest_drop(base28, [f28])
h28 = History(os.path.join(base28, "h.json")); h28.record(ops28)
real_move = org.move_file
def _busy(*a, **k):
    raise PermissionError(13, "使用中（テスト）")
org.move_file = _busy
try:
    logs28 = []
    n28 = h28.undo_last(log_cb=logs28.append)
finally:
    org.move_file = real_move
check("1回目は失敗し、履歴に残る", n28 == 0 and len(h28.recent()) == 1
      and any("Undo失敗" in l for l in logs28))
check("閉じた後の再試行で戻せる", h28.undo_last() == 1 and os.path.exists(f28)
      and h28.recent() == [])
h28.record([{"op": "move", "src": f28 + ".x", "dst": f28 + ".消えた", "batch": "b"}])
check("移動先が消えている操作は履歴から外す（再試行しても戻せない）",
      h28.undo_last() == 0 and h28.recent() == [])
f28b = put(tempfile.mkdtemp(), "USBから.dwg")
ops28b = ingest_drop(base28, [f28b])
h28.record(ops28b)
usb28 = os.path.dirname(f28b)
shutil.rmtree(usb28)  # 元のドライブが外れている状態
real_makedirs = os.makedirs
def _no_drive(path, *a, **k):
    if path.startswith(usb28):
        raise FileNotFoundError(2, "ドライブが見つかりません（テスト）")
    return real_makedirs(path, *a, **k)
os.makedirs = _no_drive
try:
    n28b = h28.undo_last()
finally:
    os.makedirs = real_makedirs
check("元のドライブが未接続で戻せないときは履歴に残す（つないでから再試行できる）",
      n28b == 0 and len(h28.recent()) == 1)
check("ドライブをつないだ後の再試行で戻せる", h28.undo_last() == 1 and os.path.exists(f28b))

print("[29] 既に移動先にあるファイルは名前を変えない")
base29 = tempfile.mkdtemp(prefix="v2sp_")
ensure_structure(base29)
z29 = put(os.path.join(base29, rules.INBOX), "納品.zip")
ops29 = ingest_drop(base29, [z29], resolver=lambda k, n, c: None)
check("Inboxのzipを移動先未確定のまま → そのまま・記録なし",
      os.listdir(os.path.join(base29, rules.INBOX)) == ["納品.zip"] and not ops29)
w29 = put(os.path.join(base29, rules.WORK_DIR), "断面.dxf")
ops29b = ingest_drop(base29, [w29])
check("仕分け済みファイルを再ドロップ → そのまま・記録なし",
      os.listdir(os.path.join(base29, rules.WORK_DIR)) == ["断面.dxf"] and not ops29b)
check("move_file は同じ場所なら何もしない", move_file(w29, w29) == w29 and os.path.exists(w29))

print("[30] ルールのフォルダ名は現場フォルダ内に限る")
check("使えるフォルダ名", all(rules.valid_folder_name(n) for n in
      ("10_図面", "21_3Dスキャン/03_エクスポート点群", "21_3Dスキャン\\02_プロジェクト")))
check("使えないフォルダ名", not any(rules.valid_folder_name(n) for n in
      ("", " ", "/etc", "\\\\server\\share", "C:\\Windows", "C:x", "..", "a/../..",
       "a//b", "a/./b", "名前?", "x|y")))
saved30 = json.loads(json.dumps({"folders": {k: sorted(v) for k, v in rules.FOLDERS.items()},
                                  "keywords": rules.KEYWORDS}))
outside30 = os.path.join(tempfile.mkdtemp(), "現場の外")
rules._apply({"folders": {outside30: [".abc"], "../外": [".def"], "40_報告書・書類": [".xlsx"]},
              "keywords": {"40_報告書・書類": "報告書"}})
check("不正なフォルダ名のルールは読み込まない", list(rules.FOLDERS) == ["40_報告書・書類"])
check("キーワードが文字列1つでも1語として扱う（1文字ずつにしない）",
      rules.KEYWORDS["40_報告書・書類"] == ["報告書"])
base30 = tempfile.mkdtemp(prefix="v2rn_")
rules.FOLDERS[outside30] = {".abc"}  # 万一読み込まれても
ensure_structure(base30)
check("現場の外にフォルダを作らない", not os.path.exists(outside30))
rules._apply(saved30)

print("[31] 設定ファイルの破損・不正形式で起動が止まらない")
open(config.SETTINGS_PATH, "w").write("[1, 2]")
import warnings as _w
with _w.catch_warnings(record=True) as cw:
    _w.simplefilter("always")
    st31 = config.load_settings()
check("配列形式 → 既定値で起動し警告を出す", st31["theme"] == "earth" and cw)
check("壊れたファイルは .broken に退避", os.path.exists(config.SETTINGS_PATH + ".broken"))
config.save_settings({"theme": "night"})
check("保存は一時ファイル経由（.tmp が残らない）",
      json.load(open(config.SETTINGS_PATH, encoding="utf-8")) == {"theme": "night"}
      and not os.path.exists(config.SETTINGS_PATH + ".tmp"))
os.remove(config.SETTINGS_PATH); os.remove(config.SETTINGS_PATH + ".broken")

print("[32] 提出の同時コピーで2箇所目に失敗 → 1箇所目のコピーも残さない")
base32 = tempfile.mkdtemp(prefix="v2cd_")
s32 = put(tempfile.mkdtemp(), "提出図.dwg")
real_copy = org.copy_file
calls32 = []
def _second_fails(a, b, cb=None):
    calls32.append(b)
    if len(calls32) == 2:
        raise OSError(28, "空き容量不足（テスト）")
    return real_copy(a, b, cb)
org.copy_file = _second_fails
try:
    ops32 = ingest_drop(base32, [s32], toggle="submit")
finally:
    org.copy_file = real_copy
check("記録なし・10にコピーが残らない・元は残る",
      not ops32 and os.listdir(os.path.join(base32, rules.WORK_DIR)) == [] and os.path.exists(s32))

print("[33] フォルダの個別仕分けでも使用中・一時ファイル・リンクは動かさない")
base33 = tempfile.mkdtemp(prefix="v2ex_")
d33 = os.path.join(tempfile.mkdtemp(), "作業中フォルダ")
put(d33, "編集中.dwg"); put(d33, "編集中.dwl"); put(d33, "~$見積.xlsx"); put(d33, "座標.sim")
if hasattr(os, "symlink"):
    try:
        os.symlink(os.path.join(d33, "座標.sim"), os.path.join(d33, "リンク.sim"))
    except OSError:
        pass
sk33 = []
ops33 = ingest_drop(base33, [d33], resolver=lambda k, n, c: "expand", skipped=sk33)
left33 = sorted(os.listdir(d33))
check("使用中(.dwl有り)・ロック・一時ファイルは元フォルダに残る",
      {"編集中.dwg", "編集中.dwl", "~$見積.xlsx"} <= set(left33))
check("使用中は再試行リストへ", [os.path.basename(x["path"]) for x in sk33] == ["編集中.dwg"])
check("通常のファイルは仕分けられる",
      os.path.exists(os.path.join(base33, "20_測量データ", "座標.sim"))
      and [os.path.basename(o["src"]) for o in ops33] == ["座標.sim"])

print("[34] Inbox仮置き（メイン画面）も元に戻せる")
base34 = tempfile.mkdtemp(prefix="v2ib_")
f34 = put(tempfile.mkdtemp(), "仮置き.pdf")
ops34 = org.send_to_inbox(base34, [f34])
h34 = History(os.path.join(base34, "h.json")); h34.record(ops34)
check("仮置きの操作を返し、元に戻せる",
      len(ops34) == 1 and h34.undo_last() == 1 and os.path.exists(f34))

print("[35] 旧版検知は写真・3Dスキャンを対象にしない")
base35 = tempfile.mkdtemp(prefix="v2ov_")
ensure_structure(base35)
put(os.path.join(base35, "30_現場写真", "2026-06-01"), "現場 (1).jpg")
put(os.path.join(base35, "30_現場写真", "2026-06-01"), "現場 (2).jpg")
put(os.path.join(base35, "21_3Dスキャン", "01_RAWデータ_FLS"), "Scan_20260601.fls")
put(os.path.join(base35, "21_3Dスキャン", "01_RAWデータ_FLS"), "Scan_20260602.fls")
put(os.path.join(base35, rules.WORK_DIR), "縦断図_v1.dwg")
put(os.path.join(base35, rules.WORK_DIR), "縦断図_v2.dwg")
c35 = [c["rel"] for c in find_old_candidates(base35)]
check("図面の旧版だけが候補", len(c35) == 1 and c35[0].startswith(rules.WORK_DIR))

print("[36] 新規現場: 不正な名前・現場外への雛形配置を防ぐ")
parent36 = tempfile.mkdtemp(prefix="v2ns_")
bad36 = []
for nm in ("..", "a/b", "a\\b", "現場:1", "  "):
    try:
        org.create_site(parent36, nm)
    except ValueError:
        bad36.append(nm)
check("使えない現場名は作らない", len(bad36) == 5 and os.listdir(parent36) == [])
tpl36 = put(tempfile.mkdtemp(), "雛形.xlsx")
outside36 = os.path.join(tempfile.mkdtemp(), "外")
logs36 = []
b36 = org.create_site(parent36, "現場A", [{"src": tpl36, "dst": outside36},
                                         {"src": tpl36, "dst": "40_報告書・書類"}],
                      log_cb=logs36.append)
check("雛形は現場内だけに置き、現場外の指定はスキップ",
      not os.path.exists(outside36)
      and os.path.exists(os.path.join(b36, "40_報告書・書類", "雛形.xlsx"))
      and any("雛形スキップ" in l for l in logs36))

shutil.rmtree(base); shutil.rmtree(desk)
shutil.rmtree(DATA_TMP, ignore_errors=True)
print(f"\n結果: OK={ok} NG={ng}")
sys.exit(1 if ng else 0)
