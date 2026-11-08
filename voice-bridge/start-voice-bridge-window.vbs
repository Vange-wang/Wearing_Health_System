Option Explicit
Dim fso, shell, base, pyw, gui, readme, cmd, item, rc, number, description, scriptPath, separator
On Error Resume Next
scriptPath = WScript.ScriptFullName
separator = InStrRev(scriptPath, "\")
base = Left(scriptPath, separator - 1)
pyw = base & "\venv\Scripts\pythonw.exe"
gui = base & "\service_control_window.py"
readme = base & "\README.md"
number = Err.Number : description = Err.Description : Err.Clear
On Error GoTo 0
If number <> 0 Or separator = 0 Then Fatal U("65E0 6CD5 51C6 5907 9879 76EE 8DEF 5F84 3002")
' Paths above need only the WSH script location, never the FSO object.
On Error Resume Next
Set fso = CreateObject("Scripting.FileSystemObject")
number = Err.Number : description = Err.Description : Err.Clear
On Error GoTo 0
If number <> 0 Then Fatal U("65E0 6CD5 5B9A 4F4D 9879 76EE 6587 4EF6 3002") & " " & CStr(number)
If Not ExistsFile(pyw) Then Fatal U("0050 0079 0074 0068 006F 006E 89E3 91CA 5668 7F3A 5931 3002")
If Not ExistsFile(gui) Then Fatal U("524D 53F0 63A7 5236 5165 53E3 811A 672C 7F3A 5931 3002")
If Not UsablePython(pyw) Then Fatal U("9879 76EE 0050 0079 0074 0068 006F 006E 89E3 91CA 5668 635F 574F 6216 4E0D 662F 53EF 542F 52A8 7A0B 5E8F 3002")
ValidateVenv
On Error Resume Next
Set shell = CreateObject("WScript.Shell")
number = Err.Number : description = Err.Description : Err.Clear
On Error GoTo 0
If number <> 0 Then Fatal U("65E0 6CD5 521B 5EFA 524D 53F0 542F 52A8 5BF9 8C61 3002") & " " & CStr(number) & " " & description
On Error Resume Next
shell.CurrentDirectory = base
number = Err.Number : description = Err.Description : Err.Clear
On Error GoTo 0
If number <> 0 Then Fatal U("65E0 6CD5 8BBE 7F6E 9879 76EE 5DE5 4F5C 76EE 5F55 3002") & " " & CStr(number) & " " & description
cmd = Quote(pyw) & " " & Quote(gui)
For Each item In WScript.Arguments
    If InStr(item, Chr(0)) > 0 Then Fatal U("524D 53F0 542F 52A8 53C2 6570 65E0 6548 3002")
    cmd = cmd & " " & Quote(CStr(item))
Next
' Wait is only this foreground GUI lifetime. No ensure/probe/recovery here.
On Error Resume Next
rc = shell.Run(cmd, 1, True)
number = Err.Number : description = Err.Description : Err.Clear
On Error GoTo 0
If number <> 0 Then Fatal U("65E0 6CD5 542F 52A8 8BED 97F3 670D 52A1 72B6 6001 7A97 53E3 3002") & " " & CStr(number) & " " & description
If rc <> 0 Then Fatal U("524D 53F0 7A97 53E3 8FD0 884C 5931 8D25 FF0C 9000 51FA 7801 FF1A") & " " & CStr(rc)
WScript.Quit 0

Function ExistsFile(path)
    Dim present, failure
    On Error Resume Next
    present = fso.FileExists(path)
    failure = Err.Number : Err.Clear
    On Error GoTo 0
    If failure <> 0 Then Fatal U("65E0 6CD5 67E5 8BE2 9879 76EE 6587 4EF6 3002") & " " & CStr(failure)
    ExistsFile = present
End Function

Function LocalAbsolute(value)
    Dim letter
    LocalAbsolute = False
    If Len(value) < 3 Then Exit Function
    letter = LCase(Left(value, 1))
    LocalAbsolute = letter >= "a" And letter <= "z" And Mid(value, 2, 2) = ":\"
End Function

Function LocalFileSize(path)
    Dim size, failure
    On Error Resume Next
    size = fso.GetFile(path).Size
    failure = Err.Number : Err.Clear
    On Error GoTo 0
    If failure <> 0 Then Fatal U("65E0 6CD5 67E5 8BE2 542F 52A8 6587 4EF6 957F 5EA6 3002") & " " & CStr(failure)
    LocalFileSize = size
End Function

Function ReadLocalText(path, prefix)
    Dim stream, value, failure, closeFailure
    Set stream = Nothing : value = "" : failure = 0
    On Error Resume Next
    Set stream = fso.OpenTextFile(path, 1, False, 0)
    failure = Err.Number : Err.Clear
    If failure = 0 Then
        If prefix = 0 Then
            value = stream.Read(8193)
        Else
            value = stream.Read(prefix)
        End If
        failure = Err.Number : Err.Clear
    End If
    If Not stream Is Nothing Then
        stream.Close
        closeFailure = Err.Number : Err.Clear
        If failure = 0 Then failure = closeFailure
    End If
    On Error GoTo 0
    If failure <> 0 Then Fatal U("65E0 6CD5 8BFB 53D6 6216 5173 95ED 542F 52A8 6587 4EF6 3002") & " " & CStr(failure)
    ReadLocalText = value
End Function

Function UsablePython(path)
    Dim size, magic
    UsablePython = False
    If Not LocalAbsolute(path) Then Fatal U("542F 52A8 89E3 91CA 5668 5FC5 987B 4F7F 7528 672C 5730 7EDD 5BF9 8DEF 5F84 3002")
    size = LocalFileSize(path)
    If size < 64 Or size > 67108864 Then Exit Function
    magic = ReadLocalText(path, 2)
    ' Only two ASCII DOS signature bytes. Never scan/hash/load the executable.
    UsablePython = magic = "MZ"
End Function

Sub ValidateVenv
    Dim cfg, text, line, position, home, homes, basePython, size
    cfg = base & "\venv\pyvenv.cfg"
    If Not ExistsFile(cfg) Then Fatal U("865A 62DF 73AF 5883 914D 7F6E 7F3A 5931 3002")
    size = LocalFileSize(cfg)
    If size = 0 Or size > 8192 Then Fatal U("865A 62DF 73AF 5883 914D 7F6E 4E3A 7A7A 6216 8D85 8FC7 68C0 67E5 4E0A 9650 3002")
    text = ReadLocalText(cfg, 0)
    If Len(text) > 8192 Then Fatal U("865A 62DF 73AF 5883 914D 7F6E 8D85 8FC7 6709 754C 8BFB 53D6 4E0A 9650 3002")
    home = "" : homes = 0
    For Each line In Split(Replace(text, vbCr, ""), vbLf)
        position = InStr(line, "=")
        If position > 0 Then
            If LCase(Trim(Left(line, position - 1))) = "home" Then
                home = Trim(Mid(line, position + 1)) : homes = homes + 1
            End If
        End If
    Next
    home = Replace(home, "/", "\")
    If homes <> 1 Or Not LocalAbsolute(home) Then Fatal U("865A 62DF 73AF 5883 914D 7F6E 65E0 6548 FF0C 9700 8981 552F 4E00 7684 672C 5730 0068 006F 006D 0065 76EE 5F55 3002")
    basePython = home
    If Right(basePython, 1) <> "\" Then basePython = basePython & "\"
    basePython = basePython & "pythonw.exe"
    If Not ExistsFile(basePython) Then Fatal U("865A 62DF 73AF 5883 7684 57FA 7840 0050 0079 0074 0068 006F 006E 89E3 91CA 5668 7F3A 5931 3002")
    If Not UsablePython(basePython) Then Fatal U("865A 62DF 73AF 5883 7684 57FA 7840 0050 0079 0074 0068 006F 006E 89E3 91CA 5668 635F 574F 6216 4E0D 53EF 7528 3002")
End Sub

Function Quote(value)
    Dim result, slashes, position, character
    result = Chr(34) : slashes = 0
    For position = 1 To Len(value)
        character = Mid(value, position, 1)
        If character = "\" Then
            slashes = slashes + 1
        ElseIf character = Chr(34) Then
            result = result & String(2 * slashes + 1, "\") & Chr(34)
            slashes = 0
        Else
            result = result & String(slashes, "\") & character
            slashes = 0
        End If
    Next
    Quote = result & String(2 * slashes, "\") & Chr(34)
End Function

Function U(value)
    Dim code, output
    output = ""
    For Each code In Split(value, " ")
        output = output & ChrW(CLng("&H" & code))
    Next
    U = output
End Function

Sub Fatal(reason)
    Dim text
    text = U("8BED 97F3 670D 52A1 542F 52A8 5931 8D25") & vbCrLf & reason & vbCrLf & U("89E3 91CA 5668 FF1A") & pyw & vbCrLf & U("5165 53E3 FF1A") & gui & vbCrLf & U("8BF7 67E5 770B 9879 76EE 6392 67E5 8BF4 660E FF1A") & readme
    ' Native blocking message: errors never disappear into background logs.
    MsgBox text, vbOKOnly Or vbCritical, U("8BED 97F3 670D 52A1 542F 52A8 5931 8D25")
    WScript.Quit 1
End Sub
