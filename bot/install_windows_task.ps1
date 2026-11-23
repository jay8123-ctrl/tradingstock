# One-Click Windows Task Scheduler Installer for TradingStock SW-04 Paper Bot
# Runs Monday-Friday at 22:20 local time (MYT, 10 min before US EST market open)

$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path
$BatPath = Join-Path $ProjectDir "bot\run_daily.bat"
$TaskName = "TradingStock_SW04_Daily"

Write-Host "Installing Windows Scheduled Task: $TaskName" -ForegroundColor Cyan
Write-Host "Target script: $BatPath"

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`"" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 22:20
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host ""
Write-Host "[SUCCESS] Scheduled task '$TaskName' created!" -ForegroundColor Green
Write-Host "Schedule : Every Monday-Friday at 22:20 (your PC local time)"
Write-Host "Log file : $ProjectDir\bot\daily_run.log"
Write-Host ""
Write-Host "To test it immediately, run:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "To remove it anytime, run  :  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
