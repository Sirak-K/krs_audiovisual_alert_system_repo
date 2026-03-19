Option Explicit

Dim title
Dim body
Dim timeoutSeconds
Dim shell

title = "Codex svar klart"
body = "Agentens svar är klart."
timeoutSeconds = 2

If WScript.Arguments.Count >= 1 Then
    title = CStr(WScript.Arguments.Item(0))
End If

If WScript.Arguments.Count >= 2 Then
    body = CStr(WScript.Arguments.Item(1))
End If

If WScript.Arguments.Count >= 3 Then
    On Error Resume Next
    timeoutSeconds = CInt(WScript.Arguments.Item(2))
    If Err.Number <> 0 Then
        timeoutSeconds = 2
        Err.Clear
    End If
    On Error GoTo 0
End If

Set shell = CreateObject("WScript.Shell")
shell.Popup body, timeoutSeconds, title, 64 + 4096
