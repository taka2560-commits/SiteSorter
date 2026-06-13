# -*- coding: utf-8 -*-
"""仕分けエンジン v2（UI非依存）

優先順位: ①トグル（提出/受領） ②キーワード辞書 ③拡張子 ④90_その他
multi/zip など要確認の判定は resolver コールバックで解決（無ければスキップ/Inbox残し）
"""
import os
import shutil
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rules

CHUNK_SIZE = 4 * 1024 * 1024
# 仕分け対象外（ロック・一時・同期ソフトの部分書き込みファイル）
TRANSIENT_EXTS = {".dwl", ".dwl2", ".part", ".tmp", ".crdownload", ".bak~"}


def is_transient(name: str) -> bool:
    return (os.path.splitext(name)[1].lower() in TRANSIENT_EXTS
            or name.startswith("~$") or name == "desktop.ini")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_structure(base: str) -> None:
    for d in rules.all_dirs():
        os.makedirs(os.path.join(base, d), exist_ok=True)


def scan_inbox(base: str) -> list:
    inbox = os.path.join(base, rules.INBOX)
    if not os.path.isdir(inbox):
        return []
    return sorted(
        os.path.join(inbox, f) for f in os.listdir(inbox)
        if os.path.isfile(os.path.join(inbox, f))
    )


def is_locked(path: str) -> bool:
    """ロックファイル(.dwl等)・排他制御の検知"""
    root, ext = os.path.splitext(path)
    if ext.lower() in (".dwg", ".dxf"):
        for lock in (".dwl", ".dwl2"):
            if os.path.exists(root + lock):
                return True
    try:
        with open(path, "r+b"):
            pass
    except OSError:
        return True
    return False


def get_photo_date(path: str) -> str:
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(36867) or exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw)[:10], "%Y:%m:%d").strftime("%Y-%m-%d")
    except Exception:
        pass
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def unique_path(dst: str) -> str:
    if not os.path.exists(dst):
        return dst
    root, ext = os.path.splitext(dst)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cand = f"{root}_{stamp}{ext}"
    n = 2
    while os.path.exists(cand):
        cand = f"{root}_{stamp}_{n}{ext}"
        n += 1
    return cand


def _chunk_copy(src: str, dst: str, progress_cb=None) -> None:
    """チャンクコピー（.part→検証→確定。中断時に不完全ファイルを残さない）"""
    total = os.path.getsize(src)
    tmp = dst + ".part"
    copied = 0
    try:
        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                chunk = fsrc.read(CHUNK_SIZE)
                if not chunk:
                    break
                fdst.write(chunk)
                copied += len(chunk)
                if progress_cb:
                    progress_cb(copied, total)
        if os.path.getsize(tmp) != total:
            raise IOError(f"コピー検証に失敗: {src}")
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def copy_file(src: str, dst: str, progress_cb=None) -> str:
    """コピー（元を残す）。同名衝突は自動リネーム。"""
    dst = unique_path(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    _chunk_copy(src, dst, progress_cb)
    return dst


def move_file(src: str, dst: str, progress_cb=None) -> str:
    """移動。同一ドライブはrename、異ドライブはチャンクコピー＋元削除。"""
    dst = unique_path(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    total = os.path.getsize(src)
    try:
        os.rename(src, dst)
        if progress_cb:
            progress_cb(total, total)
        return dst
    except OSError:
        pass
    _chunk_copy(src, dst, progress_cb)
    os.remove(src)
    return dst


def move_dir(src: str, dst_dir: str) -> str:
    """フォルダを丸ごと移動（衝突時はフォルダ名にタイムスタンプ付与）"""
    dst = unique_path(os.path.join(dst_dir, os.path.basename(src)))
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, dst)
    return dst


def _dest_for(base: str, src: str, folder: str, photo: str) -> str:
    """フォルダ判定結果から最終パスを組み立て（受領=日付/写真=撮影日）"""
    name = os.path.basename(src)
    if folder == rules.RECEIVE_DIR:
        return os.path.join(base, folder, f"{_today()}_受領", name)
    if photo and folder == photo:
        return os.path.join(base, folder, get_photo_date(src), name)
    return os.path.join(base, folder, name)


def _resolve(src: str, resolver, log_cb) -> str:
    """classify結果のmulti/zipをresolverで解決。未解決はNone（スキップ）。"""
    name = os.path.basename(src)
    c = rules.classify(name)
    if "folder" in c:
        return c["folder"]
    if "multi" in c:
        folder = resolver("multi", name, c["multi"]) if resolver else None
        if not folder and log_cb:
            log_cb(f"[要確認] {name}: 複数カテゴリ該当 → {' / '.join(c['multi'])}（スキップ）")
        return folder
    # zip（トグルなし）
    folder = resolver("zip", name, None) if resolver else None
    if not folder and log_cb:
        log_cb(f"[要確認] {name}: .zipの移動先が未確定（スキップ）")
    return folder


def preflight(base: str) -> list:
    """Inbox一括処理の事前スキャン。要確認項目 [(名前, 種別, 候補), ...] を返す。

    種別: "multi"（複数カテゴリ該当・候補リスト付き） / "zip"（移動先未確定）
    """
    pend = []
    for src in scan_inbox(base):
        name = os.path.basename(src)
        if is_transient(name):
            continue
        c = rules.classify(name)
        if "multi" in c:
            pend.append((name, "multi", c["multi"]))
        elif "zip" in c:
            pend.append((name, "zip", None))
    return pend


def organize(base: str, progress_cb=None, log_cb=None, resolver=None,
             skipped=None) -> list:
    """00_Inbox の一括仕分け。戻り値: 操作リスト（Undo用）"""
    ensure_structure(base)
    batch = _now()
    photo = rules.photo_dir()
    files = scan_inbox(base)
    total_bytes = sum(os.path.getsize(f) for f in files) or 1
    done = 0
    ops = []
    for src in files:
        name = os.path.basename(src)
        size = os.path.getsize(src)
        try:
            if is_transient(name):
                continue  # ロック・一時ファイルは触らない
            if is_locked(src):
                if log_cb:
                    log_cb(f"[スキップ] {name}: 使用中（ロック検知）")
                if skipped is not None:
                    skipped.append({"path": src, "toggle": None,
                                    "reason": "ロック中"})
                continue
            folder = _resolve(src, resolver, log_cb)
            if not folder:
                continue
            dst = _dest_for(base, src, folder, photo)

            def cb(c, _t, _b=done):
                if progress_cb:
                    progress_cb(_b + c, total_bytes, name)
            actual = move_file(src, dst, cb)
            ops.append({"op": "move", "src": src, "dst": actual,
                        "time": _now(), "batch": batch})
            if log_cb:
                log_cb(f"{name} → {os.path.relpath(actual, base)}")
        except (OSError, IOError) as e:
            if log_cb:
                log_cb(f"[スキップ] {name}: {e}")
        finally:
            done += size
            if progress_cb:
                progress_cb(done, total_bytes, name)
    return ops


def ingest_drop(base: str, paths: list, toggle=None,
                progress_cb=None, log_cb=None, resolver=None,
                skipped=None) -> list:
    """ドロップ経路の即時仕分け。

    toggle: None / "submit"（提出） / "receive"（受領）
    戻り値: 操作リスト（Undo用）
    """
    ensure_structure(base)
    batch = _now()
    photo = rules.photo_dir()
    ops = []
    for src in paths:
        name = os.path.basename(src)
        try:
            if os.path.isdir(src):
                ops += _ingest_dir(base, src, toggle, batch, resolver, log_cb, photo)
                continue
            if not os.path.isfile(src):
                continue
            if is_transient(name):
                if log_cb:
                    log_cb(f"[スキップ] {name}: 一時/ロックファイル")
                continue
            if is_locked(src):
                if log_cb:
                    log_cb(f"[スキップ] {name}: 使用中（ロック検知）")
                if skipped is not None:
                    skipped.append({"path": src, "toggle": toggle,
                                    "reason": "ロック中"})
                continue
            if toggle == "receive":
                dst = os.path.join(base, rules.RECEIVE_DIR, f"{_today()}_受領", name)
                actual = move_file(src, dst, progress_cb and (lambda c, t: progress_cb(c, t, name)))
                ops.append({"op": "move", "src": src, "dst": actual,
                            "time": _now(), "batch": batch})
                if log_cb:
                    log_cb(f"[受領] {name} → {os.path.relpath(actual, base)}")
            elif toggle == "submit":
                sub = os.path.join(base, rules.SUBMIT_DIR, f"{_today()}_提出", name)
                if name.lower().endswith(".zip"):
                    actual = copy_file(src, sub)
                    ops.append({"op": "copy", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb(f"[提出/zip] {name} → {os.path.relpath(actual, base)}")
                else:
                    work = os.path.join(base, rules.WORK_DIR, name)
                    a1 = copy_file(src, work)
                    a2 = copy_file(src, sub)
                    ops.append({"op": "copy_dual", "src": src, "dst": a1,
                                "dst2": a2, "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb(f"[提出] {name} → 10_図面_作業用 と "
                               f"{os.path.relpath(a2, base)} に同時コピー")
            else:
                folder = _resolve(src, resolver, None)
                if not folder:
                    # 未確定はInboxへ仮置き（消失防止）
                    dst = os.path.join(base, rules.INBOX, name)
                    actual = move_file(src, dst)
                    ops.append({"op": "move", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb(f"[要確認] {name}: 移動先未確定のためInboxへ仮置き")
                else:
                    dst = _dest_for(base, src, folder, photo)
                    actual = move_file(src, dst, progress_cb and (lambda c, t: progress_cb(c, t, name)))
                    ops.append({"op": "move", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb(f"{name} → {os.path.relpath(actual, base)}")
        except (OSError, IOError) as e:
            if log_cb:
                log_cb(f"[スキップ] {name}: {e}")
    return ops


def _ingest_dir(base, src, toggle, batch, resolver, log_cb, photo) -> list:
    """フォルダ投入時の処理"""
    name = os.path.basename(src)
    ops = []
    if toggle == "receive":
        # 解体せず12直下へ丸ごと
        actual = move_dir(src, os.path.join(base, rules.RECEIVE_DIR))
        ops.append({"op": "move", "src": src, "dst": actual,
                    "time": _now(), "batch": batch})
        if log_cb:
            log_cb(f"[受領] フォルダ {name} → 12_社外受領データ（丸ごと）")
        return ops
    if toggle == "submit":
        if log_cb:
            log_cb(f"[スキップ] フォルダ {name}: 提出トグルはファイルのみ対象")
        return ops
    # 通常: resolver("folder")で expand / keep を選択。既定=keep（Inboxへ維持移動）
    choice = resolver("folder", name, None) if resolver else "keep"
    if choice is None:  # キャンセル → 元の場所に残す
        if log_cb:
            log_cb(f"[キャンセル] フォルダ {name}: 処理を中止（元の場所に残します）")
        return ops
    if choice == "expand":
        for item in sorted(os.listdir(src)):  # 直下1階層のみ
            p = os.path.join(src, item)
            if os.path.isdir(p):
                actual = move_dir(p, os.path.join(base, rules.INBOX))
                ops.append({"op": "move", "src": p, "dst": actual,
                            "time": _now(), "batch": batch})
            else:
                folder = _resolve(p, resolver, log_cb)
                if not folder:
                    folder = rules.INBOX
                dst = (_dest_for(base, p, folder, photo)
                       if folder != rules.INBOX
                       else os.path.join(base, rules.INBOX, item))
                actual = move_file(p, dst)
                ops.append({"op": "move", "src": p, "dst": actual,
                            "time": _now(), "batch": batch})
                if log_cb:
                    log_cb(f"{item} → {os.path.relpath(actual, base)}")
        try:
            os.rmdir(src)  # 空になったら削除
        except OSError:
            pass
    else:
        actual = move_dir(src, os.path.join(base, rules.INBOX))
        ops.append({"op": "move", "src": src, "dst": actual,
                    "time": _now(), "batch": batch})
        if log_cb:
            log_cb(f"フォルダ {name} → 00_Inbox（維持移動）")
    return ops


def create_site(parent_dir: str, name: str, templates=None, log_cb=None) -> str:
    """新規現場のテンプレート一発作成（フォルダ構造＋雛形ファイル配置）"""
    base = os.path.join(parent_dir, name)
    if os.path.exists(base):
        raise ValueError(f"既に存在します: {base}")
    ensure_structure(base)
    for t in templates or []:
        src = t.get("src", "")
        dst_rel = t.get("dst", "") or ""
        if not src or not os.path.isfile(src):
            if log_cb:
                log_cb(f"[雛形スキップ] 見つかりません: {src}")
            continue
        dst_dir = os.path.join(base, dst_rel)
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
        if log_cb:
            log_cb(f"[雛形配置] {os.path.basename(src)} → {dst_rel or '（直下）'}")
    return base


def archive_files(base: str, paths: list, log_cb=None) -> list:
    """承認済みの旧版ファイルを 99_Archive へ移動（Undo可能な操作リストを返す）"""
    batch = _now()
    ops = []
    for src in paths:
        if not os.path.isfile(src):
            continue
        try:
            dst = move_file(src, os.path.join(
                base, rules.ARCHIVE, os.path.basename(src)))
            ops.append({"op": "move", "src": src, "dst": dst,
                        "time": _now(), "batch": batch})
            if log_cb:
                log_cb(f"[旧版] {os.path.basename(src)} → {rules.ARCHIVE}")
        except (OSError, IOError) as e:
            if log_cb:
                log_cb(f"[失敗] {os.path.basename(src)}: {e}")
    return ops


def send_to_inbox(base: str, paths: list, log_cb=None) -> list:
    """仮置き: ファイル/フォルダを 00_Inbox へ移動（仕分けしない）"""
    ensure_structure(base)
    inbox = os.path.join(base, rules.INBOX)
    moved = []
    for src in paths:
        try:
            if os.path.isdir(src):
                moved.append(move_dir(src, inbox))
            elif os.path.isfile(src):
                moved.append(move_file(src, os.path.join(inbox, os.path.basename(src))))
            else:
                continue
            if log_cb:
                log_cb(f"Inboxへ仮置き: {os.path.basename(src)}")
        except (OSError, IOError) as e:
            if log_cb:
                log_cb(f"[転送失敗] {os.path.basename(src)}: {e}")
    return moved
