<#
    Change one setting in the server's .env, from the LAPTOP, with the VPN on.

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Set-Setting.ps1 SDI_ESTIMATOR_OIDS "7e03a2b7-...,5acf6b37-..."

    Then restart, which it reminds you to do:

        .\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1 -Restart

    WHY THIS EXISTS RATHER THAN "open it in Notepad"
    Every setting handed over in this project has been a line of text in a chat
    window and an unspoken "you know what to do with that" - open a share, find
    the file, find the line, decide whether to replace or add one, save it
    without breaking the encoding, remember the restart. That is five chances
    to get it wrong on a file that is hand-edited over a share, is not in
    version control, and that every app reads once at startup.

    So: it takes a backup first, replaces the line if it is there and adds it
    if it is not, writes UTF-8 with no byte-order mark (a BOM on the first line
    makes the first setting unreadable, and the failure looks like the setting
    being absent), and says what it did.

    It NEVER prints a value. These are object IDs, keys and client secrets, and
    a console scrollback is shared in screenshots.

        -Show     list the setting NAMES present, and whether each has a value
        -Remove   take the setting out altogether
        -WhatIf   say what would change and write nothing
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Name,
    [Parameter(Position = 1)][string]$Value,
    [switch]$Remove,
    [switch]$Show,
    [switch]$WhatIf,
    [string]$Server = "10.0.0.5",
    # The one beside the service wins over the one at the repo root - see
    # config.py. This is the one to edit.
    [string]$EnvPath = ""
)

$ErrorActionPreference = "Continue"
if (-not $EnvPath) {
    $EnvPath = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend\.env"
}

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host "  $Text" -ForegroundColor $Colour }
function Stop-Here([string]$Text) {
    Write-Host ""
    Write-Host "  STOPPED: $Text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "SERVER SETTING  ->  $EnvPath" -ForegroundColor Cyan
Write-Host ("-" * 68)

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Stop-Here "Cannot reach that file. Connect FortiClient VPN (we.are.sdi) and try again."
}

$lines = @(Get-Content -LiteralPath $EnvPath -Encoding UTF8)

# -- Show: names only, never values --------------------------------------------
if ($Show) {
    Say "Settings present (names only - no value is ever printed):" White
    $any = $false
    foreach ($line in $lines) {
        if ($line -match "^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$") {
            $any = $true
            $has = if ($Matches[2].Trim()) { "set" } else { "EMPTY" }
            $colour = if ($Matches[2].Trim()) { "Green" } else { "Yellow" }
            Write-Host ("    {0,-34} {1}" -f $Matches[1], $has) -ForegroundColor $colour
        }
    }
    if (-not $any) { Say "No settings found in that file." Yellow }
    Write-Host ""
    exit 0
}

if (-not $Name) {
    Stop-Here "Name the setting, e.g.  .\Set-Setting.ps1 SDI_ESTIMATOR_OIDS ""<value>""   (or -Show)"
}
if (-not $Remove -and -not $PSBoundParameters.ContainsKey("Value")) {
    Stop-Here "Give the value, or use -Remove to take the setting out."
}

# -- What is there now? ---------------------------------------------------------
$at = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*$([regex]::Escape($Name))\s*=") { $at = $i; break }
}
$existed = ($at -ge 0)
$wasEmpty = $existed -and ($lines[$at] -replace "^[^=]*=", "").Trim() -eq ""

if ($Remove) {
    if (-not $existed) { Say "$Name is not in the file. Nothing to remove." Yellow; Write-Host ""; exit 0 }
    $after = @($lines[0..($at - 1)]) + @($lines[($at + 1)..($lines.Count - 1)])
    $after = @($after | Where-Object { $_ -ne $null })
    $what = "removed"
} else {
    $new = "$Name=$Value"
    if ($existed) {
        $lines[$at] = $new
        $after = $lines
        $what = if ($wasEmpty) { "filled in (it was empty)" } else { "replaced" }
    } else {
        $after = @($lines) + @($new)
        $what = "added"
    }
}

if ($WhatIf) {
    Say "$Name would be $what. Nothing was written (-WhatIf)." Yellow
    Write-Host ""
    exit 0
}

# -- Back it up, then write -----------------------------------------------------
# The worry that started this: a hand-edited file on a share, not in version
# control, that every app reads once at startup. A dated copy beside it costs
# nothing and means a bad edit is one rename away from undone.
$backup = "$EnvPath.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
try {
    Copy-Item -LiteralPath $EnvPath -Destination $backup -ErrorAction Stop
    Say "Backed up to $(Split-Path -Leaf $backup)" Green
} catch {
    Stop-Here "Could not write a backup, so nothing was changed: $($_.Exception.Message)"
}

try {
    # UTF-8 with NO byte-order mark. A BOM makes the FIRST setting in the file
    # unreadable, and it fails as though that setting were simply absent -
    # which is a long evening if the first line happens to be a secret.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, $after, $utf8)
} catch {
    Stop-Here "Could not write the file: $($_.Exception.Message). The backup is at $backup"
}

# -- Read it back ---------------------------------------------------------------
$check = @(Get-Content -LiteralPath $EnvPath -Encoding UTF8)
$found = @($check | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" })
if ($Remove) {
    if ($found.Count -gt 0) { Stop-Here "$Name is still in the file. The backup is at $backup" }
    Say "$Name $what." Green
} else {
    if ($found.Count -ne 1) {
        Stop-Here "Expected one $Name line and found $($found.Count). The backup is at $backup"
    }
    $length = ($found[0] -replace "^[^=]*=", "").Length
    Say "$Name $what - $length character(s) written." Green
    Say "(The value is not printed. Use -Show to list which settings are set.)" Gray
}
Say "$($check.Count) line(s) in the file." Gray

Write-Host ""
Write-Host "  .env is read ONCE, at startup, so this does nothing until a restart:" -ForegroundColor Yellow
Write-Host "      .\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1 -Restart" -ForegroundColor White
Write-Host ""
