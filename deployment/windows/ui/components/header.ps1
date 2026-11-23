$heading = New-Object System.Windows.Forms.Label
$heading.Text = 'Workspace overview'
$heading.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 15)
$heading.Location = New-Object System.Drawing.Point(18, 12)
$heading.Size = New-Object System.Drawing.Size(480, 28)
$workspaceTab.Controls.Add($heading)

$script:status = New-Object System.Windows.Forms.Label
$script:status.Text = 'Stopped'
$script:status.Location = New-Object System.Drawing.Point(20, 43)
$script:status.Size = New-Object System.Drawing.Size(180, 20)
$script:status.ForeColor = [System.Drawing.Color]::FromArgb(235, 185, 85)
$workspaceTab.Controls.Add($script:status)

$script:url = New-Object System.Windows.Forms.Label
$script:url.Text = 'MCP server URL: loading...'
$script:url.Location = New-Object System.Drawing.Point(20, 66)
$script:url.Size = New-Object System.Drawing.Size(760, 20)
$script:url.Anchor = 'Top,Left,Right'
$workspaceTab.Controls.Add($script:url)

$copyUrlButton = New-Object System.Windows.Forms.Button
$copyUrlButton.Text = 'Copy URL'
$copyUrlButton.Location = New-Object System.Drawing.Point(790, 62)
$copyUrlButton.Size = New-Object System.Drawing.Size(88, 26)
$copyUrlButton.Anchor = 'Top,Right'
$copyUrlButton.Add_Click({
    try {
        $value = [string]$script:url.Text
        $value = $value -replace '^MCP server URL:\s*',''
        [System.Windows.Forms.Clipboard]::SetText($value)
        Add-Activity 'MCP server URL copied to clipboard.'
    } catch { Add-Activity "Could not copy URL: $($_.Exception.Message)" }
})
$workspaceTab.Controls.Add($copyUrlButton)
