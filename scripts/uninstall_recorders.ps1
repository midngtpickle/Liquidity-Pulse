<#
.SYNOPSIS
    Removes the Liquidity-Pulse recorder scheduled tasks.

.DESCRIPTION
    Stops and unregisters both recorders and removes the \Liquidity-Pulse\ task folder.

    Recorded data is left alone. workspace/depth_history/ and
    workspace/positioning_history/ hold the only copy of history the exchange will
    never serve again, so deleting them is a decision to make deliberately and by
    hand, not a side effect of uninstalling a scheduled task.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\uninstall_recorders.ps1
#>

[CmdletBinding()]
param(
    [string]$TaskPath = '\Liquidity-Pulse\'
)

$ErrorActionPreference = 'Stop'

$tasks = Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue
if (-not $tasks) {
    Write-Host "No tasks registered under $TaskPath - nothing to remove."
    return
}

foreach ($task in $tasks) {
    if ($task.State -eq 'Running') {
        Write-Host ('  stopping {0}' -f $task.TaskName)
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $task.TaskName
    }
    Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $task.TaskName -Confirm:$false
    Write-Host ('  removed {0}{1}' -f $TaskPath, $task.TaskName) -ForegroundColor Green
}

# Prune the now-empty folder so Task Scheduler is not left with a stray entry.
try {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $service.GetFolder('\').DeleteFolder($TaskPath.Trim('\'), 0)
    Write-Host ('  removed task folder {0}' -f $TaskPath) -ForegroundColor Green
} catch {
    Write-Host ('  (task folder {0} left in place: {1})' -f $TaskPath, $_.Exception.Message)
}

Write-Host ''
Write-Host 'Recorded data was NOT deleted. It is the only copy that exists:'
$root = Split-Path -Parent $PSScriptRoot
Write-Host ('  {0}' -f (Join-Path $root 'workspace\depth_history'))
Write-Host ('  {0}' -f (Join-Path $root 'workspace\positioning_history'))
