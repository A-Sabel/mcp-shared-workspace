$workspaceCard = New-Object System.Windows.Forms.GroupBox
$workspaceCard.Text = '  Workspace management  '
$workspaceCard.Location = New-Object System.Drawing.Point(18, 98)
$workspaceCard.Size = New-Object System.Drawing.Size(330, 500)
$workspaceCard.Anchor = 'Top,Bottom,Left'
$workspaceTab.Controls.Add($workspaceCard)

$currentLabel = New-Object System.Windows.Forms.Label
$currentLabel.Text = 'Current workspace'
$currentLabel.Location = New-Object System.Drawing.Point(12, 25)
$currentLabel.Size = New-Object System.Drawing.Size(290, 18)
$workspaceCard.Controls.Add($currentLabel)
$script:workspaceCombo = New-Object System.Windows.Forms.ComboBox
$script:workspaceCombo.DropDownStyle = 'DropDownList'
$script:workspaceCombo.Location = New-Object System.Drawing.Point(12, 46)
$script:workspaceCombo.Size = New-Object System.Drawing.Size(292, 26)
$script:workspaceCombo.Anchor = 'Top,Left,Right'
$script:workspaceCombo.Add_SelectedIndexChanged({ Update-SelectedWorkspace })
$workspaceCard.Controls.Add($script:workspaceCombo)

$script:workspacePathLabel = New-Object System.Windows.Forms.Label
$script:workspacePathLabel.Location = New-Object System.Drawing.Point(12, 78)
$script:workspacePathLabel.Size = New-Object System.Drawing.Size(292, 36)
$script:workspacePathLabel.Anchor = 'Top,Left,Right'
$script:workspacePathLabel.AutoEllipsis = $true
$workspaceCard.Controls.Add($script:workspacePathLabel)

$script:switchButton = New-Object System.Windows.Forms.Button
$script:switchButton.Text = 'Switch workspace'
$script:switchButton.Location = New-Object System.Drawing.Point(12, 118)
$script:switchButton.Size = New-Object System.Drawing.Size(292, 32)
$script:switchButton.Anchor = 'Top,Left,Right'
$script:switchButton.Add_Click({ Switch-SelectedWorkspace })
$workspaceCard.Controls.Add($script:switchButton)

$registerHeading = New-Object System.Windows.Forms.Label
$registerHeading.Text = 'Register project folder'
$registerHeading.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9.5)
$registerHeading.Location = New-Object System.Drawing.Point(12, 166)
$registerHeading.Size = New-Object System.Drawing.Size(290, 20)
$workspaceCard.Controls.Add($registerHeading)

$nameLabel = New-Object System.Windows.Forms.Label
$nameLabel.Text = 'Workspace name'
$nameLabel.Location = New-Object System.Drawing.Point(12, 192)
$nameLabel.Size = New-Object System.Drawing.Size(290, 18)
$workspaceCard.Controls.Add($nameLabel)
$script:workspaceName = New-Object System.Windows.Forms.TextBox
$script:workspaceName.Location = New-Object System.Drawing.Point(12, 212)
$script:workspaceName.Size = New-Object System.Drawing.Size(292, 25)
$script:workspaceName.Anchor = 'Top,Left,Right'
$workspaceCard.Controls.Add($script:workspaceName)

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = 'Project folder'
$pathLabel.Location = New-Object System.Drawing.Point(12, 246)
$pathLabel.Size = New-Object System.Drawing.Size(290, 18)
$workspaceCard.Controls.Add($pathLabel)
$script:workspacePathInput = New-Object System.Windows.Forms.TextBox
$script:workspacePathInput.Location = New-Object System.Drawing.Point(12, 266)
$script:workspacePathInput.Size = New-Object System.Drawing.Size(292, 25)
$script:workspacePathInput.Anchor = 'Top,Left,Right'
$workspaceCard.Controls.Add($script:workspacePathInput)

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = 'Browse...'
$browseButton.Location = New-Object System.Drawing.Point(12, 300)
$browseButton.Size = New-Object System.Drawing.Size(292, 29)
$browseButton.Anchor = 'Top,Left,Right'
$browseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $script:workspacePathInput.Text = $dialog.SelectedPath }
    $dialog.Dispose()
})
$workspaceCard.Controls.Add($browseButton)

$registerButton = New-Object System.Windows.Forms.Button
$registerButton.Text = 'Register folder'
$registerButton.Location = New-Object System.Drawing.Point(12, 338)
$registerButton.Size = New-Object System.Drawing.Size(292, 32)
$registerButton.Anchor = 'Top,Left,Right'
$registerButton.Add_Click({
    try { Register-WorkspaceFromForm }
    catch { Add-Activity "REGISTER ERROR: $($_.Exception.Message)" }
})
$workspaceCard.Controls.Add($registerButton)

$script:deleteWorkspaceButton = New-Object System.Windows.Forms.Button
$script:deleteWorkspaceButton.Text = 'Unregister workspace'
$script:deleteWorkspaceButton.Location = New-Object System.Drawing.Point(12, 378)
$script:deleteWorkspaceButton.Size = New-Object System.Drawing.Size(292, 30)
$script:deleteWorkspaceButton.Anchor = 'Top,Left,Right'
$script:deleteWorkspaceButton.Add_Click({
    $name = [string]$script:workspaceCombo.SelectedItem
    if (-not $name) { return }
    if ($script:running) {
        [void][System.Windows.Forms.MessageBox]::Show('Pause the MCP server before removing a workspace.', 'Workspace is in use')
        return
    }
    if ([System.Windows.Forms.MessageBox]::Show("Unregister workspace '$name'? The folder and its files will not be deleted.", 'Confirm workspace removal', 'YesNo', 'Warning') -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    if ($name -eq 'default' -or $script:workspaces.Count -le 1) {
        [void][System.Windows.Forms.MessageBox]::Show('The default or last workspace cannot be removed.', 'Workspace protected')
        return
    }
    $script:workspaces.Remove($name)
    Save-WorkspaceRegistry
    Update-WorkspaceChoices
    Add-Activity "Unregistered workspace '$name'. Its files were kept."
})
$workspaceCard.Controls.Add($script:deleteWorkspaceButton)
