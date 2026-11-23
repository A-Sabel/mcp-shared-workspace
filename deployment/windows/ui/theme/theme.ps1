function Set-WorkspaceTheme([System.Windows.Forms.Control]$Parent) {
    $light = ($script:currentTheme -eq 'Light')
    if ($light) {
        $script:palette = @{
            Background = [System.Drawing.Color]::FromArgb(216,220,227)
            Surface = [System.Drawing.Color]::FromArgb(226,230,236)
            Accent = [System.Drawing.Color]::FromArgb(218,0,55)
            Text = [System.Drawing.Color]::FromArgb(27,32,40)
            Muted = [System.Drawing.Color]::FromArgb(74,82,94)
            Input = [System.Drawing.Color]::FromArgb(236,239,243)
            Border = [System.Drawing.Color]::FromArgb(181,188,199)
            Success = [System.Drawing.Color]::FromArgb(28,122,72)
            Warning = [System.Drawing.Color]::FromArgb(138,90,0)
            Danger = [System.Drawing.Color]::FromArgb(180,35,60)
            Info = [System.Drawing.Color]::FromArgb(39,93,173)
        }
    } else {
        $script:palette = @{
            Background = [System.Drawing.Color]::FromArgb(20,21,24)
            Surface = [System.Drawing.Color]::FromArgb(34,36,41)
            Accent = [System.Drawing.Color]::FromArgb(218,0,55)
            Text = [System.Drawing.Color]::FromArgb(237,237,237)
            Muted = [System.Drawing.Color]::FromArgb(174,179,188)
            Input = [System.Drawing.Color]::FromArgb(25,27,31)
            Border = [System.Drawing.Color]::FromArgb(66,70,78)
            Success = [System.Drawing.Color]::FromArgb(100,210,135)
            Warning = [System.Drawing.Color]::FromArgb(235,185,85)
            Danger = [System.Drawing.Color]::FromArgb(255,115,135)
            Info = [System.Drawing.Color]::FromArgb(125,180,255)
        }
    }
    $form.BackColor = $script:palette.Background
    $form.ForeColor = $script:palette.Text
    foreach ($control in $Parent.Controls) {
        $control.ForeColor = $script:palette.Text
        if ($control -is [System.Windows.Forms.TabControl] -or $control -is [System.Windows.Forms.TabPage]) {
            $control.BackColor = $script:palette.Background
        } elseif ($control -is [System.Windows.Forms.GroupBox]) {
            $control.BackColor = $script:palette.Surface
            $control.ForeColor = $script:palette.Text
        } elseif ($control -is [System.Windows.Forms.Panel]) {
            $control.BackColor = $script:palette.Background
        } elseif ($control -is [System.Windows.Forms.Label]) {
            $control.BackColor = [System.Drawing.Color]::Transparent
            $control.ForeColor = $script:palette.Text
        } elseif ($control -is [System.Windows.Forms.Button]) {
            $control.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
            $control.FlatAppearance.BorderSize = 1
            $control.FlatAppearance.BorderColor = $script:palette.Border
            $control.BackColor = $script:palette.Surface
            $control.ForeColor = $script:palette.Text
            $control.Cursor = [System.Windows.Forms.Cursors]::Hand
            if ($control.Text -match 'Start server|Register folder|Refresh') {
                $control.BackColor = $script:palette.Accent
                $control.ForeColor = [System.Drawing.Color]::White
                $control.FlatAppearance.BorderSize = 0
            }
        } elseif ($control -is [System.Windows.Forms.TextBox] -or $control -is [System.Windows.Forms.ComboBox]) {
            $control.BackColor = $script:palette.Input
            $control.ForeColor = $script:palette.Text
        } elseif ($control -is [System.Windows.Forms.DataGridView]) {
            $control.BackgroundColor = $script:palette.Input
            $control.GridColor = $script:palette.Border
            $control.DefaultCellStyle.BackColor = $script:palette.Background
            $control.DefaultCellStyle.ForeColor = $script:palette.Text
            $control.DefaultCellStyle.SelectionBackColor = $script:palette.Accent
            $control.DefaultCellStyle.SelectionForeColor = [System.Drawing.Color]::White
            $control.AlternatingRowsDefaultCellStyle.BackColor = $script:palette.Surface
            $control.AlternatingRowsDefaultCellStyle.ForeColor = $script:palette.Text
            $control.ColumnHeadersDefaultCellStyle.BackColor = $script:palette.Surface
            $control.ColumnHeadersDefaultCellStyle.ForeColor = $script:palette.Text
            $control.BorderStyle = 'None'
        }
        if ($control.Controls.Count -gt 0) { Set-WorkspaceTheme $control }
    }
    if ($script:activity) {
        $script:activity.BackColor = $script:palette.Input
        $script:activity.ForeColor = $script:palette.Text
        $script:activity.SelectAll()
        $script:activity.SelectionColor = $script:palette.Text
        $script:activity.SelectionStart = $script:activity.TextLength
        $script:activity.SelectionLength = 0
    }
    foreach ($button in @($script:themeDark,$script:themeLight)) {
        if ($button) {
            $button.BackColor = $script:palette.Surface
            $button.ForeColor = $script:palette.Text
            $button.FlatAppearance.BorderColor = $script:palette.Border
        }
    }
    if ($script:currentTheme -eq 'Dark') {
        $script:themeDark.BackColor = $script:palette.Accent
        $script:themeDark.ForeColor = [System.Drawing.Color]::White
    } else {
        $script:themeLight.BackColor = $script:palette.Accent
        $script:themeLight.ForeColor = [System.Drawing.Color]::White
    }
    if ($script:tabs) { $script:tabs.Invalidate() }
    if (Get-Command Update-NavState -ErrorAction SilentlyContinue) { Update-NavState }
}
