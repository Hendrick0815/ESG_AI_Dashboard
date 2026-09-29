@echo off
REM 雙擊一次：把「每日自動更新股價」的設定放到 .github\workflows\，推上 GitHub 後就會每天自動執行。
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".github\workflows" mkdir ".github\workflows"
copy /Y "scripts\daily_update.yml" ".github\workflows\daily_update.yml" >nul
echo 已建立 .github\workflows\daily_update.yml
echo 接下來推上 GitHub（開著 auto_push 會自動推；或用 GitHub Desktop 按 Commit、Push）
pause
