. (Join-Path $PSScriptRoot '..\components\header.ps1')
. (Join-Path $PSScriptRoot '..\components\workspace-selector.ps1')
. (Join-Path $PSScriptRoot '..\components\action-buttons.ps1')
. (Join-Path $PSScriptRoot '..\components\activity-log.ps1')

# Keep the overview and its two working areas aligned as the window changes
# size. The controls remain in their existing cards so their behavior and
# operational references stay intact.
function Set-WorkspacePageLayout {
    $pageWidth = $workspaceTab.ClientSize.Width
    $pageHeight = $workspaceTab.ClientSize.Height
    $layoutInset = [int]22
    $layoutGap = [int]18
    $layoutRightEdge = [Math]::Max($layoutInset, $pageWidth - $layoutInset)
    $layoutContentWidth = $layoutRightEdge - $layoutInset
    $layoutLeftWidth = [Math]::Max(330, [Math]::Min(390, [int]($layoutContentWidth * 0.36)))
    if ($layoutContentWidth -lt 780) { $layoutLeftWidth = [int]($layoutContentWidth * 0.42) }
    $layoutRightWidth = [Math]::Max(280, $layoutContentWidth - $layoutLeftWidth - $layoutGap)
    $layoutTop = [int]112
    $layoutCompact = ($pageWidth -lt 980 -or $pageHeight -lt 520)

    $heading.Location = New-Object System.Drawing.Point($layoutInset, 12)
    $heading.Size = New-Object System.Drawing.Size([Math]::Max(300, $layoutContentWidth - 100), 28)
    $script:status.Location = New-Object System.Drawing.Point(($layoutInset + 2), 43)
    $script:url.Location = New-Object System.Drawing.Point(($layoutInset + 2), 70)
    $copyUrlButton.Location = New-Object System.Drawing.Point(($layoutRightEdge - 92), 66)
    $script:url.Size = New-Object System.Drawing.Size([Math]::Max(180, $layoutRightEdge - $layoutInset - 110), 22)

    if ($layoutCompact) {
        $workspaceTab.AutoScroll = $true
        $layoutCompactButtonWidth = [Math]::Max(64, [int](($layoutContentWidth - 52) / 4))
        $serverCard.Location = New-Object System.Drawing.Point($layoutInset, $layoutTop)
        $serverCard.Size = New-Object System.Drawing.Size($layoutContentWidth, 126)
        $serverCard.Anchor = 'Top,Left,Right'
        $script:startButton.Location = New-Object System.Drawing.Point(14, 58)
        $script:startButton.Size = New-Object System.Drawing.Size($layoutCompactButtonWidth, 34)
        $script:pauseButton.Location = New-Object System.Drawing.Point((22 + $layoutCompactButtonWidth), 58)
        $script:pauseButton.Size = New-Object System.Drawing.Size($layoutCompactButtonWidth, 34)
        $script:reloadButton.Location = New-Object System.Drawing.Point((30 + (2 * $layoutCompactButtonWidth)), 58)
        $script:reloadButton.Size = New-Object System.Drawing.Size($layoutCompactButtonWidth, 34)
        $exitButton.Location = New-Object System.Drawing.Point((38 + (3 * $layoutCompactButtonWidth)), 58)
        $exitButton.Size = New-Object System.Drawing.Size($layoutCompactButtonWidth, 34)

        $workspaceCard.Location = New-Object System.Drawing.Point($layoutInset, ($layoutTop + 144))
        $workspaceCard.Size = New-Object System.Drawing.Size($layoutContentWidth, 430)
        $workspaceCard.Anchor = 'Top,Left,Right'
        $activityCard.Location = New-Object System.Drawing.Point($layoutInset, ($layoutTop + 590))
        $activityCard.Size = New-Object System.Drawing.Size($layoutContentWidth, 300)
        $activityCard.Anchor = 'Top,Left,Right'
        $workspaceTab.AutoScrollMinSize = New-Object System.Drawing.Size($pageWidth, ($layoutTop + 912))
    } else {
        $workspaceTab.AutoScroll = $false
        $layoutBottom = [Math]::Max($layoutTop + 420, $pageHeight - $layoutInset)
        $layoutCardHeight = $layoutBottom - $layoutTop
        $workspaceCard.Location = New-Object System.Drawing.Point($layoutInset, $layoutTop)
        $workspaceCard.Size = New-Object System.Drawing.Size($layoutLeftWidth, $layoutCardHeight)
        $workspaceCard.Anchor = 'Top,Left'
        $serverCard.Location = New-Object System.Drawing.Point(($layoutInset + $layoutLeftWidth + $layoutGap), $layoutTop)
        $serverCard.Size = New-Object System.Drawing.Size($layoutRightWidth, 126)
        $serverCard.Anchor = 'Top,Left,Right'
        $activityCard.Location = New-Object System.Drawing.Point(($layoutInset + $layoutLeftWidth + $layoutGap), ($layoutTop + 144))
        $activityCard.Size = New-Object System.Drawing.Size($layoutRightWidth, [Math]::Max(260, $layoutCardHeight - 144))
        $activityCard.Anchor = 'Top,Left,Right'
        $layoutStandardButtonWidth = [Math]::Min(132, [Math]::Max(96, [int](($layoutRightWidth - 60) / 4)))
        $script:startButton.Location = New-Object System.Drawing.Point(14, 58)
        $script:startButton.Size = New-Object System.Drawing.Size($layoutStandardButtonWidth, 34)
        $script:pauseButton.Location = New-Object System.Drawing.Point((22 + $layoutStandardButtonWidth), 58)
        $script:pauseButton.Size = New-Object System.Drawing.Size($layoutStandardButtonWidth, 34)
        $script:reloadButton.Location = New-Object System.Drawing.Point((30 + (2 * $layoutStandardButtonWidth)), 58)
        $script:reloadButton.Size = New-Object System.Drawing.Size($layoutStandardButtonWidth, 34)
        $exitButton.Location = New-Object System.Drawing.Point((38 + (3 * $layoutStandardButtonWidth)), 58)
        $exitButton.Size = New-Object System.Drawing.Size($layoutStandardButtonWidth, 34)
        $workspaceTab.AutoScrollMinSize = New-Object System.Drawing.Size(0, 0)
    }
    $script:activity.Location = New-Object System.Drawing.Point(10, 24)
    $script:activity.Size = New-Object System.Drawing.Size([Math]::Max(200, $activityCard.ClientSize.Width - 20), [Math]::Max(220, $activityCard.ClientSize.Height - 34))
}

$workspaceTab.Add_Resize({ Set-WorkspacePageLayout })
Set-WorkspacePageLayout
