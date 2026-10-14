Option Explicit

Dim shell, fileSystem, configDir, appPath, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
configDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
appPath = fileSystem.BuildPath(configDir, "workspace-control.ps1")

If Not fileSystem.FileExists(appPath) Then
    shell.Popup "Control app was not found:" & vbCrLf & appPath, 0, "MCP Shared Workspace", 16
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & appPath & """"
shell.Run command, 0, False
