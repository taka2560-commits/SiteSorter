# -*- coding: utf-8 -*-
"""画面まわりのテスト（起動・ドロップゾーン・二重起動・エラー記録）"""
import os
import shutil
import sys
import tempfile
import time

# 設定の保存先を一時フォルダへ切り替えてから本体を読み込む（test_core.py と同じ理由）
DATA_TMP = tempfile.mkdtemp(prefix="sitesorter_ui_")
os.environ["APPDATA"] = DATA_TMP  # Windows
os.environ["HOME"] = DATA_TMP     # Linux（~/.config）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtCore import QLockFile, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

import config
import rules
if not config.DATA_DIR.startswith(DATA_TMP):
    sys.exit("中止: 設定の保存先が一時フォルダではありません: " + config.DATA_DIR)

app = QApplication.instance() or QApplication([])
import main as app_main
from ui.drop_zone import DropZone
from ui.main_window import MainWindow

ok = ng = 0
def check(name, cond):
    global ok, ng
    print(("  OK " if cond else "  NG ") + name)
    ok += bool(cond); ng += not cond

def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents()
        time.sleep(0.01)

def drop(zone, paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    zone.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))

def put(d, name):
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, name); open(fp, "wb").write(b"x"); return fp

print("[1] 書き込めない現場フォルダが設定されていても起動できる")
bad = tempfile.mkdtemp(prefix="ui_bad_")
open(os.path.join(bad, rules.INBOX), "w").close()  # 00_Inbox がファイル → 構成フォルダを作れない
try:
    mw_bad = MainWindow({"site_folder": bad})
    started = True
except Exception as e:
    started = False
    print("   ", type(e).__name__, e)
check("起動時に例外で落ちない", started)
check("原因がログに出る", started and "構成フォルダを作れません" in mw_bad.log_view.toPlainText())

print("[2] ドロップ処理でエラーが出ても「処理中…」のまま止まらない")
good = tempfile.mkdtemp(prefix="ui_good_")
mw = MainWindow({"site_folder": good})
zone = DropZone({"site_folder": bad}, mw)
drop(zone, [put(tempfile.mkdtemp(), "a.dwg")])
wait(1000)  # 作成直後のファイルは書き込み中チェック（0.5秒）の後に処理される
check("エラー表示に変わる", "処理できません" in zone.label.text())
check("ログに理由が出る", "ドロップを処理できませんでした" in mw.log_view.toPlainText())

print("[3] 見つからない現場フォルダには仕分けない（フォルダを作り直さない）")
gone = os.path.join(tempfile.mkdtemp(), "名前を変えた現場")
zone3 = DropZone({"site_folder": gone}, mw)
f3 = put(tempfile.mkdtemp(), "b.dwg")
drop(zone3, [f3])
wait(200)
check("「見つかりません」と表示", "見つかりません" in zone3.label.text())
check("ファイルは動かさず、現場フォルダも作らない", os.path.exists(f3) and not os.path.exists(gone))

print("[4] Inbox 一覧が読めなくても落ちない")
real_listdir = os.listdir
def _denied(path):
    if path.endswith(rules.INBOX):
        raise PermissionError(13, "アクセス拒否（テスト）")
    return real_listdir(path)
os.listdir = _denied
try:
    mw.refresh_inbox()
    survived = True
except Exception:
    survived = False
finally:
    os.listdir = real_listdir
check("一覧更新で例外にならず、理由を表示", survived and "読み込めません" in mw.inbox_label.text())

print("[5] メイン画面の Inbox 仮置きも履歴に残り、元に戻せる")
f5 = put(tempfile.mkdtemp(), "仮置き.pdf")
before = len(mw.history.recent())
mw._stock_to_inbox([f5])
check("履歴に記録される", len(mw.history.recent()) == before + 1)
mw._undo()
check("元に戻すと元の場所へ", os.path.exists(f5))

print("[6] 二重起動しない")
lock = QLockFile(os.path.join(config.DATA_DIR, "SiteSorter.lock"))
check("1つ目がロックを取得", lock.tryLock(100))
shown = []
real_info = QMessageBox.information
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a))
try:
    code = app_main.main()
finally:
    QMessageBox.information = real_info
    lock.unlock()
check("2つ目は案内を出して終了する", code == 0 and shown and "既に起動" in shown[0][2])

print("[7] 想定外のエラーを error.log とログ画面に残す")
app_main.install_excepthook(lambda: mw)
try:
    raise RuntimeError("テスト用のエラー")
except RuntimeError:
    sys.excepthook(*sys.exc_info())
sys.excepthook = sys.__excepthook__
log_text = open(app_main.ERROR_LOG, encoding="utf-8").read()
check("error.log に詳細", "テスト用のエラー" in log_text and "Traceback" in log_text)
check("ログ画面に案内", "想定外のエラー" in mw.log_view.toPlainText())

shutil.rmtree(DATA_TMP, ignore_errors=True)
print(f"\n結果: OK={ok} NG={ng}")
sys.exit(1 if ng else 0)
