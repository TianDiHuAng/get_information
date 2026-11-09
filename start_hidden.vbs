' 静默启动 watchdog.bat（不弹黑窗）
Set ws = CreateObject("WScript.Shell")
ws.Run """D:\AI\project\Get_Information\watchdog.bat""", 0, False
