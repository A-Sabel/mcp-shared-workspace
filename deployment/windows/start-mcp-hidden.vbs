Option Explicit

Dim shell, fileSystem, configDir, deploymentDir, repo, config, pythonExe
Dim logDir, logPath, npmBin, processEnv, command, exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
configDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
deploymentDir = fileSystem.GetParentFolderName(configDir)
repo = fileSystem.GetParentFolderName(deploymentDir)
config = fileSystem.BuildPath(configDir, "ecosystem.config.cjs")
pythonExe = fileSystem.BuildPath(repo, ".venv\Scripts\python.exe")
logDir = fileSystem.BuildPath(repo, "logs")
logPath = fileSystem.BuildPath(logDir, "launcher.log")

If Not fileSystem.FolderExists(logDir) Then
    fileSystem.CreateFolder logDir
End If

If Not fileSystem.FileExists(config) Then
    LogMessage "ERROR: PM2 configuration not found: " & config
    WScript.Quit 1
End If

If Not fileSystem.FileExists(pythonExe) Then
    LogMessage "ERROR: Virtual environment Python not found: " & pythonExe
    WScript.Quit 1
End If

' Add npm's standard per-user global bin directory when it exists. This helps
' Explorer-launched scripts find PM2 even if the current PATH is stale.
npmBin = shell.ExpandEnvironmentStrings("%APPDATA%") & "\npm"
If fileSystem.FileExists(fileSystem.BuildPath(npmBin, "pm2.cmd")) Then
    Set processEnv = shell.Environment("PROCESS")
    processEnv("PATH") = npmBin & ";" & processEnv("PATH")
End If

exitCode = shell.Run("cmd.exe /d /c where pm2.cmd >nul 2>&1", 0, True)
If exitCode <> 0 Then
    LogMessage "ERROR: pm2.cmd is not on PATH. Install PM2 globally or add its npm bin directory to PATH."
    WScript.Quit 1
End If

LogMessage "Starting PM2 app from " & config
command = "cmd.exe /d /c pm2.cmd startOrRestart """ & config & """ >> """ & logPath & """ 2>&1"
exitCode = shell.Run(command, 0, True)
LogMessage "PM2 command completed with exit code " & CStr(exitCode)
WScript.Quit exitCode

Sub LogMessage(message)
    Dim logFile
    Set logFile = fileSystem.OpenTextFile(logPath, 8, True)
    logFile.WriteLine Now & " " & message
    logFile.Close
End Sub
