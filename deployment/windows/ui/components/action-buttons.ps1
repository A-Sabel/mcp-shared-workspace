$serverCard = New-Object System.Windows.Forms.GroupBox
$serverCard.Text = '  Server control  '
$serverCard.Location = New-Object System.Drawing.Point(366, 98)
$serverCard.Size = New-Object System.Drawing.Size(680, 126)
$serverCard.Anchor = 'Top,Left,Right'
$workspaceTab.Controls.Add($serverCard)

$serverHint = New-Object System.Windows.Forms.Label
$serverHint.Text = 'Manage the MCP server and public tunnel'
$serverHint.Location = New-Object System.Drawing.Point(14, 25)
$serverHint.Size = New-Object System.Drawing.Size(620, 19)
$serverCard.Controls.Add($serverHint)

$script:startButton = New-Object System.Windows.Forms.Button
$script:startButton.Text = 'Start server'
$script:startButton.Location = New-Object System.Drawing.Point(14, 58)
$script:startButton.Size = New-Object System.Drawing.Size(132, 34)
$script:startButton.Add_Click({ Start-Workspace })
$serverCard.Controls.Add($script:startButton)

$script:pauseButton = New-Object System.Windows.Forms.Button
$script:pauseButton.Text = 'Pause server'
$script:pauseButton.Location = New-Object System.Drawing.Point(154, 58)
$script:pauseButton.Size = New-Object System.Drawing.Size(132, 34)
$script:pauseButton.Enabled = $false
$script:pauseButton.Add_Click({ Stop-Workspace $false })
$serverCard.Controls.Add($script:pauseButton)

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = 'Exit application'
$exitButton.Location = New-Object System.Drawing.Point(294, 58)
$exitButton.Size = New-Object System.Drawing.Size(132, 34)
$exitButton.Add_Click({ $form.Close() })
$serverCard.Controls.Add($exitButton)
