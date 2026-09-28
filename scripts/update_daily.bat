@echo off
REM 每日自動更新股價（和 TEJ 無關）。由 Windows 工作排程器在平日 14:45 執行，也可以直接雙擊。
REM 想讓公開網站也每天自動更新：把下一行改成 set PUSH_TO_GITHUB=1（需要已經用 git 設定好 GitHub）
set PUSH_TO_GITHUB=0

chcp 65001 >nul
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> data\processed\auto_update.log
py scripts\update_data.py --auto >> data\processed\auto_update.log 2>&1

if "%PUSH_TO_GITHUB%"=="1" (
  py scripts\run_backtest.py >> data\processed\auto_update.log 2>&1
  git add data/processed outputs/cache >> data\processed\auto_update.log 2>&1
  git commit -m "daily data update" >> data\processed\auto_update.log 2>&1
  git push >> data\processed\auto_update.log 2>&1
)
