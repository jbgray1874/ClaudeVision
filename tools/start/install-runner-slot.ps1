<#
    Install, refresh or remove one more estimating runner on THIS desktop (SCRUM-183 phase 2).

        .\tools\start\install-runner-slot.ps1 -Slot 2
        .\tools\start\install-runner-slot.ps1 -Slot 2 -Remove

    WHAT A SLOT IS. A second (or third) runner process on the same machine, so two or three
    estimates run at once. Slot 1 is the machine's own runner (install-runner-task.ps1), in
    C:\ClaudeVision. Slot N runs in its own checkout of the SAME commit, C:\ClaudeVision-sN,
    made as a git worktree, because the engine writes its files into its own checkout's
    output folder and the runner collects a job's files from there: two runs in one checkout
    would collect each other's books.

    WHAT IT SHARES WITH SLOT 1:
      - the virtualenv (C:\ClaudeVision\.venv), so nothing is installed twice;
      - the keys: a slot's runner loads C:\ClaudeVision\.env when its own checkout has none,
        and the engine inherits them, so the keys live in one file only;
      - the price cache (cache\), as a junction, so one part keeps one researched price
        whichever slot priced it.

    HOW THE SLOTS SHARE SOLIDWORKS. In turn. One lock file per machine; the engine takes it
    around each model read and a run that finds SolidWorks in use waits for it, saying so in
    the portal every 5 minutes. A normal wait never changes the reader. Only a wait that
    reaches SDI_SW_TURN_WAIT_MINUTES (default 30) switches that run to the Document Manager,
    said in the portal and on its book (SDI_SW_TURN_TIMEOUT=none leaves the models unread
    instead). A second run is claimed only while the machine has the memory and CPU for it
    (SDI_SLOT_MIN_FREE_GB, SDI_SLOT_MAX_CPU_PCT). The service must allow the runs at once:
    SDI_MAX_CONCURRENT_RUNS in .env, then restart the services.

    NOT YET. Slot 2 stays off until the parallel-run acceptance checks pass (SCRUM-183).

    RUN AGAIN AFTER EVERY SYNC. It moves the slot's checkout to C:\ClaudeVision's HEAD and
    restarts the slot, so every slot runs the build the service runs.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [int]    $Slot = 2,
    [string] $Root = "",
    [string] $SlotRoot = "",
    [string] $Server = "",
    [switch] $Remove
)
$ErrorActionPreference = "Stop"

if ($Slot -lt 2) {
    throw "Slot 1 is this machine's own runner (install-runner-task.ps1). Use -Slot 2 or more."
}
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}
if (-not $SlotRoot) { $SlotRoot = "$Root-s$Slot" }
$TaskName = "SDI Estimating Runner s$Slot"
if (-not $Server) {
    $Server = (@($(if ($env:SDI_PORT) { "http://localhost:$($env:SDI_PORT)" }),
                 "http://localhost:8071", "http://localhost:8072") |
               Where-Object { $_ } | Select-Object -Unique) -join ","
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is needed to make the slot's checkout, and it is not on PATH."
}

Write-Host "Runner slot $Slot on $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host "  main checkout  $Root"
Write-Host "  slot checkout  $SlotRoot"
Write-Host "  task           $TaskName"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

if ($Remove) {
    if ($task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "  removed the task '$TaskName'" -ForegroundColor Yellow
    }
    # END THE SLOT'S RUNNER FIRST. Stopping the task leaves its pythonw running (the venv
    # launcher starts a child), and that process holds output\.runner.lock, so git could not
    # delete the checkout and stopped to ask (6 Nov 2026).
    $slotRunner = Join-Path $SlotRoot "tools\runner\sdi_estimate_runner.py"
    $ended = 0
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($slotRunner.ToLower()) } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  ended pid $($_.ProcessId) $($_.Name)"
            $ended++
        }
    if ($ended) { Start-Sleep -Seconds 2 }
    # THE SHARED PRICE CACHE IS A JUNCTION TO THE MAIN CHECKOUT'S. Unlink it first, with rmdir,
    # which removes the link and never the files behind it, so deleting the slot's checkout
    # cannot reach the cache every slot shares.
    $cacheLink = Join-Path $SlotRoot "cache"
    if ((Test-Path $cacheLink) -and ((Get-Item $cacheLink -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        cmd /c rmdir "$cacheLink" | Out-Null
        Write-Host "  unlinked the shared price cache from $SlotRoot"
    }
    if (Test-Path $SlotRoot) {
        git -C "$Root" worktree remove --force "$SlotRoot"
        Write-Host "  removed the slot checkout $SlotRoot" -ForegroundColor Yellow
    }
    exit 0
}

# THE SAME COMMIT AS THE MAIN CHECKOUT, ALWAYS.
$head = "$(git -C "$Root" rev-parse HEAD)".Trim()
if (-not $head) { throw "Could not read HEAD of $Root" }
if (-not (Test-Path (Join-Path $SlotRoot ".git"))) {
    git -C "$Root" worktree add --detach "$SlotRoot" $head
    if ($LASTEXITCODE -ne 0) { throw "git worktree add failed for $SlotRoot" }
    Write-Host "  made the slot checkout at $($head.Substring(0, 8))"
} else {
    git -C "$SlotRoot" checkout --detach $head
    if ($LASTEXITCODE -ne 0) {
        throw ("The slot checkout $SlotRoot could not move to $($head.Substring(0, 8)). " +
               "It should hold no edits of its own: send the output above.")
    }
    Write-Host "  moved the slot checkout to $($head.Substring(0, 8))"
}

# ONE PRICE CACHE FOR EVERY SLOT, so one part keeps one researched price.
$cacheMain = Join-Path $Root "cache"
$cacheSlot = Join-Path $SlotRoot "cache"
if (-not (Test-Path $cacheMain)) { New-Item -ItemType Directory -Path $cacheMain | Out-Null }
if (-not (Test-Path $cacheSlot)) {
    New-Item -ItemType Junction -Path $cacheSlot -Target $cacheMain | Out-Null
    Write-Host "  shared the price cache: $cacheSlot -> $cacheMain"
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) { throw "No engine virtualenv at $python" }
$runner = Join-Path $SlotRoot "tools\runner\sdi_estimate_runner.py"
if (-not (Test-Path $runner)) { throw "No runner at $runner" }

# THE SAME TASK SHAPE AS SLOT 1 (install-runner-task.ps1): the logged-on user's session, at
# logon and every five minutes, restarted on failure, never time-limited.
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$runner`" --server `"$Server`" --engine-root `"$SlotRoot`" --engine-python `"$python`" --slot $Slot" `
    -WorkingDirectory $SlotRoot
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
try {
    $sweep = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5)
    $sweep.Repetition.Duration = ""
    $triggers += $sweep
} catch {
    Write-Host "  note: could not add the 5-minute restart sweep ($($_.Exception.Message))." -ForegroundColor Yellow
}
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
} catch {
    $triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    Write-Host "  installed with the logon trigger only." -ForegroundColor Yellow
}
Start-ScheduledTask -TaskName $TaskName
Write-Host "  started '$TaskName'" -ForegroundColor Green

# WHAT THE SERVICE ALLOWS. Without it the slot is up and never given a second job.
$envFile = Join-Path $Root ".env"
$cap = ""
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern "^\s*SDI_MAX_CONCURRENT_RUNS\s*=" | Select-Object -First 1
    if ($line) { $cap = ("$($line.Line)" -split "=", 2)[1].Trim() }
}
if (-not $cap -or [int]$cap -lt $Slot) {
    Write-Host ""
    Write-Host "  The service allows $(if ($cap) { $cap } else { 1 }) run(s) at once. For $Slot, add to $envFile :" -ForegroundColor Yellow
    Write-Host "      SDI_MAX_CONCURRENT_RUNS=$Slot" -ForegroundColor Yellow
    Write-Host "  then restart the services:" -ForegroundColor Yellow
    Write-Host "      .\tools\start\restart-service.ps1" -ForegroundColor Yellow
    Write-Host "      .\tools\start\restart-service.ps1 -Port 8071 -TaskName `"SDI Intelligence Service 8071`"" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Check it: .\tools\start\restart-runner.ps1 -Slot $Slot -Root `"$SlotRoot`" -TaskName `"$TaskName`"" -ForegroundColor Cyan
