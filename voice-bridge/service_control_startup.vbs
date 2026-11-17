Option Explicit
Dim fso, shell, voice, pythonw, entry
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
voice = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(voice, "venv\Scripts\pythonw.exe")
entry = fso.BuildPath(voice, "service_control.py")
If Not fso.FileExists(pythonw) Or Not fso.FileExists(entry) Then
 WriteStartupError "Silent startup failed: Python or entry script is missing."
Else
 On Error Resume Next
 shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & entry & Chr(34) & " --autostart", 0, False
 If Err.Number <> 0 Then
  Err.Clear
  WriteStartupError "Silent startup failed: unable to launch the unified manager."
 End If
 On Error GoTo 0
End If
Sub WriteStartupError(message)
 Dim target, output
 target = voice & "\logs\service-control\startup-error.txt"
 ' Installation must pre-create this current-user-only protected file.
 ' Never create a fallback state file with an inherited broad DACL.
 If Not fso.FileExists(target) Then Exit Sub
 On Error Resume Next
 Set output = fso.OpenTextFile(target, 2, False, 0)
 If Err.Number = 0 Then
  output.WriteLine message
  output.Close
 End If
 Err.Clear
 On Error GoTo 0
End Sub
