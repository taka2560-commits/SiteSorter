# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

SiteSorter は、建設現場のプロジェクトフォルダを整理するデスクトップアプリケーション（Windows メイン、Linux 対応）。PySide6 GUI にシステムトレイアイコン、常時前面表示のドラッグ＆ドロップゾーン、バッチ仕分け、完全な元に戻す機能を備える。PyInstaller でスタンドアロン `.exe` として配布。

## コマンド

**環境セットアップ（Windows）:**
```bat
setup.bat          # venv 作成 → pip install -r requirements.txt → テスト実行
```

**アプリ起動:**
```bat
起動.bat            # venv 経由で起動（コンソール非表示）
# または直接:
venv\Scripts\pythonw.exe main.py
```

**テスト実行:**
```bash
python test_core.py       # コアエンジンテスト（分類・履歴・アンドゥ・EXIF）
python test_phase_d.py    # Phase D 機能テスト
python test_phase_e.py    # Phase E 機能テスト
python test_ui.py         # 画面まわり（起動・ドロップゾーン・二重起動・エラー記録）。画面なし環境は QT_QPA_PLATFORM=offscreen
```

**EXE ビルド:**
```bat
build.bat          # dist\SiteSorter.exe を生成（--onefile --noconsole）
```

## アーキテクチャ

### モジュール構成

```
main.py              # エントリポイント: QApplication・トレイ・MainWindow・DropZone
config.py            # 設定の読み書き・旧 APPDATA パスからの自動マイグレーション
rules.py             # ルールの読み書き・v1→v2 自動マイグレーション・フォルダ定義
core/
  organizer.py       # ファイル分類＋移動エンジン（539行）
  history.py         # アンドゥスタック（最大50件・バッチ単位）
  capacity.py        # ディスク容量計算（キャッシュあり）
  worker.py          # 非同期処理用 QThread ワーカー
  versions.py        # 旧バージョンサフィックス検出（正規表現）
ui/
  main_window.py     # 3ページサイドバー: ダッシュボード／履歴／設定（663行）
  drop_zone.py       # 常時前面表示のドラッグ＆ドロップウィジェット
  theme.py           # Earth・Night テーマ定義
  dialogs.py         # 確認ダイアログ
  archive_dialog.py  # 旧バージョンアーカイブ UI
  retry_dialog.py    # 失敗・ロックファイルのリトライ UI
  rule_editor.py     # ソートルール編集 GUI（JSON バックエンド）
```

### データフロー

**バッチ仕分け（Inbox）:**
1. `organizer.preflight(base)` — Inbox をスキャンし、複数マッチ・zip ファイルをユーザー確認用にフラグ
2. ユーザーがダイアログで競合を解決
3. `organizer.organize(base, resolver_callback)` — 各ファイルを分類して移動／コピー
4. 操作を1バッチエントリとして `history.json` に記録

**ドラッグ＆ドロップ（DropZone）:**
1. `organizer.ingest_drop(base, paths, toggle)` — ファイルを即時分類・移動
2. トグルモードで移動先が変わる: `None` = 通常分類、`submit` = 11 または 10、`receive` = 12。フォルダ（トグルなし）は `resolver("folder")` で `expand`（直下を個別仕分け）/ `keep`（丸ごと Inbox）/ `others`（丸ごと 90_その他）/ `None`（キャンセル）
3. ロック中・書き込み中ファイルは理由をログに残してスキップ
4. 結果（`summarize_ops()` による移動先フォルダ別の件数・未処理件数）をドロップゾーンに表示し、表示中は「元に戻す」/ Ctrl+Z で `History.undo_batch()` によりそのドロップのバッチだけを取り消す（バッチIDは `_batch_id()` でマイクロ秒単位）

**分類優先順位（高 → 低）:**
1. トグルモード上書き（submit → フォルダ 11 または 10、receive → 12）
2. キーワードマッチ（ファイル名に設定キーワードを含む）
3. 拡張子マッチ（フォルダの拡張子リストに一致）
4. デフォルト → `90_その他`
5. 複数マッチ・zip → ユーザー判断が必要

### 標準フォルダ構成（v2）

```
00_Inbox               ← 起点。すべてのファイルはここから始まる
10_図面_作業用          ← CAD 作業ファイル
11_図面_提出済          ← 提出済図面（上書き禁止の意図で扱う）
12_社外受領データ        ← 外部受領データ
13_図面_PDF            ← PDF 図面
20_測量データ           ← 測量データ
21_3Dスキャン/
  01_RAWデータ_FLS
  02_プロジェクトデータ
  03_エクスポート点群
30_現場写真             ← 写真。EXIF 日付を読み取り YYYY-MM-DD サブフォルダを作成
40_報告書・書類          ← 報告書・書類
90_その他               ← 未分類
99_Archive_旧データ     ← 旧バージョンアーカイブ
```

### 設定ファイル（ユーザーごと）

`%APPDATA%\SiteSorter`（Windows）/ `~/.config/SiteSorter`（Linux）に保存。旧パスからは自動マイグレーション:

- `settings.json` — テーマ・現場フォルダパス・ドロップゾーン位置・容量キャッシュ・テンプレート
- `rules.json` — フォルダ定義（キーワード・拡張子）。v1→v2 マイグレーション内蔵
- `history.json` — アンドゥスタック（最大50件・バッチ単位）

JSON 読み込みの最大ファイルサイズ: **10 MB**（メモリ枯渇防止のため強制）

### セキュリティ上の不変条件

以下は削除禁止の重要な制約:
- `organizer.py` の `_safe_path()` — すべての移動先パスがサイトルート内に収まることを検証（パストラバーサル対策）
- ファイル操作前にシンボリックリンクを拒否
- 書き込み中ファイルはダブルスタット（0.5秒間隔）で検出してスキップ。待機は呼び出しごとに1回（`_writing_set()`）で、ファイルごとに待たない（ドロップ処理はGUIスレッドで動くため、ファイル数に比例して画面が固まる）。ドロップゾーンでは `sleep` せず、`drop_snapshot()` → `QTimer` で0.5秒後に `ingest_drop(..., snapshot=)` を呼ぶ（GUIスレッドで待つとエクスプローラのドラッグ操作が終われず、ドラッグ画像が画面に残る）。ドロップ経路では作成・更新から `QUIET_SECONDS`（2秒）以上経ったファイルは待機を省く（コピー途中のファイルは作成・更新日時が新しいので必ず待機付きチェックに回る。使用中は `is_locked()` で検出）
- ロックファイルは捕捉して `retry_dialog.py` に渡す
- 現場フォルダそのもの・その親・構成フォルダ（`rules.all_dirs()`）は `is_protected()` でドロップ・仮置きの対象外（移動すると現場の構成が崩れる）
- ルールのフォルダ名は `rules.valid_folder_name()` で現場内の相対パスに限る（絶対パス・`..` 不可）。`ensure_structure()` も現場外には作らない
- 移動は失敗時に中途半端な状態を残さない: 別ドライブ移動で元を消せなければコピーを消す（`move_file`）、フォルダのコピー失敗時は途中のコピーを消す（`move_tree`）、提出の2箇所目のコピー失敗時は1箇所目を消す
- 元に戻せなかった操作（使用中など）は履歴に残して再試行可能にする。移動先が消えている操作だけ履歴から外す（`History._undo_ops`）
- settings.json / rules.json / history.json は `config.write_json_atomic()`（一時ファイル → 置き換え）で保存する。読めなかった settings.json は `.broken` に退避
- 二重起動は `QLockFile`（`%APPDATA%\SiteSorter\SiteSorter.lock`）で防ぐ。想定外の例外は `error.log` とログ画面に出す（EXE はコンソールが無い）
- 仕分けループ内の失敗はファイル単位で捕捉し、移動済み分の操作（Undo用）を失わない。`SortWorker` は例外時も `finished_batch` を必ず送る

### テストの規約

`tempfile.mkdtemp()` で独立したフォルダツリーを作成し、ファイル／サブフォルダを手動セットアップしてコア関数を直接呼び出す（モックフレームワークなし）。アサーションは合否カウンターを使った手動チェック。新しいテストを追加する際は `test_core.py` のパターンに従う: 一時ディレクトリ作成 → シナリオセットアップ → 関数呼び出し → アサーション → クリーンアップ。

各テストファイルは本体モジュールを import する前に `APPDATA`（Linux は `HOME`）を一時フォルダへ向ける。`config.py` は import 時に保存先を決めるため、これを怠ると実環境の `%APPDATA%\SiteSorter\rules.json` を書き換え・削除してしまう。新しいテストファイルにも同じ冒頭処理を入れること。
