Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = "C:\Users\bigma\Desktop\flolder\code\webcmdhack"
If fso.FolderExists(projectDir) Then
    WshShell.CurrentDirectory = projectDir
    cmd = Chr(34) & projectDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & projectDir & "\backend.py" & Chr(34)
    If fso.FileExists(projectDir & "\.venv\Scripts\pythonw.exe") Then
        WshShell.Run cmd, 0, False
    Else
        WshShell.Run "pythonw.exe " & Chr(34) & projectDir & "\backend.py" & Chr(34), 0, False
    End If
End If
