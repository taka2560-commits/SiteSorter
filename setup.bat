@echo off
cd /d "%~dp0"
echo === SiteSorter セットアップ ===

where python >nul 2>&1
if errorlevel 1 goto NOPYTHON

echo [1/3] 仮想環境を作成中...
python -m venv venv
if errorlevel 1 goto FAIL

echo [2/3] ライブラリをインストール中（数分かかります）...
venv\Scripts\python -m pip install --upgrade pip -q
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto FAIL

echo [3/3] 動作テストを実行中...
venv\Scripts\python test_core.py
if errorlevel 1 goto FAIL

echo.
echo === セットアップ完了 ===
echo 今後は「起動.bat」をダブルクリックで起動できます。
pause
exit /b 0

:NOPYTHON
echo [エラー] Pythonが見つかりません。
echo https://www.python.org/downloads/ からインストールしてください。
echo ※インストール時に「Add python.exe to PATH」に必ずチェック
pause
exit /b 1

:FAIL
echo [エラー] 処理に失敗しました。上のメッセージを確認してください。
pause
exit /b 1
