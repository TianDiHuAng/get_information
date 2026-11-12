@echo off
REM 每天自动跑一次信息雷达。由 Windows 计划任务「Z-Bit 每日采集」调用。
REM 日志按天写到 logs\run-YYYYMMDD.log，失败时退出码非 0。
chcp 65001 >nul
cd /d "%~dp0"

set LOG=logs\run-%date:~0,4%%date:~5,2%%date:~8,2%.log
if not exist logs mkdir logs

echo [%date% %time%] 开始 >> "%LOG%"
python run.py --no-mail --dry-push >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%
echo [%date% %time%] 结束 exit=%CODE% >> "%LOG%"

REM 跑完重建站点（AI + AIDD），否则页面还是旧的
if %CODE%==0 (
  python tools\build_sites.py --site site --data data --db data\radar.db >> "%LOG%" 2>&1
  set RADAR_PACK=aidd
  python tools\build_sites.py --site site\aidd --data data-aidd --db data\aidd.db --base /aidd >> "%LOG%" 2>&1
  set RADAR_PACK=
)

exit /b %CODE%
