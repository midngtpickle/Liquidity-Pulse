<#
.SYNOPSIS
    Registers the two Liquidity-Pulse data recorders as Windows scheduled tasks.

.DESCRIPTION
    Two signals in this project cannot be backtested from data the exchange will sell
    you, because nobody serves the history:

      * Order book depth   - exchanges do not serve historical order books at all.
      * Open interest and
        long/short ratios  - Binance caps /futures/data/* at 30 days, hard.

    The only way to have a year of either is to have spent a year writing it down.
    These tasks do the writing down. Until they have been running for a month or two
    there is nothing to test, which is why this is worth doing today rather than when
    the question becomes urgent.

    Both run as long-lived daemons under pythonw.exe, not as short tasks that fire on
    a timer. That is deliberate: a per-snapshot task would open and close a console
    window every five minutes on a machine you are trying to work on. pythonw has no
    console at all, so each recorder logs to a file under workspace/logs/ instead.

    Each task also carries a five-minute repeat trigger with MultipleInstances set to
    IgnoreNew. While the daemon is alive the repeat is ignored; if it ever dies, the
    next repeat restarts it. That is a watchdog in two settings and no extra code.

.NOTES
    Runs as the current user, "only when logged on". Running whether-or-not-logged-on
    would need your password stored in the task, which is not worth it for a market
    data recorder -- and means the recorders stop when you sign out. If you want them
    running on a locked machine, sign in and lock rather than signing out.

    No elevation required. Nothing here touches system settings; these are ordinary
    per-user scheduled tasks under \Liquidity-Pulse\.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_recorders.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\uninstall_recorders.ps1
#>

[CmdletBinding()]
param(
    [int]$PositioningIntervalSeconds = 300,
    [string]$TaskPath = '\Liquidity-Pulse\'
)

$ErrorActionPreference = 'Stop'

$Root    = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $Root 'venv\Scripts\pythonw.exe'
$LogDir  = Join-Path $Root 'workspace\logs'

Write-Host "Liquidity-Pulse recorder installation" -ForegroundColor Cyan
Write-Host "  project : $Root"

if (-not (Test-Path $PythonW)) {
    throw "pythonw.exe not found at $PythonW. Create the virtual environment first: python -m venv venv"
}
if (-not (Test-Path (Join-Path $Root 'src\ws_feed.py'))) {
    throw "src\ws_feed.py not found under $Root. Run this script from the repository."
}
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$User = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "  user    : $User (only when logged on; no password stored)"

# A daily trigger that repeats every five minutes for twenty-four hours. The more
# obvious -Once with an open-ended RepetitionDuration is rejected or silently
# truncated on some Windows builds; this form is accepted everywhere.
function New-WatchdogTrigger {
    $daily  = New-ScheduledTaskTrigger -Daily -At '00:00'
    $repeat = New-ScheduledTaskTrigger -Once -At '00:00' `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Hours 24)
    $daily.Repetition = $repeat.Repetition
    return $daily
}

function Install-Recorder {
    param(
        [string]$Name,
        [string]$Description,
        [string]$Arguments
    )

    $action = New-ScheduledTaskAction -Execute $PythonW -Argument $Arguments -WorkingDirectory $Root

    # StartWhenAvailable catches a missed window after sleep or a late boot. The
    # battery settings matter more than they look on a laptop: the defaults stop a
    # running task the moment the machine unplugs, which would punch silent holes in
    # the recording -- exactly what the gap markers exist to make visible.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)

    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

    $triggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $User),
        (New-WatchdogTrigger)
    )

    $existing = Get-ScheduledTask -TaskPath $TaskPath -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  replacing existing task $Name" -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $Name -Confirm:$false
    }

    Register-ScheduledTask -TaskPath $TaskPath -TaskName $Name `
        -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
        -Description $Description | Out-Null

    Write-Host "  registered $TaskPath$Name" -ForegroundColor Green
}

$depthLog = Join-Path $LogDir 'record_depth.log'
$posLog   = Join-Path $LogDir 'record_positioning.log'

Install-Recorder -Name 'Record Depth' `
    -Description ('Records BINANCE:BTCUSDT.P order book history to workspace/depth_history/. ' +
                  'Exchanges do not serve historical order books, so the depth imbalance signal ' +
                  'can only ever be tested against data recorded beforehand. ~12MB/day gzipped.') `
    -Arguments ('"{0}" --record --log "{1}"' -f (Join-Path $Root 'src\ws_feed.py'), $depthLog)

Install-Recorder -Name 'Record Positioning' `
    -Description ('Records open interest, funding and long/short ratios to ' +
                  'workspace/positioning_history/. Binance caps this history at 30 days, so ' +
                  'anything older than a month exists only if it was recorded at the time.') `
    -Arguments ('"{0}" --record --loop {1} --log "{2}"' -f `
                (Join-Path $Root 'src\positioning.py'), $PositioningIntervalSeconds, $posLog)

Write-Host ''
Write-Host 'Starting both now so recording begins without waiting for the next logon.' -ForegroundColor Cyan
Start-ScheduledTask -TaskPath $TaskPath -TaskName 'Record Depth'
Start-ScheduledTask -TaskPath $TaskPath -TaskName 'Record Positioning'

Start-Sleep -Seconds 6
Get-ScheduledTask -TaskPath $TaskPath | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    '{0,-22} {1,-10} last run {2}' -f $_.TaskName, $_.State, $info.LastRunTime
}

Write-Host ''
Write-Host 'Logs:' -ForegroundColor Cyan
Write-Host "  $depthLog"
Write-Host "  $posLog"
Write-Host 'Data:' -ForegroundColor Cyan
Write-Host ('  {0}' -f (Join-Path $Root 'workspace\depth_history'))
Write-Host ('  {0}' -f (Join-Path $Root 'workspace\positioning_history'))
Write-Host ''
Write-Host 'Remove with: powershell -ExecutionPolicy Bypass -File scripts\uninstall_recorders.ps1'
