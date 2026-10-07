Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
repo = fileSystem.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /c cd /d """ & repo & """ && pm2 startOrRestart ecosystem.config.cjs"
shell.Run command, 0, False