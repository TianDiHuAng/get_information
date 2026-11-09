@echo off
rem 需要“以管理员身份运行”一次：注册成每天 08:00 / 20:00 的系统计划任务
rem 之后即使不登录也能跑（取决于任务设置）。装完可删除本文件。
chcp 65001 >nul
set TASK1=GetInfo_Daily_0800
set TASK2=GetInfo_Daily_2000
set TASK3=GetInfo_Web
set RUN=D:\AI\project\Get_Information\run_daily.bat
set WEB=D:\Anaconda\pythonw.exe D:\AI\project\Get_Information\serve.py

schtasks /Create /TN "%TASK1%" /TR "%RUN%" /SC DAILY /ST 08:00 /F
schtasks /Create /TN "%TASK2%" /TR "%RUN%" /SC DAILY /ST 20:00 /F
rem 可视化服务：每次登录自启（serve.py 单实例，重复启动无害）
schtasks /Create /TN "%TASK3%" /TR "%WEB%" /SC ONLOGON /F

echo.
echo 已创建（或已存在）：
schtasks /Query /TN "%TASK1%" /FO LIST | findstr /C:"TaskName" /C:"Next Run" /C:"下一次"
schtasks /Query /TN "%TASK2%" /FO LIST | findstr /C:"TaskName" /C:"Next Run" /C:"下一次"
echo.
echo 卸载： schtasks /Delete /TN "%TASK1%" /F  ^&  schtasks /Delete /TN "%TASK2%" /F  ^&  schtasks /Delete /TN "%TASK3%" /F
pause
