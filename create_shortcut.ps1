$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\VoiceCapture.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\VoiceCapture.bat"
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.IconLocation = "$PSScriptRoot\icon.ico"
$Shortcut.Description = "Start VoiceCapture - Audio opname met transcriptie"
$Shortcut.Save()
Write-Host "Snelkoppeling aangemaakt op bureaublad!"
