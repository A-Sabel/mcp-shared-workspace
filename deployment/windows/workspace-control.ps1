$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$script:envPath = Join-Path $script:repo '.env'
$script:pm2Config = Join-Path $PSScriptRoot 'ecosystem.config.cjs'
$script:appLog = Join-Path $script:repo 'logs\launcher.log'
$script:serverLog = Join-Path $script:repo 'logs\mcp-server.log'
$script:serverErrLog = Join-Path $script:repo 'logs\mcp-server-err.log'
$script:ngrokLog = Join-Path $script:repo 'logs\ngrok.log'
$script:workspaceRegistry = Join-Path $script:repo 'logs\workspaces.json'
$script:pythonExe = Join-Path $script:repo '.venv\Scripts\python.exe'
$script:hostname = $null
$script:configuredWorkspace = $null
$script:workspaces = [ordered]@{}
$script:selectedWorkspacePath = $null
$script:nodeExe = $null
$script:pm2Cli = $null
$script:ngrokExe = $null
$script:ngrokProcess = $null
$script:serverProcess = $null
$script:logPumps = @()
$script:running = $false
$script:starting = $false
$script:closing = $false
$script:closeRequested = $false
$script:pm2Cleaned = $false
$script:tunnelOnline = $false
$script:lastStatusCheckError = $null
$script:logOffsets = @{}

function Add-Activity([string]$Text) {
    $timestamp = Get-Date
    $category = 'INFO'
    $categoryColor = if ($script:palette) { $script:palette.Muted } else { [System.Drawing.Color]::Gray }
    if ($Text -match '(?i)\b(error|failed|exception|critical|traceback|could not|cannot|exited)\b') {
        $category = 'ERROR'
        if ($script:palette) { $categoryColor = $script:palette.Danger }
    } elseif ($Text -match '(?i)\b(warn|waiting|cancelled|timed out|timeout)\b') {
        $category = 'WARN'
        if ($script:palette) { $categoryColor = $script:palette.Warning }
    } elseif ($Text -match '(?i)\b(ngrok|tunnel)\b') {
        $category = 'TUNNEL'
        if ($script:palette) { $categoryColor = $script:palette.Info }
    } elseif ($Text -match '(?i)\b(ready|registered|listening|connected|online|paused|stopped|selected workspace|unregistered|copied)\b') {
        $category = 'OK'
        if ($script:palette) { $categoryColor = $script:palette.Success }
    } elseif ($Text -match '(?i)\b(server|MCP)\b') {
        $category = 'SERVER'
        if ($script:palette) { $categoryColor = $script:palette.Info }
    } elseif ($Text -match '(?i)\b(workspace|project)\b') {
        $category = 'WORKSPACE'
        if ($script:palette) { $categoryColor = $script:palette.Muted }
    }
    if ($script:activity -and -not $script:activity.IsDisposed) {
        $script:activity.SelectionStart = $script:activity.TextLength
        $script:activity.SelectionLength = 0
        $script:activity.SelectionColor = $categoryColor
        $script:activity.AppendText(('[{0}] [{1}]' -f $timestamp.ToString('HH:mm:ss'), $category.PadRight(9)))
        $script:activity.SelectionColor = $script:palette.Text
        $script:activity.AppendText((' {0}{1}' -f $Text, [Environment]::NewLine))
        if ($script:activity.Lines.Count -gt 500) {
            $removeAt = $script:activity.GetFirstCharIndexFromLine($script:activity.Lines.Count - 400)
            if ($removeAt -gt 0) {
                $script:activity.Select(0, $removeAt)
                $script:activity.SelectedText = ''
            }
        }
        $script:activity.SelectionStart = $script:activity.TextLength
        $script:activity.ScrollToCaret()
    }
    try {
        $dir = Split-Path -Parent $script:appLog
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        if ((Test-Path -LiteralPath $script:appLog) -and (Get-Item -LiteralPath $script:appLog).Length -ge 2MB) {
            Clear-LogFile $script:appLog
        }
        Add-Content -LiteralPath $script:appLog -Value ($timestamp.ToString('yyyy-MM-dd HH:mm:ss') + ' [' + $category + '] ' + $Text)
    } catch { }
}

function Clear-LogFile([string]$Path) {
    try {
        if (Test-Path -LiteralPath $Path) {
            [IO.File]::WriteAllText($Path, '', [Text.UTF8Encoding]::new($false))
        }
    } catch { }
}

function Get-Settings {
    if (-not (Test-Path -LiteralPath $script:envPath)) { throw '.env is missing.' }
    if (-not (Test-Path -LiteralPath $script:pythonExe)) { throw 'Virtual environment Python was not found.' }
    foreach ($line in Get-Content -LiteralPath $script:envPath) {
        if ($line -match '^\s*WORKSPACE_ROOT\s*=\s*(.*?)\s*$') {
            $script:configuredWorkspace = $Matches[1].Trim('"').Trim("'")
        }
        if ($line -match '^\s*PUBLIC_HOSTNAME\s*=\s*(.*?)\s*$') {
            $script:hostname = $Matches[1].Trim('"').Trim("'")
            break
        }
    }
    if (-not $script:configuredWorkspace -or -not (Test-Path -LiteralPath $script:configuredWorkspace -PathType Container)) {
        throw 'WORKSPACE_ROOT is missing or not an existing directory in .env.'
    }
    if ($script:hostname -notmatch '^[A-Za-z0-9.-]+$') { throw 'PUBLIC_HOSTNAME is missing or invalid in .env.' }
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { throw 'node.exe is not on PATH.' }
    $script:nodeExe = $node.Source
    $script:pm2Cli = Join-Path $env:APPDATA 'npm\node_modules\pm2\bin\pm2'
    if (-not (Test-Path -LiteralPath $script:pm2Cli)) { throw 'PM2 was not found in the npm global modules folder.' }
    $ngrok = Get-Command ngrok.exe -ErrorAction SilentlyContinue
    if (-not $ngrok) { throw 'ngrok.exe is not on PATH.' }
    $script:ngrokExe = $ngrok.Source
}

function Save-WorkspaceRegistry {
    $dir = Split-Path -Parent $script:workspaceRegistry
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $json = ConvertTo-Json -InputObject $script:workspaces -Depth 4
    $temp = $script:workspaceRegistry + '.tmp'
    [IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $script:workspaceRegistry -Force
}

function Update-WorkspaceChoices {
    if (-not $script:workspaceCombo) { return }
    $previous = [string]$script:workspaceCombo.SelectedItem
    $script:workspaceCombo.Items.Clear()
    foreach ($name in @($script:workspaces.Keys | Sort-Object)) { [void]$script:workspaceCombo.Items.Add($name) }
    if ($previous -and $script:workspaces.Contains($previous)) { $script:workspaceCombo.SelectedItem = $previous }
    elseif ($script:workspaces.Contains('default')) { $script:workspaceCombo.SelectedItem = 'default' }
    elseif ($script:workspaceCombo.Items.Count -gt 0) { $script:workspaceCombo.SelectedIndex = 0 }
    Update-SelectedWorkspace
}

function Update-SelectedWorkspace {
    $name = [string]$script:workspaceCombo.SelectedItem
    if ($name -and $script:workspaces.Contains($name)) {
        $script:selectedWorkspacePath = [IO.Path]::GetFullPath([string]$script:workspaces[$name])
        $script:workspacePathLabel.Text = $script:selectedWorkspacePath
    }
}

function Import-WorkspaceRegistry {
    $script:workspaces = [ordered]@{}
    if (Test-Path -LiteralPath $script:workspaceRegistry) {
        try {
            $loaded = Get-Content -LiteralPath $script:workspaceRegistry -Raw | ConvertFrom-Json
            foreach ($property in $loaded.PSObject.Properties) {
                if ($property.Value -is [string]) { $script:workspaces[$property.Name] = $property.Value }
            }
        } catch { throw 'Workspace registry is invalid. Repair logs\workspaces.json before using the selector.' }
    }
    $configured = [IO.Path]::GetFullPath($script:configuredWorkspace)
    $found = $false
    foreach ($path in $script:workspaces.Values) {
        if ([IO.Path]::GetFullPath([string]$path) -ieq $configured) { $found = $true; break }
    }
    if (-not $found) {
        $name = if (-not $script:workspaces.Contains('default')) { 'default' } else { 'configured-root' }
        $suffix = 2
        while ($script:workspaces.Contains($name)) { $name = "configured-root-$suffix"; $suffix++ }
        $script:workspaces[$name] = $configured
    }
    Update-WorkspaceChoices
}

function Register-WorkspaceFromForm {
    $name = $script:workspaceName.Text.Trim()
    $path = $script:workspacePathInput.Text.Trim()
    if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$') { throw 'Use a 1–64 character workspace name (letters, numbers, spaces, dots, underscores, or hyphens).' }
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'Choose an existing project directory.' }
    $path = [IO.Path]::GetFullPath($path)
    if ($script:workspaces.Contains($name) -and [IO.Path]::GetFullPath([string]$script:workspaces[$name]) -ine $path) {
        throw 'That name is already used by another workspace.'
    }
    foreach ($existingName in $script:workspaces.Keys) {
        if ($existingName -ne $name -and [IO.Path]::GetFullPath([string]$script:workspaces[$existingName]) -ieq $path) {
            throw "That directory is already registered as '$existingName'."
        }
    }
    $script:workspaces[$name] = $path
    Save-WorkspaceRegistry
    Update-WorkspaceChoices
    $script:workspaceCombo.SelectedItem = $name
    Add-Activity "Registered workspace '$name'."
}

function ConvertTo-QuotedArgument([string]$Value) { return '"' + $Value.Replace('"', '\"') + '"' }

# Returns the command's stdout. Callers that don't need it should use [void].
function Invoke-Pm2([string[]]$Pm2Args, [int]$Timeout = 30, [switch]$QuietError) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $script:nodeExe
    $psi.Arguments = (@((ConvertTo-QuotedArgument $script:pm2Cli)) + @($Pm2Args | ForEach-Object { ConvertTo-QuotedArgument $_ })) -join ' '
    $psi.WorkingDirectory = $script:repo
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit($Timeout * 1000)) {
        try { $proc.Kill() } catch { }
        throw "PM2 command timed out: $($Pm2Args -join ' ')"
    }
    $stderr = $errTask.Result.Trim() -replace '[\r\n]+', ' | '
    if ($proc.ExitCode -ne 0) {
        if ($stderr -and -not $QuietError) { Add-Activity "PM2 error: $stderr" }
        throw "PM2 command returned exit code $($proc.ExitCode)."
    }
    return $outTask.Result
}

function Stop-PreviousTunnel {
    try {
        $items = Get-CimInstance Win32_Process -Filter "Name = 'ngrok.exe'" -ErrorAction Stop
    } catch {
        Add-Activity "Could not inspect old ngrok processes: $($_.Exception.Message)"
        return
    }
    foreach ($item in $items) {
        if ($item.CommandLine -and $item.CommandLine.IndexOf($script:hostname, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            try {
                Add-Activity 'Stopping the previous ngrok process for this hostname.'
                Stop-Process -Id $item.ProcessId -Force -ErrorAction Stop
            } catch {
                Add-Activity "Could not stop ngrok PID $($item.ProcessId): $($_.Exception.Message)"
            }
        }
    }
}

# Removes the old PM2 entry for this app. 'pm2 kill' only runs if the delete
# succeeded (so the entry really existed) AND no other PM2 apps are running.
function Stop-ExistingPm2 {
    if ($script:pm2Cleaned) { return }
    $script:pm2Cleaned = $true
    $removed = $false
    try {
        Add-Activity 'Checking for a previous PM2-managed server.'
        [void](Invoke-Pm2 @('delete', 'mcp-workspace') 20 -QuietError)
        $removed = $true
        Add-Activity 'Removed the previous PM2 entry for mcp-workspace.'
    } catch { }
    if (-not $removed) { return }
    try {
        $out = Invoke-Pm2 @('jlist') 20 -QuietError
        $last = @($out -split '\r?\n' | Where-Object { $_.Trim() }) | Select-Object -Last 1
        if ($last -and $last.Trim() -eq '[]') {
            [void](Invoke-Pm2 @('kill') 20 -QuietError)
            Add-Activity 'No other PM2 apps were running; stopped the PM2 daemon.'
        } else {
            Add-Activity 'Other PM2 apps are running; leaving the PM2 daemon alone.'
        }
    } catch { }
}

function Stop-ProcessTree([int]$RootPid) {
    try {
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        $descendants = New-Object 'System.Collections.Generic.List[int]'
        $frontier = New-Object 'System.Collections.Generic.Queue[int]'
        $frontier.Enqueue($RootPid)
        while ($frontier.Count -gt 0) {
            $parentId = $frontier.Dequeue()
            foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $parentId }) {
                $descendants.Add([int]$child.ProcessId)
                $frontier.Enqueue([int]$child.ProcessId)
            }
        }
        for ($i = $descendants.Count - 1; $i -ge 0; $i--) {
            Stop-Process -Id $descendants[$i] -Force -ErrorAction SilentlyContinue
        }
    } catch { Add-Activity "Could not enumerate MCP child processes: $($_.Exception.Message)" }
    Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Stop-OrphanedWorkspaceServer {
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) { return }
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($listener in $listeners) {
        $process = $processes | Where-Object { $_.ProcessId -eq $listener.OwningProcess } | Select-Object -First 1
        if (-not $process -or $process.CommandLine -notmatch '(?i)-m\s+server\.http_runner') {
            throw "Port 8000 is in use by an unrecognized process (PID $($listener.OwningProcess)); it was left running."
        }
        $parent = $processes | Where-Object { $_.ProcessId -eq $process.ParentProcessId } | Select-Object -First 1
        if ($process.ExecutablePath -ieq $script:pythonExe) { $rootPid = [int]$process.ProcessId }
        elseif ($parent -and $parent.ExecutablePath -ieq $script:pythonExe -and $parent.CommandLine -match '(?i)-m\s+server\.http_runner') { $rootPid = [int]$parent.ProcessId }
        elseif ($process.ExecutablePath -match '(?i)\\Python\d+\\python\.exe$') { $rootPid = [int]$process.ProcessId }
        else { throw "Port 8000 is held by a Python MCP process whose parent could not be matched to this workspace (PID $($listener.OwningProcess)); it was left running." }
        Add-Activity "Stopping an orphaned MCP server process tree (PID $rootPid)."
        Stop-ProcessTree $rootPid
    }
}

# ---- Log pumps: pure .NET stream copy, no scriptblocks on thread-pool threads ----

function Start-LogPump([IO.Stream]$Source, [string]$Path) {
    try {
        $dir = Split-Path -Parent $Path
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        # bufferSize 1 = unbuffered, so the log is readable while the server runs
        $fs = [IO.FileStream]::new($Path, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite, 1)
        $task = $Source.CopyToAsync($fs)
        $script:logPumps += ,@{ Stream = $fs; Task = $task }
    } catch {
        Add-Activity "Could not open $Path for server output: $($_.Exception.Message)"
        # Still drain the pipe so the server can never block on a full buffer.
        try { $script:logPumps += ,@{ Stream = $null; Task = $Source.CopyToAsync([IO.Stream]::Null) } } catch { }
    }
}

function Stop-LogPumps {
    foreach ($pump in @($script:logPumps)) {
        try { [void]$pump.Task.Wait(1500) } catch { }
        try { if ($pump.Stream) { $pump.Stream.Dispose() } } catch { }
    }
    $script:logPumps = @()
}

function Set-LogCursor([string]$Path) {
    try { $script:logOffsets[$Path] = if (Test-Path -LiteralPath $Path) { (Get-Item -LiteralPath $Path).Length } else { 0 } }
    catch { $script:logOffsets[$Path] = 0 }
}

function Write-OperationalLogsToActivity {
    $sources = @(
        @{ Path = $script:serverLog; Kind = 'server' },
        @{ Path = $script:serverErrLog; Kind = 'server error' },
        @{ Path = $script:ngrokLog; Kind = 'ngrok' }
    )
    foreach ($source in $sources) {
        $path = $source.Path
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            $stream = [IO.FileStream]::new($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            $offset = [int64]$script:logOffsets[$path]
            if ($offset -gt $stream.Length) { $offset = 0 }
            $stream.Position = $offset
            $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 1024, $true)
            $lines = New-Object 'System.Collections.Generic.List[string]'
            while (-not $reader.EndOfStream) { $lines.Add($reader.ReadLine()) }
            $script:logOffsets[$path] = $stream.Position
            $reader.Dispose()
            $stream.Dispose()
            foreach ($line in $lines) {
                $important = if ($source.Kind -eq 'ngrok') {
                    $line -match 'lvl=(warn|eror|crit)|ERR_NGROK'
                } elseif ($source.Kind -eq 'server error') {
                    $line -match '(?i)\b(error|exception|traceback|critical|failed)\b'
                } else {
                    $line -match 'Application startup complete|Uvicorn running|" [45]\d\d '
                }
                if ($important) { Add-Activity ("{0}: {1}" -f $source.Kind, $line) }
            }
        } catch { }
    }
}

function Stop-ManagedServer {
    if ($script:serverProcess) {
        try {
            Stop-ProcessTree $script:serverProcess.Id
            [void]$script:serverProcess.WaitForExit(3000)
        } catch { Add-Activity "MCP server stop: $($_.Exception.Message)" }
        Stop-LogPumps
        $script:serverProcess.Dispose()
        $script:serverProcess = $null
    } else {
        Stop-LogPumps
    }
}

function Stop-NgrokProcess {
    if ($script:ngrokProcess) {
        try {
            if (-not $script:ngrokProcess.HasExited) {
                $script:ngrokProcess.Kill()
                [void]$script:ngrokProcess.WaitForExit(3000)
            }
        } catch { Add-Activity "ngrok stop: $($_.Exception.Message)" }
        $script:ngrokProcess.Dispose()
        $script:ngrokProcess = $null
    }
}

# Surfaces the most recent error lines from ngrok's own log file.
function Write-NgrokFailure {
    try {
        if (Test-Path -LiteralPath $script:ngrokLog) {
            $hits = @(Get-Content -LiteralPath $script:ngrokLog -Tail 80 |
                Where-Object { $_ -match 'lvl=(eror|crit)|ERR_NGROK' } |
                Select-Object -Last 4)
            foreach ($h in $hits) { Add-Activity ('ngrok: ' + $h) }
            if ($hits.Count -eq 0) { Add-Activity "No error lines found; see $($script:ngrokLog)" }
        } else {
            Add-Activity 'ngrok wrote no log file; run ngrok manually in a terminal to see its error.'
        }
    } catch { }
}

function Wait-ForServer {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        if ($script:closeRequested) { return $false }
        if ($script:serverProcess -and $script:serverProcess.HasExited) { return $false }
        $client = [Net.Sockets.TcpClient]::new()
        try {
            $async = $client.BeginConnect('127.0.0.1', 8000, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(350) -and $client.Connected) {
                $client.EndConnect($async)
                return $true
            }
        } catch { } finally { $client.Dispose() }
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 150
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Wait-ForPortFree([int]$TimeoutSeconds = 10) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ($script:closeRequested) { return $false }
        $client = [Net.Sockets.TcpClient]::new()
        $connected = $false
        try {
            $async = $client.BeginConnect('127.0.0.1', 8000, $null, $null)
            $connected = $async.AsyncWaitHandle.WaitOne(250) -and $client.Connected
            if ($connected) { $client.EndConnect($async) }
        } catch { $connected = $false }
        finally { $client.Dispose() }
        if (-not $connected) { return $true }
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Set-Status([bool]$IsRunning, [string]$Text) {
    $script:running = $IsRunning
    $script:status.Text = $Text
    $script:status.ForeColor = if ($IsRunning) { [System.Drawing.Color]::FromArgb(100, 210, 135) } else { [System.Drawing.Color]::FromArgb(235, 185, 85) }
    $script:startButton.Enabled = -not $IsRunning
    $script:pauseButton.Enabled = $IsRunning
    $script:reloadButton.Enabled = $IsRunning
    $script:switchButton.Enabled = $true
}

function Start-ManagedServerProcess {
    $serverStart = New-Object Diagnostics.ProcessStartInfo
    $serverStart.FileName = $script:pythonExe
    $serverStart.Arguments = '-u -m server.http_runner'
    $serverStart.WorkingDirectory = $script:repo
    $serverStart.UseShellExecute = $false
    $serverStart.CreateNoWindow = $true
    $serverStart.RedirectStandardOutput = $true
    $serverStart.RedirectStandardError = $true
    $serverStart.EnvironmentVariables['WORKSPACE_ROOT'] = $script:selectedWorkspacePath
    $script:serverProcess = [Diagnostics.Process]::new()
    $script:serverProcess.StartInfo = $serverStart
    [void]$script:serverProcess.Start()
    Start-LogPump $script:serverProcess.StandardOutput.BaseStream $script:serverLog
    Start-LogPump $script:serverProcess.StandardError.BaseStream $script:serverErrLog
}

function Restart-WorkspaceServer {
    if (-not $script:running -or $script:starting -or -not $script:serverProcess) { return }
    $script:starting = $true
    $script:reloadButton.Enabled = $false
    $script:pauseButton.Enabled = $false
    $script:status.Text = 'Reloading MCP server...'
    [System.Windows.Forms.Application]::DoEvents()
    try {
        Add-Activity 'Reloading MCP server to load saved server and tool changes.'
        Stop-ManagedServer
        if (-not (Wait-ForPortFree)) {
            throw 'Port 8000 is still in use. Close the process using that port, then reload again.'
        }
        if ($script:closeRequested) { return }

        Start-ManagedServerProcess
        if (-not (Wait-ForServer)) {
            if ($script:serverProcess -and $script:serverProcess.HasExited) {
                throw "MCP server exited during reload (code $($script:serverProcess.ExitCode)). See logs\mcp-server-err.log."
            }
            throw 'MCP server did not resume listening on port 8000. See logs\mcp-server-err.log.'
        }
        Add-Activity 'MCP server reloaded. The tunnel remains active; reconnect the MCP client if it does not refresh its tools.'
        Set-Status $true $(if ($script:tunnelOnline) { 'Online' } else { 'Waiting for ngrok...' })
    } catch {
        Add-Activity "RELOAD ERROR: $($_.Exception.Message)"
        Stop-NgrokProcess
        Stop-ManagedServer
        if ($script:hostname) { Stop-PreviousTunnel }
        $script:statusTimer.Stop()
        $script:tunnelOnline = $false
        Set-Status $false 'Stopped (reload failed)'
    } finally {
        $script:starting = $false
        if ($script:closeRequested -and -not $script:closing) { $form.Close() }
    }
}

function Start-Workspace {
    if ($script:running -or $script:starting) { return }
    $script:starting = $true
    $script:startButton.Enabled = $false
    $script:pauseButton.Enabled = $false
    $script:reloadButton.Enabled = $false
    $script:status.Text = 'Starting...'
    [System.Windows.Forms.Application]::DoEvents()
    try {
        Get-Settings
        Set-LogCursor $script:serverLog
        Set-LogCursor $script:serverErrLog
        Stop-PreviousTunnel
        Stop-ExistingPm2
        Stop-OrphanedWorkspaceServer
        $portFree = Wait-ForPortFree
        if ($script:closeRequested) { Add-Activity 'Start cancelled: the app is closing.'; return }
        if (-not $portFree) { throw 'Port 8000 is still in use after cleanup. Close the process using that port, then press Start again.' }

        Clear-LogFile $script:serverLog
        Clear-LogFile $script:serverErrLog
        Add-Activity "Starting the MCP server for workspace '$([string]$script:workspaceCombo.SelectedItem)'."
        Start-ManagedServerProcess

        $listening = Wait-ForServer
        if ($script:closeRequested) {
            Stop-ManagedServer
            Add-Activity 'Start cancelled: the app is closing.'
            return
        }
        if (-not $listening) {
            if ($script:serverProcess -and $script:serverProcess.HasExited) {
                throw "MCP server exited during startup (code $($script:serverProcess.ExitCode)). See logs\mcp-server-err.log."
            }
            throw 'MCP server did not start listening on port 8000. See logs\mcp-server-err.log.'
        }
        Add-Activity 'MCP server is listening on port 8000.'
        Add-Activity 'Server reload is manual; use Reload server after saving changes. New *_tools.py modules are auto-registered.'

        Clear-LogFile $script:ngrokLog
        Set-LogCursor $script:ngrokLog
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName = $script:ngrokExe
        $psi.Arguments = 'http 8000 --url ' + (ConvertTo-QuotedArgument ('https://' + $script:hostname)) +
            ' --log ' + (ConvertTo-QuotedArgument $script:ngrokLog) + ' --log-format logfmt'
        $psi.WorkingDirectory = $script:repo
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $script:ngrokProcess = [Diagnostics.Process]::new()
        $script:ngrokProcess.StartInfo = $psi
        [void]$script:ngrokProcess.Start()
        Add-Activity 'ngrok started. This control app now owns the tunnel.'
        $script:tunnelOnline = $false
        $script:lastStatusCheckError = $null
        Set-Status $true 'Starting ngrok...'
        $script:statusTimer.Start()
    } catch {
        Add-Activity "START ERROR: $($_.Exception.Message)"
        Stop-NgrokProcess
        Stop-ManagedServer
        Set-Status $false 'Stopped (start failed)'
    } finally {
        $script:starting = $false
        # Exit / X was pressed while starting: finish the close now that start has unwound.
        if ($script:closeRequested -and -not $script:closing) { $form.Close() }
    }
}

function Stop-Workspace([bool]$Exiting = $false) {
    $script:statusTimer.Stop()
    $script:tunnelOnline = $false
    Stop-NgrokProcess
    Stop-ManagedServer
    if ($script:hostname) { Stop-PreviousTunnel }
    if ($Exiting) {
        # PM2 cleanup is deliberately NOT done here; it only belongs to Start's migration step.
        Add-Activity 'Workspace stopped; control app exiting.'
    } else { Add-Activity 'Workspace paused. Press Start to reconnect your MCP client.' }
    Set-Status $false $(if ($Exiting) { 'Stopped' } else { 'Paused' })
}

function Switch-SelectedWorkspace {
    Update-SelectedWorkspace
    if (-not $script:selectedWorkspacePath -or -not (Test-Path -LiteralPath $script:selectedWorkspacePath -PathType Container)) {
        Add-Activity 'Choose a valid registered workspace first.'
        return
    }
    if ($script:running) {
        Add-Activity 'Switching workspace; restarting the MCP server and tunnel.'
        Stop-Workspace $false
        Start-Workspace
    } else {
        Add-Activity "Selected workspace '$([string]$script:workspaceCombo.SelectedItem)'. Press Start to launch it."
        $script:status.Text = 'Stopped - workspace selected'
    }
}

function Update-UsageView {
    if (-not $script:usageTotals -or $script:usageTotals.IsDisposed) { return }
    $totals = @{}
    $recordCount = 0
    $badCount = 0
    $logFiles = @($script:toolAuditLog) + @(1..5 | ForEach-Object { "$($script:toolAuditLog).$_" })
    foreach ($logFile in $logFiles) {
        if (-not (Test-Path -LiteralPath $logFile -PathType Leaf)) { continue }
        foreach ($line in [IO.File]::ReadLines($logFile)) {
            if (-not $line.Trim()) { continue }
            try {
                $record = ConvertFrom-Json -InputObject $line -ErrorAction Stop
                if (-not $record.tool) { throw 'Missing tool name.' }
                $name = [string]$record.tool
                if (-not $totals.ContainsKey($name)) {
                    $totals[$name] = [ordered]@{ Calls = 0; Success = 0; Failed = 0; Bytes = 0L; Chars = 0L; Chunks = 0; Lines = 0L; More = 0 }
                }
                $item = $totals[$name]
                $item.Calls++
                if ($record.success) { $item.Success++ } else { $item.Failed++ }
                if ($record.result) {
                    $item.Bytes += [long]$record.result.bytes
                    $item.Chars += [long]$record.result.chars
                    foreach ($range in @($record.result.read_ranges)) {
                        if (-not $range) { continue }
                        $item.Chunks++
                        if ($null -ne $range.start_line -and $null -ne $range.end_line) {
                            $item.Lines += [Math]::Max(0, [int]$range.end_line - [int]$range.start_line + 1)
                        }
                        if ($range.has_more) { $item.More++ }
                    }
                }
                $recordCount++
            } catch { $badCount++ }
        }
    }

    $script:usageTotals.Text = "Audit: $recordCount calls across current and rotated logs; $badCount malformed lines. Server output bytes are not model token counts."
    $script:usageGrid.Rows.Clear()
    foreach ($name in @($totals.Keys | Sort-Object)) {
        $item = $totals[$name]
        [void]$script:usageGrid.Rows.Add($name, $item.Calls, $item.Success, $item.Failed, $item.Bytes, $item.Chunks, $item.Lines, $item.More)
    }

    $paired = 0
    $evaluated = 0
    $baselineTokens = 0L
    $candidateTokens = 0L
    $baselinePass = $candidatePass = $baselineComplete = $candidateComplete = 0
    if (Test-Path -LiteralPath $script:benchmarkCsv -PathType Leaf) {
        foreach ($row in (Import-Csv -LiteralPath $script:benchmarkCsv)) {
            $bi = 0L; $bo = 0L; $ci = 0L; $co = 0L
            $hasCounts = [long]::TryParse([string]$row.baseline_input_tokens, [ref]$bi) -and
                [long]::TryParse([string]$row.baseline_output_tokens, [ref]$bo) -and
                [long]::TryParse([string]$row.candidate_input_tokens, [ref]$ci) -and
                [long]::TryParse([string]$row.candidate_output_tokens, [ref]$co)
            if (-not $hasCounts) { continue }
            $paired++
            $baselineTokens += $bi + $bo
            $candidateTokens += $ci + $co
            if ($row.baseline_pass -match '^(?i:yes|y|true|1|pass|no|n|false|0|fail)$' -and $row.baseline_complete -match '^(?i:yes|y|true|1|pass|no|n|false|0|fail)$' -and
                $row.candidate_pass -match '^(?i:yes|y|true|1|pass|no|n|false|0|fail)$' -and $row.candidate_complete -match '^(?i:yes|y|true|1|pass|no|n|false|0|fail)$') { $evaluated++ }
            if ($row.baseline_pass -match '^(?i:yes|y|true|1|pass)$') { $baselinePass++ }
            if ($row.candidate_pass -match '^(?i:yes|y|true|1|pass)$') { $candidatePass++ }
            if ($row.baseline_complete -match '^(?i:yes|y|true|1|pass)$') { $baselineComplete++ }
            if ($row.candidate_complete -match '^(?i:yes|y|true|1|pass)$') { $candidateComplete++ }
        }
    }
    $change = if ($baselineTokens -gt 0) { '{0:N1}% saved' -f (100.0 * ($baselineTokens - $candidateTokens) / $baselineTokens) } else { 'not available' }
    $script:benchmarkSummary.Text = "Benchmark: $paired paired tasks | $baselineTokens -> $candidateTokens tokens ($change) | pass $baselinePass -> $candidatePass | complete $baselineComplete -> $candidateComplete | fully rated $evaluated"
}

. (Join-Path $PSScriptRoot 'ui\main-form.ps1')

$script:statusTimer = New-Object System.Windows.Forms.Timer
$script:statusTimer.Interval = 5000
$script:statusTimer.Add_Tick({
    if ($script:serverProcess -and $script:serverProcess.HasExited) {
        Add-Activity "MCP server exited with code $($script:serverProcess.ExitCode). See logs\mcp-server-err.log."
        $script:statusTimer.Stop()
        Stop-NgrokProcess
        Stop-ManagedServer
        Set-Status $false 'Stopped (MCP server exited)'
        return
    }
    if ($script:ngrokProcess -and $script:ngrokProcess.HasExited) {
        Add-Activity "ngrok exited with code $($script:ngrokProcess.ExitCode)."
        $script:statusTimer.Stop()
        Write-NgrokFailure
        Stop-NgrokProcess
        Stop-ManagedServer
        Set-Status $false 'Stopped (ngrok exited)'
        return
    }
    try {
        $info = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 1
        $expectedUrl = ('https://' + $script:hostname).TrimEnd('/')
        $match = @($info.tunnels | Where-Object { ([string]$_.public_url).TrimEnd('/') -ieq $expectedUrl } | Select-Object -First 1)
        $script:lastStatusCheckError = $null
        $isOnline = $match.Count -gt 0
        if ($isOnline) {
            if (-not $script:tunnelOnline) { Add-Activity ('Tunnel connected: ' + $expectedUrl) }
            $script:tunnelOnline = $true
            Set-Status $true 'Online'
            $script:url.Text = 'MCP server URL: ' + $expectedUrl + '/mcp'
        } else {
            $script:tunnelOnline = $false
            $script:status.Text = 'Waiting for ngrok tunnel...'
        }
    } catch {
        # Keep a confirmed online state through a transient local API timeout.
        if ($script:tunnelOnline) {
            $script:status.Text = 'Online'
        } else {
            $script:status.Text = 'Waiting for ngrok...'
        }
        if ($script:lastStatusCheckError -ne $_.Exception.Message) {
            Add-Activity "Tunnel status check failed: $($_.Exception.Message)"
            $script:lastStatusCheckError = $_.Exception.Message
        }
    }
    Write-OperationalLogsToActivity
})

$form.Add_FormClosing({
    param($eventSource, $e)
    if ($script:starting) {
        # Don't tear things down mid-start; Start-Workspace aborts at its next check and closes the form.
        $e.Cancel = $true
        $script:closeRequested = $true
        return
    }
    if (-not $script:closing) {
        $script:closing = $true
        Stop-Workspace $true
    }
})

try {
    Get-Settings
    Import-WorkspaceRegistry
    Update-UsageView
    $script:url.Text = 'MCP server URL: https://' + $script:hostname + '/mcp'
    Add-Activity 'Ready. Select or register a project, then Start. Switching while running restarts the server and tunnel.'
} catch { Add-Activity "CONFIG ERROR: $($_.Exception.Message)" }

try {
    [void][System.Windows.Forms.Application]::Run($form)
} catch {
    Add-Activity "APP ERROR: $($_.Exception.Message)"
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'MCP Shared Workspace error', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
}
