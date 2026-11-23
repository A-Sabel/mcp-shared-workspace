$form = New-Object System.Windows.Forms.Form
$form.Text = 'MCP Shared Workspace'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(1080, 760)
$form.MinimumSize = New-Object System.Drawing.Size(760, 520)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$form.BackColor = [System.Drawing.Color]::FromArgb(20,21,24)
$form.ForeColor = [System.Drawing.Color]::FromArgb(237,237,237)

$root = New-Object System.Windows.Forms.Panel
$root.Dock = 'Fill'
$root.BackColor = $form.BackColor
$form.Controls.Add($root)

$tabs = New-Object System.Windows.Forms.TabControl
$script:tabs = $tabs
$tabs.Dock = 'Fill'
$tabs.Appearance = [System.Windows.Forms.TabAppearance]::Buttons
$tabs.SizeMode = [System.Windows.Forms.TabSizeMode]::Fixed
$tabs.ItemSize = New-Object System.Drawing.Size(1,1)
$tabs.Multiline = $false
$tabs.Padding = New-Object System.Drawing.Point(0,0)
$tabs.DrawMode = [System.Windows.Forms.TabDrawMode]::Normal
$workspaceTab = New-Object System.Windows.Forms.TabPage
$workspaceTab.Text = 'Workspace'
$workspaceTab.UseVisualStyleBackColor = $false
$usageTab = New-Object System.Windows.Forms.TabPage
$usageTab.Text = 'Usage'
$usageTab.UseVisualStyleBackColor = $false
[void]$tabs.TabPages.Add($workspaceTab)
[void]$tabs.TabPages.Add($usageTab)
$root.Controls.Add($tabs)

$nav = New-Object System.Windows.Forms.Panel
$nav.Dock = 'Top'
$nav.Height = 38
$nav.Padding = New-Object System.Windows.Forms.Padding(8,3,8,3)
$root.Controls.Add($nav)

$script:navWorkspace = New-Object System.Windows.Forms.Button
$script:navWorkspace.Text = 'Workspace'
$script:navWorkspace.Location = New-Object System.Drawing.Point(0,2)
$script:navWorkspace.Size = New-Object System.Drawing.Size(112,32)
$script:navWorkspace.FlatStyle = 'Flat'
$script:navWorkspace.FlatAppearance.BorderSize = 0
$script:navWorkspace.Add_Click({ $tabs.SelectedTab = $workspaceTab; Update-NavState })
$nav.Controls.Add($script:navWorkspace)
$script:navUsage = New-Object System.Windows.Forms.Button
$script:navUsage.Text = 'Usage'
$script:navUsage.Location = New-Object System.Drawing.Point(116,2)
$script:navUsage.Size = New-Object System.Drawing.Size(112,32)
$script:navUsage.FlatStyle = 'Flat'
$script:navUsage.FlatAppearance.BorderSize = 0
$script:navUsage.Add_Click({ $tabs.SelectedTab = $usageTab; Update-NavState })
$nav.Controls.Add($script:navUsage)

function Update-NavState {
    if (-not $script:palette) { return }
    foreach ($button in @($script:navWorkspace,$script:navUsage)) {
        $button.BackColor = $script:palette.Surface
        $button.ForeColor = $script:palette.Text
    }
    $selected = if ($tabs.SelectedTab -eq $usageTab) { $script:navUsage } else { $script:navWorkspace }
    $selected.BackColor = $script:palette.Accent
    $selected.ForeColor = [System.Drawing.Color]::White
}
$tabs.Add_SelectedIndexChanged({ Update-NavState })

$script:appHeader = New-Object System.Windows.Forms.Panel
$script:appHeader.Dock = 'Top'
$script:appHeader.Height = 70
$script:appHeader.Padding = New-Object System.Windows.Forms.Padding(18,6,18,5)
$root.Controls.Add($script:appHeader)

. (Join-Path $PSScriptRoot 'pages\workspace-page.ps1')
. (Join-Path $PSScriptRoot 'pages\usage-page.ps1')

$brand = New-Object System.Windows.Forms.Label
$brand.Text = 'MCP Shared Workspace'
$brand.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
$brand.Location = New-Object System.Drawing.Point(18,7)
$brand.Size = New-Object System.Drawing.Size(430,27)
$script:appHeader.Controls.Add($brand)
$tagline = New-Object System.Windows.Forms.Label
$tagline.Text = 'Local MCP Server & Project Workspace'
$tagline.Location = New-Object System.Drawing.Point(20,36)
$tagline.Size = New-Object System.Drawing.Size(430,20)
$script:appHeader.Controls.Add($tagline)

$appearanceLabel = New-Object System.Windows.Forms.Label
$appearanceLabel.Text = 'Appearance'
$appearanceLabel.TextAlign = 'MiddleRight'
$appearanceLabel.Location = New-Object System.Drawing.Point(760,19)
$appearanceLabel.Size = New-Object System.Drawing.Size(86,25)
$appearanceLabel.Anchor = 'Top,Right'
$script:appHeader.Controls.Add($appearanceLabel)

$script:themeDark = New-Object System.Windows.Forms.Button
$script:themeDark.Text = 'Dark'
$script:themeDark.Location = New-Object System.Drawing.Point(854,16)
$script:themeDark.Size = New-Object System.Drawing.Size(62,30)
$script:themeDark.Anchor = 'Top,Right'
$script:themeDark.FlatStyle = 'Flat'
$script:themeDark.FlatAppearance.BorderSize = 1
$script:appHeader.Controls.Add($script:themeDark)
$script:themeLight = New-Object System.Windows.Forms.Button
$script:themeLight.Text = 'Light'
$script:themeLight.Location = New-Object System.Drawing.Point(916,16)
$script:themeLight.Size = New-Object System.Drawing.Size(62,30)
$script:themeLight.Anchor = 'Top,Right'
$script:themeLight.FlatStyle = 'Flat'
$script:themeLight.FlatAppearance.BorderSize = 1
$script:appHeader.Controls.Add($script:themeLight)

. (Join-Path $PSScriptRoot 'theme\theme.ps1')
$settingsPath = Join-Path $script:repo 'logs\ui-settings.json'
$initialTheme = 'Dark'
try {
    if (Test-Path -LiteralPath $settingsPath) {
        $saved = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        if ($saved.theme -in @('Dark','Light')) { $initialTheme = [string]$saved.theme }
    }
} catch { }
$script:currentTheme = $initialTheme
$script:themeDark.Add_Click({ $script:currentTheme = 'Dark'; Set-WorkspaceTheme $form; Save-WorkspaceTheme })
$script:themeLight.Add_Click({ $script:currentTheme = 'Light'; Set-WorkspaceTheme $form; Save-WorkspaceTheme })
function Save-WorkspaceTheme {
    try {
        $dir = Split-Path -Parent $settingsPath
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        [IO.File]::WriteAllText($settingsPath, (@{theme=$script:currentTheme} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    } catch { Add-Activity "Could not save appearance setting: $($_.Exception.Message)" }
}
Set-WorkspaceTheme $form
Update-NavState
