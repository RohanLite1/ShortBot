Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = "C:\Users\bigma\Desktop\flolder\code\webcmdhack"
If fso.FolderExists(projectDir) Then
    WshShell.CurrentDirectory = projectDir
    WshShell.Run "pythonw.exe backend.py", 0, False
Else
    scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
    WshShell.CurrentDirectory = scriptDir
    WshShell.Run "pythonw.exe backend.py", 0, False
End If

