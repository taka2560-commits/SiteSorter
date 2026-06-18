@echo off
cd /d "%~dp0"
echo === SiteSorter exe化ビルド ===

if not exist venv\Scripts\python.exe (
    echo 先に setup.bat を実行してください。
    pause
    exit /b 1
)

echo [1/3] PyInstallerを準備中...
venv\Scripts\pip install pyinstaller -q
if errorlevel 1 goto FAIL

echo [2/3] ビルド中（数分かかります）...
venv\Scripts\pyinstaller --noconfirm --onefile --noconsole ^
  --name SiteSorter ^
  --icon assets\app.ico ^
  --add-data "assets;assets" ^
  --collect-data qtawesome ^
  main.py
if errorlevel 1 goto FAIL

echo [3/3] 完了確認...
if not exist dist\SiteSorter.exe goto FAIL

echo.
echo === ビルド完了: dist\SiteSorter.exe ===
echo 設定は %%APPDATA%%\SiteSorter に保存されるため、exe単体で配布できます。
echo ※ウイルス対策ソフトに誤検知される場合は --onefile を外した
echo 　フォルダ形式（--onedir）でのビルドも検討してください。
pause
exit /b 0

:FAIL
echo [エラー] ビルドに失敗しました。上のメッセージを確認してください。
pause
exit /b 1
