@echo off
chcp 65001 >nul
cd /d D:\AI\project\Get_Information
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo. >> logs\run.log
echo ===== [%date% %time%] start ===== >> logs\run.log
D:\Anaconda\python.exe run.py >> logs\run.log 2>&1
echo ===== [%date% %time%] exit=%errorlevel% ===== >> logs\run.log
