' 静默启动 watchdog.bat（不弹黑窗）
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run """" & root & "\watchdog.bat""", 0, False
