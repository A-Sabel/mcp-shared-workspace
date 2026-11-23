$activityCard = New-Object System.Windows.Forms.GroupBox
$activityCard.Text = '  Recent activity  '
$activityCard.Location = New-Object System.Drawing.Point(366, 238)
$activityCard.Size = New-Object System.Drawing.Size(680, 360)
$activityCard.Anchor = 'Top,Bottom,Left,Right'
$workspaceTab.Controls.Add($activityCard)

$script:activity = New-Object System.Windows.Forms.RichTextBox
$script:activity.Multiline = $true
$script:activity.ReadOnly = $true
$script:activity.WordWrap = $true
$script:activity.DetectUrls = $false
$script:activity.ScrollBars = 'Vertical'
$script:activity.BorderStyle = 'FixedSingle'
$script:activity.Font = New-Object System.Drawing.Font('Consolas', 9)
$script:activity.Anchor = 'Top,Left,Right'
$script:activity.Location = New-Object System.Drawing.Point(10, 24)
$script:activity.Size = New-Object System.Drawing.Size(654, 326)
$activityCard.Controls.Add($script:activity)
