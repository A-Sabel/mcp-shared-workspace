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
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Text
    if ($script:activity -and -not $script:activity.IsDisposed) {
        $script:activity.AppendText($line + [Environment]::NewLine)
        if ($script:activity.Lines.Count -gt 400) {
            $script:activity.Lines = @($script:activity.Lines | Select-Object -Last 400)
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
        Add-Content -LiteralPath $script:appLog -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Text)
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
                    $line -match 'started tunnel|lvl=(eror|crit)|ERR_NGROK'
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
    $script:switchButton.Enabled = $true
}

function Start-Workspace {
    if ($script:running -or $script:starting) { return }
    $script:starting = $true
    $script:startButton.Enabled = $false
    $script:pauseButton.Enabled = $false
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
    } else { Add-Activity 'Workspace paused. Press Start to reconnect Claude.' }
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

    $script:usageTotals.Text = "Audit: $recordCount calls across current and rotated logs; $badCount malformed lines. Server output bytes are not Claude token counts."
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

$form = New-Object System.Windows.Forms.Form
$form.Text = 'MCP Shared Workspace'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(900, 740)
$form.MinimumSize = New-Object System.Drawing.Size(760, 680)
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 34, 42)
$form.ForeColor = [System.Drawing.Color]::White
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Dock = 'Fill'
$workspaceTab = New-Object System.Windows.Forms.TabPage
$workspaceTab.Text = 'Workspace'
$workspaceTab.BackColor = $form.BackColor
$usageTab = New-Object System.Windows.Forms.TabPage
$usageTab.Text = 'Usage'
$usageTab.BackColor = $form.BackColor
[void]$tabs.TabPages.Add($workspaceTab)
[void]$tabs.TabPages.Add($usageTab)
$form.Controls.Add($tabs)

$heading = New-Object System.Windows.Forms.Label
$heading.Text = 'MCP Shared Workspace'
$heading.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 18)
$heading.Location = New-Object System.Drawing.Point(22, 18)
$heading.Size = New-Object System.Drawing.Size(500, 36)
$workspaceTab.Controls.Add($heading)

$script:status = New-Object System.Windows.Forms.Label
$script:status.Text = 'Stopped'
$script:status.Location = New-Object System.Drawing.Point(24, 62)
$script:status.Size = New-Object System.Drawing.Size(640, 24)
$script:status.ForeColor = [System.Drawing.Color]::FromArgb(235, 185, 85)
$workspaceTab.Controls.Add($script:status)

$script:url = New-Object System.Windows.Forms.Label
$script:url.Text = 'Claude connector URL: loading...'
$script:url.Location = New-Object System.Drawing.Point(24, 88)
$script:url.Size = New-Object System.Drawing.Size(640, 22)
$script:url.ForeColor = [System.Drawing.Color]::FromArgb(135, 190, 245)
$workspaceTab.Controls.Add($script:url)

$workspaceTitle = New-Object System.Windows.Forms.Label
$workspaceTitle.Text = 'Project workspace'
$workspaceTitle.Location = New-Object System.Drawing.Point(24, 116)
$workspaceTitle.Size = New-Object System.Drawing.Size(180, 22)
$workspaceTab.Controls.Add($workspaceTitle)

$script:workspaceCombo = New-Object System.Windows.Forms.ComboBox
$script:workspaceCombo.DropDownStyle = 'DropDownList'
$script:workspaceCombo.Location = New-Object System.Drawing.Point(24, 140)
$script:workspaceCombo.Size = New-Object System.Drawing.Size(350, 28)
$script:workspaceCombo.Add_SelectedIndexChanged({ Update-SelectedWorkspace })
$workspaceTab.Controls.Add($script:workspaceCombo)

$script:switchButton = New-Object System.Windows.Forms.Button
$script:switchButton.Text = 'Switch workspace'
$script:switchButton.Location = New-Object System.Drawing.Point(390, 138)
$script:switchButton.Size = New-Object System.Drawing.Size(150, 32)
$script:switchButton.Add_Click({ Switch-SelectedWorkspace })
$workspaceTab.Controls.Add($script:switchButton)

$script:workspacePathLabel = New-Object System.Windows.Forms.Label
$script:workspacePathLabel.Location = New-Object System.Drawing.Point(24, 171)
$script:workspacePathLabel.Size = New-Object System.Drawing.Size(640, 20)
$script:workspacePathLabel.ForeColor = [System.Drawing.Color]::FromArgb(155, 165, 180)
$workspaceTab.Controls.Add($script:workspacePathLabel)

$nameLabel = New-Object System.Windows.Forms.Label
$nameLabel.Text = 'Name'
$nameLabel.Location = New-Object System.Drawing.Point(24, 194)
$nameLabel.Size = New-Object System.Drawing.Size(170, 20)
$workspaceTab.Controls.Add($nameLabel)
$script:workspaceName = New-Object System.Windows.Forms.TextBox
$script:workspaceName.Location = New-Object System.Drawing.Point(24, 214)
$script:workspaceName.Size = New-Object System.Drawing.Size(170, 26)
$workspaceTab.Controls.Add($script:workspaceName)

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = 'Project folder'
$pathLabel.Location = New-Object System.Drawing.Point(204, 194)
$pathLabel.Size = New-Object System.Drawing.Size(350, 20)
$workspaceTab.Controls.Add($pathLabel)
$script:workspacePathInput = New-Object System.Windows.Forms.TextBox
$script:workspacePathInput.Location = New-Object System.Drawing.Point(204, 214)
$script:workspacePathInput.Size = New-Object System.Drawing.Size(350, 26)
$workspaceTab.Controls.Add($script:workspacePathInput)

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = 'Browse...'
$browseButton.Location = New-Object System.Drawing.Point(564, 212)
$browseButton.Size = New-Object System.Drawing.Size(100, 30)
$browseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $script:workspacePathInput.Text = $dialog.SelectedPath }
    $dialog.Dispose()
})
$workspaceTab.Controls.Add($browseButton)

$registerButton = New-Object System.Windows.Forms.Button
$registerButton.Text = 'Register folder'
$registerButton.Location = New-Object System.Drawing.Point(24, 246)
$registerButton.Size = New-Object System.Drawing.Size(130, 32)
$registerButton.Add_Click({
    try { Register-WorkspaceFromForm }
    catch { Add-Activity "REGISTER ERROR: $($_.Exception.Message)" }
})
$workspaceTab.Controls.Add($registerButton)

$script:startButton = New-Object System.Windows.Forms.Button
$script:startButton.Text = 'Start'
$script:startButton.Location = New-Object System.Drawing.Point(24, 290)
$script:startButton.Size = New-Object System.Drawing.Size(110, 38)
$script:startButton.Add_Click({ Start-Workspace })
$workspaceTab.Controls.Add($script:startButton)

$script:pauseButton = New-Object System.Windows.Forms.Button
$script:pauseButton.Text = 'Pause'
$script:pauseButton.Location = New-Object System.Drawing.Point(146, 290)
$script:pauseButton.Size = New-Object System.Drawing.Size(110, 38)
$script:pauseButton.Enabled = $false
$script:pauseButton.Add_Click({ Stop-Workspace $false })
$workspaceTab.Controls.Add($script:pauseButton)

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = 'Exit'
$exitButton.Location = New-Object System.Drawing.Point(268, 290)
$exitButton.Size = New-Object System.Drawing.Size(110, 38)
$exitButton.Add_Click({ $form.Close() })
$workspaceTab.Controls.Add($exitButton)

$logTitle = New-Object System.Windows.Forms.Label
$logTitle.Text = 'Activity'
$logTitle.Location = New-Object System.Drawing.Point(24, 330)
$logTitle.Size = New-Object System.Drawing.Size(200, 24)
$workspaceTab.Controls.Add($logTitle)

$script:activity = New-Object System.Windows.Forms.TextBox
$script:activity.Multiline = $true
$script:activity.ReadOnly = $true
$script:activity.ScrollBars = 'Vertical'
$script:activity.BackColor = [System.Drawing.Color]::FromArgb(18, 21, 27)
$script:activity.ForeColor = [System.Drawing.Color]::FromArgb(220, 225, 232)
$script:activity.Font = New-Object System.Drawing.Font('Consolas', 9)
$script:activity.Anchor = 'Top,Bottom,Left,Right'
$script:activity.Location = New-Object System.Drawing.Point(24, 358)
$script:activity.Size = New-Object System.Drawing.Size(836, 320)
$workspaceTab.Controls.Add($script:activity)

$auditPathSetting = [string]$env:LOG_PATH
if (-not $auditPathSetting) {
    foreach ($line in (Get-Content -LiteralPath $script:envPath -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*LOG_PATH\s*=\s*(.*?)\s*$') { $auditPathSetting = $Matches[1].Trim('"').Trim("'"); break }
    }
}
if (-not $auditPathSetting) { $auditPathSetting = 'logs/tool_calls.jsonl' }
$script:toolAuditLog = if ([IO.Path]::IsPathRooted($auditPathSetting)) { $auditPathSetting } else { Join-Path $script:repo $auditPathSetting }
$script:benchmarkCsv = Join-Path $script:repo 'benchmarks\results.csv'
$usageHeading = New-Object System.Windows.Forms.Label
$usageHeading.Text = 'Tool usage and token efficiency'
$usageHeading.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
$usageHeading.Location = New-Object System.Drawing.Point(20, 20)
$usageHeading.Size = New-Object System.Drawing.Size(700, 32)
$usageTab.Controls.Add($usageHeading)

$script:usageTotals = New-Object System.Windows.Forms.Label
$script:usageTotals.Location = New-Object System.Drawing.Point(22, 60)
$script:usageTotals.Size = New-Object System.Drawing.Size(820, 42)
$script:usageTotals.ForeColor = [System.Drawing.Color]::FromArgb(190, 200, 214)
$usageTab.Controls.Add($script:usageTotals)

$refreshUsage = New-Object System.Windows.Forms.Button
$refreshUsage.Text = 'Refresh'
$refreshUsage.Location = New-Object System.Drawing.Point(22, 108)
$refreshUsage.Size = New-Object System.Drawing.Size(100, 32)
$usageTab.Controls.Add($refreshUsage)

$script:usageGrid = New-Object System.Windows.Forms.DataGridView
$script:usageGrid.Location = New-Object System.Drawing.Point(22, 152)
$script:usageGrid.Size = New-Object System.Drawing.Size(830, 300)
$script:usageGrid.Anchor = 'Top,Bottom,Left,Right'
$script:usageGrid.ReadOnly = $true
$script:usageGrid.AllowUserToAddRows = $false
$script:usageGrid.AllowUserToDeleteRows = $false
$script:usageGrid.AllowUserToResizeRows = $false
$script:usageGrid.RowHeadersVisible = $false
$script:usageGrid.AutoSizeColumnsMode = 'Fill'
$script:usageGrid.BackgroundColor = [System.Drawing.Color]::FromArgb(18, 21, 27)
$script:usageGrid.ForeColor = [System.Drawing.Color]::FromArgb(30, 34, 42)
$script:usageGrid.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(45, 52, 64)
$script:usageGrid.ColumnHeadersDefaultCellStyle.ForeColor = [System.Drawing.Color]::White
$script:usageGrid.EnableHeadersVisualStyles = $false
foreach ($column in @(@('Tool', 'Tool'), @('Calls', 'Calls'), @('Success', 'Success'), @('Failed', 'Failed'), @('Bytes', 'Result bytes'), @('Chunks', 'Read chunks'), @('Lines', 'Lines read'), @('More', 'Has more'))) {
    [void]$script:usageGrid.Columns.Add([string]$column[0], [string]$column[1])
}
$usageTab.Controls.Add($script:usageGrid)

$script:benchmarkSummary = New-Object System.Windows.Forms.Label
$script:benchmarkSummary.Location = New-Object System.Drawing.Point(22, 466)
$script:benchmarkSummary.Size = New-Object System.Drawing.Size(830, 70)
$script:benchmarkSummary.Anchor = 'Bottom,Left,Right'
$script:benchmarkSummary.ForeColor = [System.Drawing.Color]::FromArgb(190, 200, 214)
$usageTab.Controls.Add($script:benchmarkSummary)

$benchmarkHint = New-Object System.Windows.Forms.Label
$benchmarkHint.Text = 'Enter actual Claude input/output token counts and pass/completeness ratings in benchmarks/results.csv, then refresh.'
$benchmarkHint.Location = New-Object System.Drawing.Point(22, 540)
$benchmarkHint.Size = New-Object System.Drawing.Size(830, 42)
$benchmarkHint.Anchor = 'Bottom,Left,Right'
$benchmarkHint.ForeColor = [System.Drawing.Color]::FromArgb(145, 158, 178)
$usageTab.Controls.Add($benchmarkHint)
$refreshUsage.Add_Click({ Update-UsageView })
$tabs.Add_SelectedIndexChanged({ if ($tabs.SelectedTab -eq $usageTab) { Update-UsageView } })

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
            Set-Status $true ('Online - ' + $expectedUrl)
            $script:url.Text = 'Claude connector URL: ' + $expectedUrl + '/mcp'
        } else {
            $script:tunnelOnline = $false
            $script:status.Text = 'Waiting for ngrok tunnel...'
        }
    } catch {
        # Keep a confirmed online state through a transient local API timeout.
        if ($script:tunnelOnline) {
            $script:status.Text = 'Online - https://' + $script:hostname
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
    $script:url.Text = 'Claude connector URL: https://' + $script:hostname + '/mcp'
    Add-Activity 'Ready. Select or register a project, then Start. Switching while running restarts the server and tunnel.'
} catch { Add-Activity "CONFIG ERROR: $($_.Exception.Message)" }

try {
    [void][System.Windows.Forms.Application]::Run($form)
} catch {
    Add-Activity "APP ERROR: $($_.Exception.Message)"
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'MCP Shared Workspace error', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
}
