# -*- coding: utf-8 -*-
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules
from core.organizer import ensure_structure, ingest_drop, organize

ok = ng = 0
def check(name, cond):
    global ok, ng
    print(("  OK " if cond else "  NG ") + name); ok += bool(cond); ng += not cond

print("[E1] skipped収集（organize/ingest_drop）")
base = tempfile.mkdtemp(prefix="e_")
ensure_structure(base)
ib = os.path.join(base, rules.INBOX)
open(os.path.join(ib, "編集中.dwg"), "wb").write(b"x")
open(os.path.join(ib, "編集中.dwl"), "wb").write(b"x")
open(os.path.join(ib, "通常.dwg"), "wb").write(b"x")
sk = []
ops = organize(base, skipped=sk)
check("ロック分がskippedに入る", len(sk) == 1 and "編集中.dwg" in sk[0]["path"]
      and sk[0]["reason"] == "ロック中")
check("通常分は処理される", len(ops) == 1)
desk = tempfile.mkdtemp(prefix="ed_")
f = os.path.join(desk, "図面.dwg"); open(f, "wb").write(b"x")
open(os.path.join(desk, "図面.dwl"), "wb").write(b"x")
sk2 = []
ingest_drop(base, [f], toggle="submit", skipped=sk2)
check("ドロップ経路もtoggle付きで収集", len(sk2) == 1 and sk2[0]["toggle"] == "submit")
print("[E2] ロック解除後の再試行で処理される")
os.remove(os.path.join(desk, "図面.dwl"))
sk3 = []
ops3 = ingest_drop(base, [f], toggle="submit", skipped=sk3)
check("再試行成功（提出コピー）", not sk3 and len(ops3) == 1
      and ops3[0]["op"] == "copy_dual")
print("[E3] resource_path")
import config
p = config.resource_path("assets/app.ico")
check("通常時はAPP_DIR基準", p.startswith(config.APP_DIR))
shutil.rmtree(base); shutil.rmtree(desk)
print(f"\n結果: OK={ok} NG={ng}")
sys.exit(1 if ng else 0)
