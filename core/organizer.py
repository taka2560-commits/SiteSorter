# -*- coding: utf-8 -*-
"""仕分けエンジン v2（UI非依存）

優先順位: ①トグル（提出/受領） ②キーワード辞書 ③拡張子 ④90_その他
multi/zip など要確認の判定は resolver コールバックで解決（無ければスキップ/Inbox残し）
"""
import errno
import os
import shutil
import stat
import time
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rules

CHUNK_SIZE = 4 * 1024 * 1024
# 仕分け対象外（ロック・一時・同期ソフトの部分書き込みファイル）
TRANSIENT_EXTS = {".dwl", ".dwl2", ".part", ".tmp", ".crdownload", ".bak~"}


def _safe_path(base: str, candidate: str) -> None:
    """candidate が base 配下に収まることを確認（パストラバーサル防止）"""
    norm_base = os.path.normcase(os.path.abspath(base))
    norm_cand = os.path.normcase(os.path.abspath(candidate))
    if not (norm_cand == norm_base or norm_cand.startswith(norm_base + os.sep)):
        raise OSError("安全でないパスを検知しました（操作を中止）: %s" % candidate)


def is_transient(name: str) -> bool:
    return (os.path.splitext(name)[1].lower() in TRANSIENT_EXTS
            or name.startswith("~$") or name == "desktop.ini")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _batch_id() -> str:
    """Undo単位のID。秒単位だと同じ秒の連続ドロップが1つにまとまるのでマイクロ秒まで"""
    return datetime.now().isoformat(timespec="microseconds")


def ensure_structure(base: str) -> None:
    for d in rules.all_dirs():
        path = os.path.join(base, d)
        try:
            _safe_path(base, path)
        except OSError:
            continue  # rules.json の不正なフォルダ名（絶対パス・..）は現場の外に作らない
        os.makedirs(path, exist_ok=True)


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def is_protected(base: str, path: str) -> bool:
    """現場フォルダそのもの・その親・構成フォルダ（00_Inbox 等）か。

    これらをドロップで移動すると現場のフォルダ構成が崩れるため扱わない。
    """
    p = os.path.normcase(os.path.abspath(path))
    b = os.path.normcase(os.path.abspath(base))
    if p == b or b.startswith(p.rstrip(os.sep) + os.sep):
        return True
    for d in rules.all_dirs():
        parts = d.replace("\\", "/").split("/")
        for i in range(1, len(parts) + 1):
            if p == os.path.normcase(os.path.abspath(os.path.join(base, *parts[:i]))):
                return True
    return False


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
        if _is_readonly(path):
            # 読み取り専用属性のファイル（CD・受領データ等）は書き込みで開けないだけ。
            # 読み込みで開けるなら使用中ではない（移動自体は可能）
            try:
                with open(path, "rb"):
                    pass
                return False
            except OSError:
                return True
        return True
    return False


def _is_readonly(path: str) -> bool:
    try:
        return not (os.stat(path).st_mode & stat.S_IWRITE)
    except OSError:
        return False


def _remove_file(path: str) -> None:
    """ファイル削除（Windows の読み取り専用属性は外してから消す）"""
    try:
        os.remove(path)
    except PermissionError:
        if not _is_readonly(path):
            raise
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.remove(path)


def _rmtree(path: str) -> None:
    """フォルダ削除（読み取り専用ファイルを含んでいても消す）"""
    def _retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)


def get_photo_date(path: str, log_cb=None) -> str:
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(36867) or exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw)[:10], "%Y:%m:%d").strftime("%Y-%m-%d")
    except Exception:
        pass
    if log_cb:
        log_cb("[情報] %s: EXIF日付なし → ファイル更新日時を使用" % os.path.basename(path))
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


WRITE_CHECK_INTERVAL = 0.5  # 書き込み中チェックの2回のstatの間隔（秒）


def _stat_snapshot(files):
    """書き込み中チェックの1回目のstat: {パス: (サイズ, 更新日時) or None}"""
    snap = {}
    for f in files:
        try:
            st = os.stat(f)
            snap[f] = (st.st_size, st.st_mtime_ns)
        except OSError:
            snap[f] = None
    return snap


def _changed_since(snap):
    """2回目のstat: サイズ/更新日時が変化した（または読めなかった）ファイルの集合"""
    writing = set()
    for f, before in snap.items():
        try:
            st = os.stat(f)
            cur = (st.st_size, st.st_mtime_ns)
        except OSError:
            cur = None
        if before is None or cur is None or before != cur:
            writing.add(f)
    return writing


def _writing_set(files, interval=WRITE_CHECK_INTERVAL):
    """書き込み中（コピー途中等）のファイルの集合を返すバッチチェック。

    全ファイルのstat -> interval秒待機 -> 再stat で、サイズ/更新日時が変化した
    （または読めなかった）ファイルを書き込み中とみなす。待機は1回だけなので、
    ファイル数が増えても待ち時間は変わらない（ファイルごとに待たないこと）。
    """
    snap = _stat_snapshot(files)
    if not snap:
        return set()
    time.sleep(interval)
    return _changed_since(snap)


QUIET_SECONDS = 2.0  # これ以上前から変化がないファイルは書き込み中チェックの待機を省く


def _recently_changed(path, now):
    """直近 QUIET_SECONDS 秒以内に作成・更新された（または状態が読めない）か。

    コピー途中のファイルは作成・更新日時が「今」に近いので、必ず待機付きの
    チェックに回る。何秒も前から変化のないファイル（エクスプローラから
    ドラッグする通常のファイル）は待たずに移動し、一覧からすぐ消えるようにする。
    使用中のファイルは別途 is_locked() で検出する。
    """
    try:
        st = os.stat(path)
    except OSError:
        return True
    # Windows の st_ctime は作成日時、Linux は状態変更日時（どちらも新しい方で判定）
    return now - max(st.st_mtime, st.st_ctime) < QUIET_SECONDS


def _drop_targets(paths):
    """ドロップ経路で書き込み中チェックの対象になる通常ファイル（最近変化したもののみ）"""
    now = time.time()
    return [p for p in paths
            if not os.path.islink(p) and os.path.isfile(p)
            and not is_transient(os.path.basename(p))
            and _recently_changed(p, now)]


def drop_snapshot(paths):
    """ドロップ直後に取る1回目のstat（GUIを止めずに書き込み中チェックするため）。

    呼び出し側は WRITE_CHECK_INTERVAL 秒後に ingest_drop(..., snapshot=戻り値) を呼ぶ
    （戻り値が空＝最近変化したファイルがなければ待たずに呼んでよい）。
    その間に sleep せずイベントループを回すことで、ドロップ元（エクスプローラ）の
    ドラッグ操作がすぐ完了し、ドラッグ中の画像が画面に残らない。
    """
    return _stat_snapshot(_drop_targets(paths))


def _filter_writing(files, log_cb=None, skipped=None):
    """書き込み中のファイルを除外する（Inbox一括処理用）"""
    writing = _writing_set(files)
    stable = []
    for f in files:
        if f in writing:
            name = os.path.basename(f)
            if log_cb:
                log_cb("[スキップ] %s: 書き込み中（コピー未完了の可能性）" % name)
            if skipped is not None:
                skipped.append({"path": f, "toggle": None,
                                "reason": "書き込み中"})
        else:
            stable.append(f)
    return stable


def _size_or_zero(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _chunk_copy(src, dst, progress_cb=None):
    """チャンクコピー（.part -> 検証 -> 確定。中断時に不完全ファイルを残さない）

    コピー前後でソースのstat（サイズ・更新日時）を比較し、
    コピー中にファイルが変更された場合はIOErrorで中断する。
    """
    stat_before = os.stat(src)
    total = stat_before.st_size
    tmp = unique_path(dst + ".part")  # 同名の .part が既にあっても上書きしない
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
            raise IOError("コピー検証に失敗（サイズ不一致）: %s" % src)
        # コピー中にソースが変更されていないことを確認
        stat_after = os.stat(src)
        if (stat_before.st_size != stat_after.st_size
                or stat_before.st_mtime_ns != stat_after.st_mtime_ns):
            raise IOError(
                "コピー中にファイルが変更されました（書き込み中の可能性）: %s"
                % os.path.basename(src))
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def copy_file(src, dst, progress_cb=None):
    """コピー（元を残す）。同名衝突は自動リネーム。"""
    dst = unique_path(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    _chunk_copy(src, dst, progress_cb)
    return dst


def move_file(src, dst, progress_cb=None):
    """移動。同一ドライブはrename、異ドライブはチャンクコピー＋元削除。

    移動先が元と同じ場所なら何もせず src を返す（同名リネームを作らない）。
    コピー後に元を消せない（使用中など）場合は、コピーを消してから例外を出す
    （元と移動先の両方にファイルが残り、履歴にも載らない状態を作らない）。
    """
    if _same_path(src, dst):
        return src
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
    try:
        _remove_file(src)
    except OSError:
        _remove_file(dst)
        raise
    return dst


def move_tree(src, dst, log_cb=None):
    """フォルダを dst（存在しないパス）へ移動。

    同一ドライブは rename（失敗したらそのまま例外）。別ドライブはコピー → 元を削除。コピーに失敗したら
    途中までのコピーを消して例外（元はそのまま）。コピー完了後に元の一部を
    消せなかった場合は、全データが dst にあるので移動成功として扱い、ログで知らせる。
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
        return dst
    except OSError as e:
        if e.errno != errno.EXDEV:
            # 別ドライブ以外の失敗（中のファイルが使用中・権限など）はコピーに切り替えない。
            # 全部コピーしてから元を一部しか消せない、という中途半端な状態を作らないため
            raise
    try:
        shutil.copytree(src, dst, symlinks=True)
    except BaseException:
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        raise
    try:
        _rmtree(src)
    except OSError as e:
        if log_cb:
            log_cb("[注意] %s: 移動先へのコピーは完了しましたが、元フォルダの一部を"
                   "削除できませんでした（使用中のファイルがある可能性）: %s"
                   % (os.path.basename(src), e))
    return dst


def move_dir(src, dst_dir, log_cb=None):
    """フォルダを丸ごと dst_dir 直下へ移動（衝突時はフォルダ名にタイムスタンプ付与）"""
    dst = os.path.join(dst_dir, os.path.basename(src))
    if _same_path(src, dst):
        return src
    return move_tree(src, unique_path(dst), log_cb)


def _dest_for(base, src, folder, photo, log_cb=None):
    """フォルダ判定結果から最終パスを組み立て（受領=日付/写真=撮影日）"""
    name = os.path.basename(src)
    if folder == rules.RECEIVE_DIR:
        dst = os.path.join(base, folder, "%s_受領" % _today(), name)
    elif photo and folder == photo:
        dst = os.path.join(base, folder, get_photo_date(src, log_cb), name)
    else:
        dst = os.path.join(base, folder, name)
    _safe_path(base, dst)
    return dst


def _resolve(src, resolver, log_cb):
    """classify結果のmulti/zipをresolverで解決。未解決はNone（スキップ）。"""
    name = os.path.basename(src)
    c = rules.classify(name)
    if "folder" in c:
        return c["folder"]
    if "multi" in c:
        folder = resolver("multi", name, c["multi"]) if resolver else None
        if not folder and log_cb:
            log_cb("[要確認] %s: 複数カテゴリ該当 → %s（スキップ）" % (name, " / ".join(c["multi"])))
        return folder
    # zip（トグルなし）
    folder = resolver("zip", name, None) if resolver else None
    if not folder and log_cb:
        log_cb("[要確認] %s: .zipの移動先が未確定（スキップ）" % name)
    return folder


def preflight(base):
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


def organize(base, progress_cb=None, log_cb=None, resolver=None,
             skipped=None):
    """00_Inbox の一括仕分け。戻り値: 操作リスト（Undo用）"""
    ensure_structure(base)
    batch = _batch_id()
    photo = rules.photo_dir()
    files = scan_inbox(base)
    # 書き込み中（Explorerでコピー途中等）のファイルを事前に除外
    files = _filter_writing(files, log_cb, skipped)
    # 処理中にファイルが消えても止まらないよう、サイズは先に取得しておく
    sizes = {f: _size_or_zero(f) for f in files}
    total_bytes = sum(sizes.values()) or 1
    done = 0
    ops = []
    for src in files:
        name = os.path.basename(src)
        size = sizes[src]
        try:
            if is_transient(name):
                continue  # ロック・一時ファイルは触らない
            if os.path.islink(src):
                if log_cb:
                    log_cb("[スキップ] %s: シンボリックリンクは処理できません" % name)
                continue
            if not os.path.isfile(src):
                if log_cb:
                    log_cb("[スキップ] %s: 見つかりません（移動・削除された可能性）" % name)
                continue
            if is_locked(src):
                if log_cb:
                    log_cb("[スキップ] %s: 使用中（ロック検知）" % name)
                if skipped is not None:
                    skipped.append({"path": src, "toggle": None,
                                    "reason": "ロック中"})
                continue
            folder = _resolve(src, resolver, log_cb)
            if not folder:
                continue
            dst = _dest_for(base, src, folder, photo, log_cb)

            def cb(c, _t, _b=done):
                if progress_cb:
                    progress_cb(_b + c, total_bytes, name)
            actual = move_file(src, dst, cb)
            ops.append({"op": "move", "src": src, "dst": actual,
                        "time": _now(), "batch": batch})
            if log_cb:
                log_cb("%s → %s" % (name, os.path.relpath(actual, base)))
        except (OSError, IOError) as e:
            if log_cb:
                log_cb("[スキップ] %s: %s" % (name, e))
        finally:
            done += size
            if progress_cb:
                progress_cb(done, total_bytes, name)
    return ops


def ingest_drop(base, paths, toggle=None,
                progress_cb=None, log_cb=None, resolver=None,
                skipped=None, snapshot=None):
    """ドロップ経路の即時仕分け。

    toggle: None / "submit"（提出） / "receive"（受領）
    snapshot: drop_snapshot() の戻り値。渡すとここでは待たず、その時点からの
              変化で書き込み中を判定する（GUI側で待機をイベントループに任せる場合）
    戻り値: 操作リスト（Undo用）
    """
    ensure_structure(base)
    batch = _batch_id()
    photo = rules.photo_dir()
    # 書き込み中チェックはドロップ全体で1回だけ待機する
    if snapshot is None:
        writing = _writing_set(_drop_targets(paths))
    else:
        writing = _changed_since(snapshot)
    ops = []
    for src in paths:
        name = os.path.basename(src)
        try:
            if os.path.islink(src):
                if log_cb:
                    log_cb("[スキップ] %s: シンボリックリンクは処理できません" % name)
                continue
            if is_protected(base, src):
                if log_cb:
                    log_cb("[スキップ] %s: 現場フォルダ・構成フォルダは移動できません" % name)
                continue
            if os.path.isdir(src):
                ops += _ingest_dir(base, src, toggle, batch, resolver, log_cb, photo,
                                   skipped)
                continue
            if not os.path.isfile(src):
                continue
            if is_transient(name):
                if log_cb:
                    log_cb("[スキップ] %s: 一時/ロックファイル" % name)
                continue
            locked = is_locked(src)
            if locked or src in writing:
                reason = "使用中" if locked else "書き込み中"
                if log_cb:
                    log_cb("[スキップ] %s: %s" % (name, reason))
                if skipped is not None:
                    skipped.append({"path": src, "toggle": toggle,
                                    "reason": reason})
                continue
            if toggle == "receive":
                dst = os.path.join(base, rules.RECEIVE_DIR, "%s_受領" % _today(), name)
                actual = move_file(src, dst, progress_cb and (lambda c, t: progress_cb(c, t, name)))
                ops.append({"op": "move", "src": src, "dst": actual,
                            "time": _now(), "batch": batch})
                if log_cb:
                    log_cb("[受領] %s → %s" % (name, os.path.relpath(actual, base)))
            elif toggle == "submit":
                sub = os.path.join(base, rules.SUBMIT_DIR, "%s_提出" % _today(), name)
                if name.lower().endswith(".zip"):
                    actual = copy_file(src, sub)
                    ops.append({"op": "copy", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb("[提出/zip] %s → %s" % (name, os.path.relpath(actual, base)))
                else:
                    work = os.path.join(base, rules.WORK_DIR, name)
                    a1 = copy_file(src, work)
                    try:
                        a2 = copy_file(src, sub)
                    except BaseException:
                        _remove_file(a1)  # 片方だけのコピーを履歴に載らないまま残さない
                        raise
                    ops.append({"op": "copy_dual", "src": src, "dst": a1,
                                "dst2": a2, "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb("[提出] %s → 10_図面_作業用 と %s に同時コピー"
                               % (name, os.path.relpath(a2, base)))
            else:
                folder = _resolve(src, resolver, None)
                if not folder:
                    # 未確定はInboxへ仮置き（消失防止）
                    dst = os.path.join(base, rules.INBOX, name)
                    actual = move_file(src, dst)
                    ops.append({"op": "move", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb("[要確認] %s: 移動先未確定のためInboxへ仮置き" % name)
                else:
                    dst = _dest_for(base, src, folder, photo, log_cb)
                    actual = move_file(src, dst, progress_cb and (lambda c, t: progress_cb(c, t, name)))
                    ops.append({"op": "move", "src": src, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb("%s → %s" % (name, os.path.relpath(actual, base)))
        except (OSError, IOError) as e:
            if log_cb:
                log_cb("[スキップ] %s: %s" % (name, e))
    return _drop_noop(ops)


def _drop_noop(ops):
    """既に移動先にあった（移動しなかった）操作を除く（Undo・件数に載せない）"""
    return [o for o in ops if not (o["op"] == "move" and _same_path(o["src"], o["dst"]))]


def summarize_ops(base, ops):
    """操作リストを移動先の第1階層フォルダごとに集計 → [(フォルダ名, 件数), ...]

    件数の多い順（同数は先に出た順）。提出の同時コピーは2箇所それぞれに数える。
    """
    counts = {}
    for op in ops:
        for dst in (op.get("dst"), op.get("dst2")):
            if not dst:
                continue
            rel = os.path.relpath(dst, base)
            top = rel.split(os.sep)[0] if not rel.startswith("..") else \
                os.path.basename(os.path.dirname(dst))
            counts[top] = counts.get(top, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def _ingest_dir(base, src, toggle, batch, resolver, log_cb, photo, skipped=None):
    """フォルダ投入時の処理"""
    name = os.path.basename(src)
    ops = []
    if toggle == "receive":
        # 解体せず12直下へ丸ごと
        actual = move_dir(src, os.path.join(base, rules.RECEIVE_DIR), log_cb)
        ops.append({"op": "move", "src": src, "dst": actual,
                    "time": _now(), "batch": batch})
        if log_cb:
            log_cb("[受領] フォルダ %s → 12_社外受領データ（丸ごと）" % name)
        return ops
    if toggle == "submit":
        if log_cb:
            log_cb("[スキップ] フォルダ %s: 提出トグルはファイルのみ対象" % name)
        return ops
    # 通常: resolver("folder")で expand / keep / others を選択。既定=keep（Inboxへ維持移動）
    choice = resolver("folder", name, None) if resolver else "keep"
    if choice is None:  # キャンセル → 元の場所に残す
        if log_cb:
            log_cb("[キャンセル] フォルダ %s: 処理を中止（元の場所に残します）" % name)
        return ops
    if choice == "others":
        # 解体せず 90_その他 へ丸ごと（仕分け不要のフォルダ用）
        actual = move_dir(src, os.path.join(base, rules.OTHERS), log_cb)
        ops.append({"op": "move", "src": src, "dst": actual,
                    "time": _now(), "batch": batch})
        if log_cb:
            log_cb("フォルダ %s → %s（丸ごと）" % (name, rules.OTHERS))
        return ops
    if choice == "expand":
        for item in sorted(os.listdir(src)):  # 直下1階層のみ
            p = os.path.join(src, item)
            # 1件の失敗で残りの処理と移動済み分の履歴を失わないよう個別に捕捉
            try:
                if os.path.islink(p):
                    if log_cb:
                        log_cb("[スキップ] %s: シンボリックリンクは処理できません" % item)
                    continue
                if is_protected(base, p):
                    continue
                if os.path.isdir(p):
                    actual = move_dir(p, os.path.join(base, rules.INBOX), log_cb)
                    ops.append({"op": "move", "src": p, "dst": actual,
                                "time": _now(), "batch": batch})
                else:
                    if is_transient(item):
                        continue  # ロック・一時ファイルは元フォルダに残す
                    if is_locked(p):
                        if log_cb:
                            log_cb("[スキップ] %s: 使用中" % item)
                        if skipped is not None:
                            skipped.append({"path": p, "toggle": toggle,
                                            "reason": "使用中"})
                        continue
                    folder = _resolve(p, resolver, log_cb)
                    if not folder:
                        folder = rules.INBOX
                    dst = (_dest_for(base, p, folder, photo, log_cb)
                           if folder != rules.INBOX
                           else os.path.join(base, rules.INBOX, item))
                    actual = move_file(p, dst)
                    ops.append({"op": "move", "src": p, "dst": actual,
                                "time": _now(), "batch": batch})
                    if log_cb:
                        log_cb("%s → %s" % (item, os.path.relpath(actual, base)))
            except (OSError, IOError) as e:
                if log_cb:
                    log_cb("[スキップ] %s: %s" % (item, e))
        try:
            os.rmdir(src)  # 空になったら削除
        except OSError:
            pass
    else:
        actual = move_dir(src, os.path.join(base, rules.INBOX), log_cb)
        ops.append({"op": "move", "src": src, "dst": actual,
                    "time": _now(), "batch": batch})
        if log_cb:
            log_cb("フォルダ %s → 00_Inbox（維持移動）" % name)
    return ops


def create_site(parent_dir, name, templates=None, log_cb=None):
    """新規現場のテンプレート一発作成（フォルダ構造＋雛形ファイル配置）"""
    name = (name or "").strip()
    if (not name or name in (".", "..") or "/" in name or "\\" in name
            or any(c in name for c in '<>:"|?*')):
        raise ValueError("現場名に使えない文字が含まれています: %s" % name)
    base = os.path.join(parent_dir, name)
    if os.path.exists(base):
        raise ValueError("既に存在します: %s" % base)
    ensure_structure(base)
    for t in templates or []:
        src = t.get("src", "")
        dst_rel = t.get("dst", "") or ""
        if not src or not os.path.isfile(src):
            if log_cb:
                log_cb("[雛形スキップ] 見つかりません: %s" % src)
            continue
        dst_dir = os.path.join(base, dst_rel)
        try:
            _safe_path(base, dst_dir)
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
        except OSError as e:
            if log_cb:
                log_cb("[雛形スキップ] %s: %s" % (os.path.basename(src), e))
            continue
        if log_cb:
            log_cb("[雛形配置] %s → %s" % (os.path.basename(src), dst_rel or "（直下）"))
    return base


def archive_files(base, paths, log_cb=None):
    """承認済みの旧版ファイルを 99_Archive へ移動（Undo可能な操作リストを返す）"""
    batch = _batch_id()
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
                log_cb("[旧版] %s → %s" % (os.path.basename(src), rules.ARCHIVE))
        except (OSError, IOError) as e:
            if log_cb:
                log_cb("[失敗] %s: %s" % (os.path.basename(src), e))
    return ops


def send_to_inbox(base, paths, log_cb=None):
    """仮置き: ファイル/フォルダを 00_Inbox へ移動（仕分けしない）

    戻り値: 操作リスト（Undo用）
    """
    ensure_structure(base)
    inbox = os.path.join(base, rules.INBOX)
    batch = _batch_id()
    ops = []
    for src in paths:
        name = os.path.basename(src)
        try:
            if os.path.islink(src):
                if log_cb:
                    log_cb("[スキップ] %s: シンボリックリンクは処理できません" % name)
                continue
            if is_protected(base, src):
                if log_cb:
                    log_cb("[スキップ] %s: 現場フォルダ・構成フォルダは移動できません" % name)
                continue
            if os.path.isdir(src):
                actual = move_dir(src, inbox, log_cb)
            elif os.path.isfile(src):
                actual = move_file(src, os.path.join(inbox, name))
            else:
                continue
            ops.append({"op": "move", "src": src, "dst": actual,
                        "time": _now(), "batch": batch})
            if log_cb:
                log_cb("Inboxへ仮置き: %s" % name)
        except (OSError, IOError) as e:
            if log_cb:
                log_cb("[転送失敗] %s: %s" % (name, e))
    return _drop_noop(ops)
