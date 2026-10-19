# Run in a normal user PowerShell after installing Python 3.11+.
param([Parameter(Mandatory=$true)][string]$Wheel)
$ErrorActionPreference = 'Stop'
$venv = Join-Path $env:LOCALAPPDATA 'CodexChronicle\venv'
py -3 -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Python venv failed' }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install $Wheel
if ($LASTEXITCODE -ne 0) { throw 'Wheel installation failed' }
& $python -m chronicle.cli init
& $python -m chronicle.cli install
if ($LASTEXITCODE -ne 0) { throw 'Codex plugin installation failed' }
$action = New-ScheduledTaskAction -Execute $python -Argument '-m chronicle.cli agent'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'CodexChronicleAgent' -Action $action -Trigger $trigger -Settings $settings -Description 'Local offline Codex journal' | Out-Null
Write-Host 'Review and trust Chronicle hooks in Codex. Configure secrets locally; never paste them into chat.'
