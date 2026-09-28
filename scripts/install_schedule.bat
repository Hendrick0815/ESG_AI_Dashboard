@echo off
REM 雙擊一次即可：建立 Windows 排程「ESG-AI-DailyUpdate」，週一到週五 14:45 自動抓最新收盤價。
REM 取消排程：schtasks /Delete /TN "ESG-AI-DailyUpdate" /F
chcp 65001 >nul
schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 14:45 /TN "ESG-AI-DailyUpdate" /TR "\"%~dp0update_daily.bat\"" /F
if %errorlevel%==0 (
  echo.
  echo 已建立排程：平日 14:45 自動更新股價。電腦需要開機（睡眠中不會執行）。
  echo 執行紀錄：data\processed\auto_update.log
) else (
  echo 建立失敗，請改用「以系統管理員身分執行」。
)
pause
