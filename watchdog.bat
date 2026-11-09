@echo off
rem Resident watchdog: collection runs ONCE a day at 09:00 (and sends the daily email).
rem NOTE: keep this file ASCII-only - cmd parses .bat in ANSI (GBK) codepage.
setlocal
cd /d D:\\AI\\project\\Get_Information
if not exist logs mkdir logs

rem Web UI: serve.py is single-instance (exits if port 8123 is taken).
if exist "D:\\Anaconda\\pythonw.exe" powershell -NoProfile -Command "Start-Process 'D:\\Anaconda\\pythonw.exe' '%~dp0serve.py' -WindowStyle Hidden" >nul 2>&1

:loop
echo [%date% %time%] watchdog tick >> logs\\watchdog.log
call run_daily.bat
for /f %%s in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\\next_wait.ps1"') do set WAIT=%%s
echo [%date% %time%] watchdog sleep %WAIT%s >> logs\\watchdog.log
rem windowless consoles: `timeout` returns instantly, use Start-Sleep.
powershell -NoProfile -Command "Start-Sleep -Seconds %WAIT%" >nul 2>&1
goto loop
