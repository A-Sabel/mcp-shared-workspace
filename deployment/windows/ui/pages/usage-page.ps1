$auditPathSetting = [string]$env:LOG_PATH
if (-not $auditPathSetting) {
    foreach ($line in (Get-Content -LiteralPath $script:envPath -ErrorAction SilentlyContinue)) {
        if ($line -match '^\\s*LOG_PATH\\s*=\\s*(.*?)\\s*$') { $auditPathSetting = $Matches[1].Trim('"').Trim("'"); break }
    }
}
if (-not $auditPathSetting) { $auditPathSetting = 'logs/tool_calls.jsonl' }
$script:toolAuditLog = if ([IO.Path]::IsPathRooted($auditPathSetting)) { $auditPathSetting } else { Join-Path $script:repo $auditPathSetting }
$script:benchmarkCsv = Join-Path $script:repo 'benchmarks\\results.csv'

$usageHeading = New-Object System.Windows.Forms.Label
$usageHeading.Text = 'Tool usage and token efficiency'
$usageHeading.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
$usageTab.Controls.Add($usageHeading)

$script:usageTotals = New-Object System.Windows.Forms.Label
$script:usageTotals.AutoEllipsis = $true
$usageTab.Controls.Add($script:usageTotals)

$refreshUsage = New-Object System.Windows.Forms.Button
$refreshUsage.Text = 'Refresh'
$refreshUsage.Size = New-Object System.Drawing.Size(112, 32)
$usageTab.Controls.Add($refreshUsage)

$script:usageGrid = New-Object System.Windows.Forms.DataGridView
$script:usageGrid.Anchor = 'Top,Bottom,Left,Right'
$script:usageGrid.ReadOnly = $true
$script:usageGrid.AllowUserToAddRows = $false
$script:usageGrid.AllowUserToDeleteRows = $false
$script:usageGrid.AllowUserToResizeRows = $false
$script:usageGrid.RowHeadersVisible = $false
$script:usageGrid.AutoSizeColumnsMode = 'Fill'
$script:usageGrid.EnableHeadersVisualStyles = $false
$script:usageGrid.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:usageGrid.MultiSelect = $false
$script:usageGrid.RowTemplate.Height = 26
$script:usageGrid.ColumnHeadersHeight = 32
foreach ($column in @(@('Tool', 'Tool'), @('Calls', 'Calls'), @('Success', 'Success'), @('Failed', 'Failed'), @('Bytes', 'Result bytes'), @('Chunks', 'Read chunks'), @('Lines', 'Lines read'), @('More', 'Has more'))) {
    [void]$script:usageGrid.Columns.Add([string]$column[0], [string]$column[1])
}
$usageTab.Controls.Add($script:usageGrid)

$benchmarkCard = New-Object System.Windows.Forms.GroupBox
$benchmarkCard.Text = '  Benchmark summary  '
$benchmarkCard.Anchor = 'Bottom,Left,Right'
$usageTab.Controls.Add($benchmarkCard)
$script:benchmarkSummary = New-Object System.Windows.Forms.Label
$script:benchmarkSummary.AutoEllipsis = $true
$script:benchmarkSummary.Anchor = 'Top,Left,Right'
$benchmarkCard.Controls.Add($script:benchmarkSummary)
$benchmarkHint = New-Object System.Windows.Forms.Label
$benchmarkHint.Text = 'Add measured baseline/candidate token counts and quality ratings to benchmarks/results.csv, then refresh.'
$benchmarkHint.AutoEllipsis = $true
$benchmarkHint.Anchor = 'Top,Left,Right'
$benchmarkCard.Controls.Add($benchmarkHint)

$refreshUsage.Add_Click({ Update-UsageView })

function Set-UsagePageLayout {
    $layoutWidth = [int]$usageTab.ClientSize.Width
    $layoutHeight = [int]$usageTab.ClientSize.Height
    $layoutInset = [int]22
    $layoutBottomInset = [int]20
    $layoutCardHeight = [int]118
    $layoutCardTop = [Math]::Max(180, $layoutHeight - $layoutBottomInset - $layoutCardHeight)
    $layoutContentWidth = [Math]::Max(320, $layoutWidth - (2 * $layoutInset))

    $usageHeading.Location = New-Object System.Drawing.Point($layoutInset, 12)
    $usageHeading.Size = New-Object System.Drawing.Size($layoutContentWidth, 30)
    $script:usageTotals.Location = New-Object System.Drawing.Point($layoutInset, 48)
    $script:usageTotals.Size = New-Object System.Drawing.Size([Math]::Max(180, $layoutContentWidth - 132), 42)
    $refreshUsage.Location = New-Object System.Drawing.Point(($layoutWidth - $layoutInset - 112), 50)
    $script:usageGrid.Location = New-Object System.Drawing.Point($layoutInset, 100)
    $script:usageGrid.Size = New-Object System.Drawing.Size($layoutContentWidth, [Math]::Max(64, $layoutCardTop - 114))
    $benchmarkCard.Location = New-Object System.Drawing.Point($layoutInset, $layoutCardTop)
    $benchmarkCard.Size = New-Object System.Drawing.Size($layoutContentWidth, $layoutCardHeight)
    $script:benchmarkSummary.Location = New-Object System.Drawing.Point(16, 25)
    $script:benchmarkSummary.Size = New-Object System.Drawing.Size([Math]::Max(250, $layoutContentWidth - 34), 42)
    $benchmarkHint.Location = New-Object System.Drawing.Point(16, 76)
    $benchmarkHint.Size = New-Object System.Drawing.Size([Math]::Max(250, $layoutContentWidth - 34), 30)
    $usageTab.AutoScrollMinSize = New-Object System.Drawing.Size(0, ($layoutCardTop + $layoutCardHeight + $layoutBottomInset))
}

$usageTab.AutoScroll = $true
$usageTab.Add_Resize({ Set-UsagePageLayout })
Set-UsagePageLayout
