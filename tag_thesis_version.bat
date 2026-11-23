@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Tag frozen thesis version: thesis-v2-2026-10-20 ===
echo Run start_auto_push.bat first so the latest files are committed.
git tag -a thesis-v2-2026-10-20 -m "Thesis v2 frozen: data cutoff 2026-10-20, TEJ prices, T+1 open execution (run_id thesis_2026-10-20_v2)"
if errorlevel 1 (
  echo Tag already exists or git error. Nothing changed.
) else (
  git push origin thesis-v2-2026-10-20
  echo Done. The tag is now on GitHub.
)
pause
