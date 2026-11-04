<#
    WHAT HAPPENED ON THE LAST SAMEDAY CALL?  READS ONLY.
    Run FROM THE LAPTOP, VPN connected, straight after a test call:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Check-SameDay-Call.ps1

    -- WHY ---------------------------------------------------------------------
    4 November 2026: "the render didn't appear on the phone app". Played
    through the phone address in a browser sized as an iPhone, with a
    stand-in render, the render does appear, mid-call too. So the reason is
    on the server: a render that was never made, or that failed. During a
    call SameDay keeps its error lines off the screen and tells the voice
    instead - they are in the chat, and in its log. This shows them.

    It reads SameDay through SDI Intelligence's own /sameday/ address on the
    office network (no team code: that address is for SDI's network and
    signed-in people), and its log over the admin share. It changes nothing.
#>
[CmdletBinding()]
param(
    [string]$Server = "10.0.0.5",
    [int]$Lines = 30
)

$ErrorActionPreference = "Continue"
$Via = "http://${Server}:8071/sameday"
$Log = "\\$Server\c$\SDI_Automation\logs\SDISameDay.log"

# -- Helpers, all defined before anything uses them -------------------------
function Head([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}
function Yes ([string]$Text) { Write-Host "  [ok]    $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "  [check] $Text" -ForegroundColor Yellow }
function Say ([string]$Text, [string]$Colour = "Gray") { Write-Host "          $Text" -ForegroundColor $Colour }
function NoKeys([string]$Text) { return ($Text -replace 'sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9]{16,}|ek_[A-Za-z0-9_\-]{16,}', '[key removed]') }
function Ask([string]$Path) {
    try { return Invoke-RestMethod -Uri ($Via + $Path) -TimeoutSec 20 } catch { return $null }
}

Write-Host ""
Write-Host "  SDI SAMEDAY - WHAT HAPPENED ON THE LAST CALL  (reads only)" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray
$hints = @()

# -- 1. Is it running, and can it spend? -------------------------------------------
Head "1. SameDay now"
$status = Ask "/api/status"
if (-not $status) {
    Warn "No answer from $Via/api/status."
    Say "Not Found means Ship-It has not put the /sameday/ address on yet; no answer at all means the VPN is off."
    exit 1
}
Yes ("Running: " + $status.version)
if ($status.openai_key) { Yes "The OpenAI key is there" } else { Warn "NO OpenAI key - nothing can be drawn"; $hints += "The OpenAI key is missing from C:\SDI_Automation\.env." }
$spent = [double]$status.spent_today
$cap = [double]$status.cap
$money = "Spent today: {0:N2} of {1:N2} USD" -f $spent, $cap
if ($cap -gt 0 -and $spent -ge $cap * 0.9) {
    Warn "$money - at or near today's cap, which stops renders first"
    $hints += "Today's AI cap is (nearly) used up. Raise brief_lite_daily_cap_usd in C:\SDI_Automation\studio_data\ai_switch.json (no restart needed)."
} else { Yes $money }

# -- 2. The last chat ----------------------------------------------------------------
Head "2. The last chat, as SameDay kept it"
$chats = @(Ask "/api/sessions")
if (-not $chats.Count -or -not $chats[0].id) {
    Warn "No chats to read."
} else {
    $c = $chats[0]
    $brief = $null
    try { $brief = $c.brief | ConvertFrom-Json } catch { $brief = $null }
    Say ("Chat " + $c.id + " - " + $c.name + ", last change " + $c.updated + ", pictures in it: " + $c.n_visuals) White
    if ($brief) { Say ("Brief: client=" + $brief.client + "; unit=" + $brief.unit_type + "; size=" + $brief.size + "; route=" + $brief.design_route) }
    $one = Ask ("/api/session/" + $c.id)
    if ($one) {
        $msgs = @($one.messages)
        $from = [Math]::Max(0, $msgs.Count - $Lines)
        foreach ($m in $msgs[$from..($msgs.Count - 1)]) {
            $who = if ($m.dir -eq "in") { "AM " } else { "SDI" }
            $txt = NoKeys ([string]$m.text)
            if ($txt.Length -gt 170) { $txt = $txt.Substring(0, 170) + "..." }
            if ($m.media) { $txt = "[picture] " + $txt }
            $t = ([string]$m.at)
            if ($t.Length -ge 19) { $t = $t.Substring(11, 8) }
            $colour = if ($txt -match "couldn't|can't|cannot|went wrong|paused|budget|not drawn|NO render|Not drawing|error") { "Yellow" } else { "Gray" }
            Write-Host ("  " + $t + "  " + $who + "  " + $txt) -ForegroundColor $colour
        }
        $drew = @($msgs | Where-Object { $_.media -and $_.dir -eq "out" }).Count
        $asked = @($msgs | Where-Object { $_.dir -eq "in" -and $_.text -match "draw|render|show me|make it|picture" }).Count
        if ($asked -and -not $drew) {
            $hints += "The AM asked for a render and no picture was made - the yellow lines above (or the log below) say why."
        }
    }
}

# -- 3. SameDay's log --------------------------------------------------------------
Head "3. SameDay's log - errors and drawing (keys removed)"
$readable = $false
try { $readable = Test-Path -LiteralPath $Log -ErrorAction Stop } catch { $readable = $false }
if (-not $readable) {
    Warn "Can't read $Log over the admin share (the same rights Ship-It uses)."
} else {
    $pattern = 'Traceback|Error|error|refused|budget|credit|429|timed out|timeout|image|visual|render|live voice|drive '
    $hits = @(Get-Content -LiteralPath $Log -Tail 600 -ErrorAction SilentlyContinue | Select-String -Pattern $pattern)
    if (-not $hits.Count) { Yes "Nothing about errors or drawing in the last 600 lines" }
    foreach ($h in $hits | Select-Object -Last 25) {
        $line = NoKeys ([string]$h.Line)
        if ($line.Length -gt 220) { $line = $line.Substring(0, 220) + "..." }
        Say $line
    }
}

# -- Verdict ---------------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($hints.Count) {
    foreach ($h in $hints) { Write-Host "  $h" -ForegroundColor Yellow }
} else {
    Write-Host "  Nothing obvious. Send Claude everything above, with the time of the call." -ForegroundColor White
}
Write-Host "  Send Claude everything above." -ForegroundColor Gray
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
