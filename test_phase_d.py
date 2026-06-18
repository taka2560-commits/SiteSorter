# -*- coding: utf-8 -*-
"""Phase D テスト: 容量計算・旧版検知・新規現場テンプレ・アーカイブUndo"""
import os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules
from core.capacity import calc
from core.versions import base_key, find_old_candidates
from core.organizer import archive_files, create_site, ensure_structure
from core.history import History

ok = ng = 0
def check(name, cond):
    global ok, ng
    print(("  OK " if cond else "  NG ") + name)
    ok += bool(cond); ng += not cond

print("[D1] base_key（サフィックス除去）")
check("_v2", base_key("平面図_v2") == "平面図")
check("(3)", base_key("平面図(3)") == "平面図")
check("_20260601", base_key("平面図_20260601") == "平面図")
check("2026-06-01", base_key("平面図_2026-06-01") == "平面図")
check("rev3", base_key("平面図_rev3") == "平面図")
check("複合 _v2(2)", base_key("平面図_v2(2)") == "平面図")
check("サフィックスなしは不変", base_key("平面図") == "平面図")
check("数値のみ名は保護", base_key("20260601") == "20260601")

print("[D2] 容量計算（21_3Dスキャン別集計）")
base = tempfile.mkdtemp(prefix="d_")
ensure_structure(base)
open(os.path.join(base, rules.WORK_DIR, "a.dwg"), "wb").write(b"x" * 1000)
open(os.path.join(base, "21_3Dスキャン", "03_エクスポート点群", "p.las"), "wb").write(b"x" * 5000)
res = calc(base)
check("総容量", res["total"] == 6000)
check("3Dスキャン配下", res["scan3d"] == 5000)

print("[D3] 旧版検知（最新以外・除外フォルダ）")
w = os.path.join(base, rules.WORK_DIR)
open(os.path.join(w, "縦断図.dwg"), "wb").write(b"1")
time.sleep(0.05)
open(os.path.join(w, "縦断図_v2.dwg"), "wb").write(b"2")
time.sleep(0.05)
open(os.path.join(w, "縦断図_v3.dwg"), "wb").write(b"3")
# 除外: 11と12に同パターンを置いても検知されない
os.makedirs(os.path.join(base, rules.SUBMIT_DIR), exist_ok=True)
open(os.path.join(base, rules.SUBMIT_DIR, "縦断図.dwg"), "wb").write(b"x")
open(os.path.join(base, rules.SUBMIT_DIR, "縦断図_v2.dwg"), "wb").write(b"x")
cands = find_old_candidates(base)
rels = {c["rel"] for c in cands}
check("v1とv2が候補・v3は残す", any("縦断図.dwg" in r for r in rels)
      and any("縦断図_v2" in r for r in rels)
      and not any("縦断図_v3" in r for r in rels))
check("候補は2件のみ（聖域は対象外）", len(cands) == 2)
check("keepは最新を指す", all("縦断図_v3" in c["keep"] for c in cands))

print("[D4] 承認制アーカイブ＋Undo")
hist = History(os.path.join(base, "h.json"))
ops = archive_files(base, [c["path"] for c in cands])
check("99へ移動", os.path.exists(os.path.join(base, rules.ARCHIVE, "縦断図.dwg"))
      and os.path.exists(os.path.join(base, rules.ARCHIVE, "縦断図_v2.dwg")))
hist.record(ops)
n = hist.undo_last()
check("Undoで復元", n == 2 and os.path.exists(os.path.join(w, "縦断図.dwg")))

print("[D5] 新規現場テンプレ作成")
tdir = tempfile.mkdtemp(prefix="tpl_")
tpl = os.path.join(tdir, "報告書雛形.xlsx")
open(tpl, "wb").write(b"excel")
parent = tempfile.mkdtemp(prefix="parent_")
logs = []
nb = create_site(parent, "2026_テスト現場",
                 [{"src": tpl, "dst": "40_報告書・書類"},
                  {"src": "/存在しない.lsp", "dst": ""}], log_cb=logs.append)
check("フォルダ構造生成", os.path.isdir(os.path.join(nb, rules.INBOX))
      and os.path.isdir(os.path.join(nb, "21_3Dスキャン", "03_エクスポート点群"))
      and os.path.isdir(os.path.join(nb, rules.ARCHIVE)))
check("雛形配置", os.path.exists(os.path.join(nb, "40_報告書・書類", "報告書雛形.xlsx")))
check("欠損雛形はスキップ通知", any("雛形スキップ" in l for l in logs))
try:
    create_site(parent, "2026_テスト現場", [])
    check("重複はエラー", False)
except ValueError:
    check("重複はエラー", True)

shutil.rmtree(base); shutil.rmtree(tdir); shutil.rmtree(parent)
print(f"\n結果: OK={ok} NG={ng}")
sys.exit(1 if ng else 0)
