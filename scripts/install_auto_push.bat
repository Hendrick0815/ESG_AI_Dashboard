@echo off
REM 雙擊一次：登入 Windows 後自動在背景執行「自動發佈」，不會出現視窗。現在也會馬上啟動。
REM 取消：刪除「啟動」資料夾裡的 ESG-AI-auto-push.bat（按 Win+R 輸入 shell:startup 就能打開）。
chcp 65001 >nul
set "ROOT=%~dp0.."
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
  echo @echo off
  echo cd /d "%ROOT%"
  echo start "" pyw scripts\auto_push.py
) > "%STARTUP%\ESG-AI-auto-push.bat"
cd /d "%ROOT%"
start "" pyw scripts\auto_push.py
echo.
echo 已設定：登入後自動在背景監看，檔案變動就測試並推到 GitHub。
echo 執行紀錄：data\processed\auto_push.log
echo 取消：Win+R 輸入 shell:startup，刪掉 ESG-AI-auto-push.bat
pause
