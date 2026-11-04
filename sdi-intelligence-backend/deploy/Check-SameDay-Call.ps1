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
    [int]$Lines = 30,
    # A chat id from the list in section 2, to read that one instead of the latest.
    [string]$Chat = ""
)

$ErrorActionPreference = "Continue"
$Via = "http://${Server}:8071/sameday"
$Log = "\\$Server\c$\SDI_Automation\logs\SDISameDay.log"
$Logs = "\\$Server\c$\SDI_Automation\logs"
$Auto = "\\$Server\c$\SDI_Automation"

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
# Windows PowerShell 5.1 hands back a JSON list as ONE item (the whole list); passing it
# through the pipeline lays it out as separate items (4 November: every chat came out at once).
function Items($Value) { return @($Value | ForEach-Object { $_ }) }

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
# Past work (4 Nov 2026: "it keeps saying it can't see past jobs"). SameDay searches indexes made from W: and K:,
# not the drives file by file: what it can find, then the index files themselves on the server.
$ver = Ask "/api/version"
$past = if ($ver) { $ver.past_work } else { $null }
if ($past) {
    $jobs = [int]$past.jobs
    if ($jobs -gt 0) { Yes ("Past jobs it can find: " + $jobs) }
    else {
        Warn ("Past jobs it can find: NONE - " + $past.why)
        $hints += "SameDay has no job index: copy projects.db from Muhammad's laptop (C:\SDI_Automation\brief_lite) to the server's, then restart SDISameDay."
    }
    if ($past.estimates) { Yes "Old estimates (K:): there" } else { Warn "Old estimates (K:): no knowledge.db" }
    if ($past.pictures) { Yes "Look-alike pictures: on" }
    else { Say ("Look-alike pictures: off (" + $past.why + ") - past jobs are still found by number, name and words") }
} else {
    Warn "This SameDay does not say what past work it can find: it is older than the 4 November fix."
    $hints += "Run Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz: before it, past jobs needed the picture index, which the server does not have."
}
foreach ($f in @("$Auto\brief_lite\projects.db", "$Auto\brief_lite\knowledge.db", "$Auto\all_img_index.npz")) {
    $i = Get-Item -LiteralPath $f -ErrorAction SilentlyContinue
    if ($i) { Say ("{0,-20} {1,7:N0} MB   {2:d MMM yyyy HH:mm}" -f $i.Name, ($i.Length / 1MB), $i.LastWriteTime) }
    else { Say ("{0,-20} not on the server" -f (Split-Path $f -Leaf)) }
}

# -- 2. The last chat ----------------------------------------------------------------
Head "2. The last chat, as SameDay kept it"
$chats = Items (Ask "/api/sessions")
if (-not $chats.Count -or -not $chats[0].id) {
    Warn "No chats to read."
} else {
    Say "The most recent chats (newest first):" White
    foreach ($r in $chats | Select-Object -First 6) {
        $b = $null
        try { $b = $r.brief | ConvertFrom-Json } catch { $b = $null }
        $what = if ($b) { ([string]$b.client + " / " + [string]$b.unit_type + " / size " + [string]$b.size + " / past-or-new " + [string]$b.design_route) } else { "" }
        Say ("  " + $r.id + "  " + $r.updated + "  " + $r.name + "  pictures: " + $r.n_visuals + "  " + $what)
    }
    $c = $chats[0]
    if ($Chat) { $c = $chats | Where-Object { $_.id -eq $Chat } | Select-Object -First 1 }
    if (-not $c) { Warn "No chat $Chat in the list." }
    else {
        Write-Host ""
        Say ("Reading chat " + $c.id + " (" + $c.name + ", last change " + $c.updated + ") - another one: -Chat <id>") White
        $one = Ask ("/api/session/" + $c.id)
        $msgs = if ($one) { Items $one.messages } else { @() }
        $from = [Math]::Max(0, $msgs.Count - $Lines)
        if ($msgs.Count) {
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
                $hints += "The AM asked for a render and no picture was made - the yellow lines above, and the 'rt tool' lines below, say why."
            }
        }
    }
}

# -- 3. SameDay's log --------------------------------------------------------------
Head "3. SameDay's log - errors and drawing (keys removed)"
# The service starts a new log file each time it restarts, so a call before the last
# restart is in an older one: the three newest are read, oldest first.
$files = @()
try { $files = @(Get-ChildItem -LiteralPath $Logs -Filter "SDISameDay*.log" -ErrorAction Stop | Sort-Object LastWriteTime | Select-Object -Last 3) } catch { $files = @() }
if (-not $files.Count) {
    Warn "Can't read $Logs over the admin share (the same rights Ship-It uses)."
} else {
    $pattern = 'rt tool|rt done|Traceback|Error|error|refused|budget|credit|429|timed out|timeout|image|visual|render|live voice|drive |past job lookup|past by name|past-work|search not ready|ref lookup|took [0-9]+s|waited [0-9]+s|live files'
    $hits = @()
    foreach ($f in $files) { $hits += @(Get-Content -LiteralPath $f.FullName -Tail 1500 -ErrorAction SilentlyContinue | Select-String -Pattern $pattern) }
    Say ("Read: " + (($files | ForEach-Object { $_.Name }) -join ", "))
    if (-not $hits.Count) { Yes "Nothing about errors, drawing or the voice's tools" }
    foreach ($h in $hits | Select-Object -Last 40) {
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
