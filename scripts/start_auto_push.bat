@echo off
REM 雙擊：開一個視窗監看專案，檔案有變動就測試並推到 GitHub（網站自動更新）。關掉視窗就停止。
chcp 65001 >nul
cd /d "%~dp0.."
py scripts\auto_push.py
pause
