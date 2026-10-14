Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
configDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
deploymentDir = fileSystem.GetParentFolderName(configDir)
repo = fileSystem.GetParentFolderName(deploymentDir)
config = fileSystem.BuildPath(configDir, "ecosystem.config.cjs")
command = "cmd.exe /c cd /d """ & repo & """ && pm2 startOrRestart """ & config & """"
shell.Run command, 0, False
