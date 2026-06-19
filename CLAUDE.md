# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SiteSorter is a desktop application (Windows-primary, Linux-compatible) for organizing Japanese construction site project folders. It provides a PySide6 GUI with a system tray icon, an always-on-top drag-drop zone, batch file sorting, and full undo support. Distribution is as a standalone `.exe` via PyInstaller.

## Commands

**Environment setup (Windows):**
```bat
setup.bat          # Creates venv, pip install -r requirements.txt, runs tests
```

**Run the app:**
```bat
起動.bat            # Launch via venv (hides console)
# or directly:
venv\Scripts\pythonw.exe main.py
```

**Run tests:**
```bash
python test_core.py       # Core engine tests (classification, history, undo, EXIF)
python test_phase_d.py    # Phase D feature tests
python test_phase_e.py    # Phase E feature tests
```

**Build distributable EXE:**
```bat
build.bat          # Produces dist\SiteSorter.exe (--onefile --noconsole)
```

## Architecture

### Module Layout

```
main.py              # Entry point: QApplication, tray, MainWindow, DropZone
config.py            # Settings load/save, auto-migration from old APPDATA path
rules.py             # Rules load/save, v1→v2 auto-migration, folder definitions
core/
  organizer.py       # File classification + movement engine (515 LOC)
  history.py         # Undo stack (max 50 ops, batch-aware)
  capacity.py        # Disk capacity calculation with caching
  worker.py          # QThread workers for async organize/undo
  versions.py        # Old version suffix detection (regex-based)
ui/
  main_window.py     # 3-page sidebar: Dashboard / History / Settings (661 LOC)
  drop_zone.py       # Always-on-top drag-drop widget
  theme.py           # Earth + Night theme definitions
  dialogs.py         # Confirmation dialogs
  archive_dialog.py  # Old version archival UI
  retry_dialog.py    # Failed/locked file retry UI
  rule_editor.py     # GUI for editing sort rules (JSON-backed)
```

### Data Flow

**Batch sorting (Inbox):**
1. `organizer.preflight(base)` — scans Inbox, flags multi-match and zip files for user confirmation
2. User resolves conflicts via dialogs
3. `organizer.organize(base, resolver_callback)` — classifies and moves/copies each file
4. Operations logged as a single batch entry in `history.json`

**Drag-and-drop (DropZone):**
1. `organizer.ingest_drop(base, paths, toggle)` — classifies and moves files immediately
2. Toggle modes affect destination: `None` = classify normally, `submit` = 11/10, `receive` = 12
3. Locked/write-in-progress files are skipped with reason logging

**Classification priority (highest → lowest):**
1. Toggle mode override (submit → folder 11 or 10, receive → folder 12)
2. Keyword match (filename contains a configured keyword)
3. Extension match (file suffix in a folder's extension list)
4. Default → `90_その他`
5. Multi-match or zip → user decision required

### Standard Folder Structure (v2)

```
00_Inbox               ← source; all files start here
10_図面_作業用          ← CAD working files
11_図面_提出済          ← submitted drawings (treated as sacred/read-only intent)
12_社外受領データ        ← externally received data
13_図面_PDF            ← PDF drawings
20_測量データ           ← survey data
21_3Dスキャン/
  01_RAWデータ_FLS
  02_プロジェクトデータ
  03_エクスポート点群
30_現場写真             ← photos; EXIF date read to create YYYY-MM-DD subfolders
40_報告書・書類          ← reports and documents
90_その他               ← unclassified
99_Archive_旧データ     ← archived old versions
```

### Persistent Config (per-user)

Config files live in `%APPDATA%\SiteSorter` (Windows) / `~/.config/SiteSorter` (Linux), auto-migrated from older locations:

- `settings.json` — theme, current site folder path, drop zone position, capacity cache, templates
- `rules.json` — folder definitions with keywords and extensions (v1→v2 migration built in)
- `history.json` — undo stack (max 50 operations, stored as batches)

Max file size for JSON reads: **10 MB** (enforced to prevent memory exhaustion).

### Security Invariants

These are load-bearing constraints — do not remove:
- `_safe_path()` in `organizer.py` validates that all resolved destination paths stay within the site root (path traversal protection)
- Symlinks are rejected before any file operation
- Write-in-progress files are detected via double-stat (0.5 s interval) and skipped
- Locked files are caught and surfaced to `retry_dialog.py`

### Testing Conventions

Tests use `tempfile.mkdtemp()` to create isolated folder trees, manually set up files/subfolders, then call core functions directly (no mocking framework). Assertions are manual checks with a running pass/fail counter. To add a new test, follow the pattern in `test_core.py`: create temp dir → set up scenario → call function → assert → cleanup.
