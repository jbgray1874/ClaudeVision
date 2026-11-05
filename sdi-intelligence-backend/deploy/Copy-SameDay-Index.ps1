<#
    PUT MUHAMMAD'S PICTURE INDEX ON THE SERVER, SO SAMEDAY MATCHES PAST WORK BY WHAT IT LOOKS LIKE.
    Run FROM THE LAPTOP, VPN connected, once Muhammad has copied it to K::

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Copy-SameDay-Index.ps1

    -- WHY ---------------------------------------------------------------------
    5 November 2026. SameDay finds past jobs on the server by their names and
    words, with Claude looking at the best dozen. Muhammad's picture index -
    built on his laptop from all 269,000 pictures on W: - finds them by what
    they look like. He copies it to K: (index-for-server); this brings it to
    the server: the same one way in as the code (never by hand, never from his
    laptop straight to the server).

    -- WHAT IT DOES --------------------------------------------------------------
      1. Checks K:'s copy is complete: the index opens (a half-copied one
         doesn't), the job list is a real database, both from the same build.
      2. Keeps the server's current job list (and index, if any) in backups.
      3. Copies everything while SameDay keeps running: the thumbnails (added,
         never deleted) and the index and job list under temporary names.
      4. Pauses the watch, stops SameDay for the few seconds it takes to swap
         the index and job list in (a running SameDay holds the job list
         open), starts it again, and turns the watch back on.
      5. Waits until SameDay says picture matching is on - or says why not.
    Best run in the office: over the VPN, everything travels through the
    laptop, and the thumbnails are many small files (-NoThumbs leaves them for
    another time; running it again carries on where a copy stopped).
    It never touches the keys (.env), the chats (lite.db), or anything else.
#>
[CmdletBinding()]
param(
    [string]$Server = "10.0.0.5",
    # Where Muhammad puts it - K: by its full name (works without K: mapped, and as administrator).
    [string]$From = "\\sdi-dc01\shareddata$\Shared\IT\AI & Automation\Design\SDI Same Day Intelligence\index-for-server",
    [switch]$NoThumbs,
    [string]$Watch = "SDI SameDay Watch"
)

$ErrorActionPreference = "Continue"
$Target = "\\$Server\c$\SDI_Automation"
$Version = "http://${Server}:5020/api/version"

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
function Stop-Here([string]$Text) {
    Write-Host ""
    Write-Host "  [STOP]  $Text" -ForegroundColor Red
    Write-Host "          Nothing on the server was changed." -ForegroundColor Red
    Write-Host ""
    exit 1
}
function There([string]$Path) {
    try { return [bool](Test-Path -LiteralPath $Path -ErrorAction Stop) } catch { return $false }
}
function Size-MB([string]$Path) { return [math]::Round((Get-Item -LiteralPath $Path).Length / 1MB) }
# SameDay's own answer: pictures on, how many jobs, and why not.
function Past-Work {
    try { return (Invoke-RestMethod -Uri $Version -TimeoutSec 10).past_work } catch { return $null }
}
function Service-State([string]$Name) {
    $q = (& sc.exe "\\$Server" query $Name 2>&1) -join " "
    if ($q -match "STATE\s+:\s+\d+\s+(\w+)") { return $Matches[1] }
    return ""
}

Write-Host ""
Write-Host "  SDI SAMEDAY - THE PICTURE INDEX ONTO THE SERVER" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# -- 1. Checks: everything before anything changes ----------------------------------
Head "1. Is Muhammad's copy on K: complete?"
if (-not (There $From)) { Stop-Here "Nothing at $From yet. When Muhammad has copied it there, run this again." }
$npz = "$From\all_img_index.npz"
$db = if (There "$From\projects.db") { "$From\projects.db" } else { "$From\brief_lite\projects.db" }
$thumbs = if (-not $NoThumbs -and (There "$From\all_img_thumbs")) { "$From\all_img_thumbs" } else { "" }
if (-not (There $npz)) { Stop-Here "all_img_index.npz is not in $From." }
if (-not (There $db)) { Stop-Here "projects.db is not in $From (or its brief_lite folder) - it must come with the index." }

# Still being copied? Its size moves, or it is too new to trust.
$a = (Get-Item -LiteralPath $npz).Length
Start-Sleep -Seconds 5
$b = (Get-Item -LiteralPath $npz).Length
if ($a -ne $b) {
    Stop-Here "all_img_index.npz is still growing - Muhammad's copy hasn't finished. Run this again when it has."
}
# A half-copied index can't be opened: its table of contents is at the end.
$pictures = 0
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($npz)
    $entry = $zip.Entries | Where-Object { $_.Name -eq "emb.npy" } | Select-Object -First 1
    if ($entry) {
        $s = $entry.Open()
        $buf = New-Object byte[] 256
        $n = $s.Read($buf, 0, 256)
        $s.Close()
        $head = [Text.Encoding]::ASCII.GetString($buf, 0, $n)
        if ($head -match "'shape':\s*\((\d+),") { $pictures = [int]$Matches[1] }
    }
    $zip.Dispose()
} catch {
    Stop-Here "all_img_index.npz won't open - most likely the copy hasn't finished, or it was cut short."
}
if (-not $pictures) { Stop-Here "all_img_index.npz opens but holds no picture list (emb). Ask Muhammad which file is the index." }
Yes ("The index opens: " + $pictures.ToString("N0") + " pictures, " + (Size-MB $npz) + " MB")
# A real SQLite database starts with these 16 bytes.
$head = ""
try {
    $f = [IO.File]::OpenRead($db)
    $buf = New-Object byte[] 16
    $null = $f.Read($buf, 0, 16)
    $f.Close()
    $head = [Text.Encoding]::ASCII.GetString($buf)
} catch { $head = "" }
if (-not $head.StartsWith("SQLite format 3")) { Stop-Here "projects.db is not a complete database - the copy may not have finished." }
Yes ("The job list is a database: " + (Size-MB $db) + " MB")
# The same build: picture n in the index is picture n in the job list. SameDay checks the count itself
# (and refuses a mismatch); the dates are a first look.
$gap = [math]::Abs(((Get-Item -LiteralPath $npz).LastWriteTime - (Get-Item -LiteralPath $db).LastWriteTime).TotalDays)
if ($gap -gt 3) {
    Warn ("The index and the job list were made " + [math]::Round($gap) + " days apart. SameDay will refuse them if they")
    Say "don't match - ask Muhammad whether they come from the same build."
} else { Yes "The index and the job list were made at the same time" }
if ($thumbs) { Yes "The thumbnails folder is there" }
elseif ($NoThumbs) { Say "Thumbnails left for another time (-NoThumbs)." }
else { Warn "No all_img_thumbs folder - matching still works; past-work pictures load from W: instead." }

if (-not (There "$Target\brief_lite\lite_app.py")) { Stop-Here "Can't reach SameDay on the server ($Target). VPN on?" }
# Room on the server's C: for the index, the job list and the thumbnails, with plenty to spare.
try {
    $disk = Get-WmiObject -Class Win32_LogicalDisk -ComputerName $Server -Filter "DeviceID='C:'" -ErrorAction Stop
    $freeGB = [math]::Round($disk.FreeSpace / 1GB, 1)
    $needGB = [math]::Round(((Get-Item -LiteralPath $npz).Length + (Get-Item -LiteralPath $db).Length) / 1GB + $(if ($thumbs) { 8 } else { 0 }) + 10, 1)
    if ($freeGB -lt $needGB) { Stop-Here "The server's C: has $freeGB GB free; this needs about $needGB GB (thumbnails included, 10 GB spare)." }
    Yes "The server's C: has $freeGB GB free"
} catch { Warn "Couldn't read the server's free space - carrying on (a full disk stops the copy, with nothing half-swapped)." }
$before = Past-Work
if ($before) { Say ("SameDay now: " + $before.jobs + " past jobs, pictures " + $(if ($before.pictures) { "on" } else { "off (" + $before.why + ")" })) }

# -- 2. Keep what is replaced --------------------------------------------------------------
Head "2. Keeping the server's current job list"
$keep = "$Target\backups\before-index-" + (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Force -Path $keep | Out-Null
foreach ($p in @("$Target\brief_lite\projects.db", "$Target\all_img_index.npz")) {
    if (There $p) { Copy-Item -LiteralPath $p -Destination $keep }
}
if (-not (There "$keep\projects.db") -and (There "$Target\brief_lite\projects.db")) { Stop-Here "Couldn't keep a copy of the current job list - nothing replaced." }
Yes "Kept in $keep"

# -- 3. Copying, while SameDay keeps running ------------------------------------------------
Head "3. Copying (SameDay keeps running - this is the long part)"
$newNpz = "$Target\all_img_index.npz.incoming"
$newDb = "$Target\brief_lite\projects.db.incoming"
try {
    Copy-Item -LiteralPath $npz -Destination $newNpz -Force -ErrorAction Stop
    Copy-Item -LiteralPath $db -Destination $newDb -Force -ErrorAction Stop
} catch {
    Remove-Item -LiteralPath $newNpz, $newDb -Force -ErrorAction SilentlyContinue
    Stop-Here ("Copying the index failed: " + $_.Exception.Message)
}
if ((Get-Item -LiteralPath $newNpz).Length -ne (Get-Item -LiteralPath $npz).Length) {
    Remove-Item -LiteralPath $newNpz, $newDb -Force -ErrorAction SilentlyContinue
    Stop-Here "The index arrived a different size from K:'s copy."
}
Yes "Index and job list copied, ready to swap in"
if ($thumbs) {
    # many small files: several at once; a stopped copy carries on where it was when this is run again
    & robocopy $thumbs "$Target\all_img_thumbs" /E /MT:16 /R:1 /W:1 /NP /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { Warn "Copying the thumbnails failed (robocopy $LASTEXITCODE) - run this again to carry on. The index goes in regardless." }
    else { Yes "Thumbnails copied (added to what was there - nothing deleted)" }
}

# -- 4. The index and the job list, with SameDay stopped ----------------------------
Head "4. Swapping them in (SameDay stopped for a few seconds, the watch paused)"
# so the watch doesn't email "SameDay isn't answering" about this
& schtasks.exe /Change /S $Server /TN $Watch /DISABLE 2>&1 | Out-Null
& sc.exe "\\$Server" stop SDISameDay | Out-Null
$deadline = (Get-Date).AddSeconds(60)
do { Start-Sleep -Seconds 2 } until ((Service-State "SDISameDay") -eq "STOPPED" -or (Get-Date) -gt $deadline)
if ((Service-State "SDISameDay") -ne "STOPPED") {
    & sc.exe "\\$Server" start SDISameDay | Out-Null
    & schtasks.exe /Change /S $Server /TN $Watch /ENABLE 2>&1 | Out-Null
    Stop-Here "SameDay didn't stop within a minute, so nothing was swapped. It has been asked to start again."
}
$ok = $true
try {     # a rename on the server's own disk - seconds, not a copy
    Move-Item -LiteralPath $newNpz -Destination "$Target\all_img_index.npz" -Force -ErrorAction Stop
    Move-Item -LiteralPath $newDb -Destination "$Target\brief_lite\projects.db" -Force -ErrorAction Stop
} catch {
    $ok = $false
    Warn ("The swap failed: " + $_.Exception.Message)
    foreach ($pair in @(@("$keep\projects.db", "$Target\brief_lite\projects.db"), @("$keep\all_img_index.npz", "$Target\all_img_index.npz"))) {
        if (There $pair[0]) { Copy-Item -LiteralPath $pair[0] -Destination $pair[1] -Force }
    }
    Warn "What was there before has been put back."
}
& sc.exe "\\$Server" start SDISameDay | Out-Null
& schtasks.exe /Change /S $Server /TN $Watch /ENABLE 2>&1 | Out-Null
if ($ok) { Yes "Swapped in; SameDay is starting, the watch is back on" }

# -- 5. Does SameDay use it? ------------------------------------------------------------
Head "5. Waiting for SameDay to load it (the first time can take a few minutes)"
$deadline = (Get-Date).AddMinutes(6)
$past = $null
do {
    Start-Sleep -Seconds 10
    $past = Past-Work
    if ($past) { Say ("  " + (Get-Date -Format "HH:mm:ss") + "  " + $(if ($past.pictures) { "pictures on" } else { $past.why })) }
} until (($past -and ($past.pictures -or ($past.why -and $past.why -notmatch "loading"))) -or (Get-Date) -gt $deadline)

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($past -and $past.pictures) {
    Write-Host "  Picture matching is ON - $($past.jobs) past jobs, matched by what they look like." -ForegroundColor Green
    Write-Host "  Andy can test again." -ForegroundColor Green
} else {
    Write-Host "  Picture matching is not on yet." -ForegroundColor Yellow
    if ($past) { Say ("SameDay says: " + $past.why) }
    if ($past -and $past.why -match "newer than the job index") { Say "The index and job list are from different builds - ask Muhammad for both from the same one." }
    elseif ($past -and $past.why -match "loading") { Say "Still loading - the first time it fetches its picture model. Check again in a few minutes: .\sdi-intelligence-backend\deploy\Check-SameDay-Call.ps1" }
    elseif ($past -and $past.why -match "CLIP") { Say "SameDay's picture software didn't load - send Claude the line above." }
    elseif (-not $past) { Say "SameDay isn't answering yet - run .\sdi-intelligence-backend\deploy\Check-SameDay-Call.ps1 in a minute." }
    Say "Past jobs are still found by words and the AI's look in the meantime - nothing is broken."
}
Say "To put the old job list back: copy $keep\projects.db to $Target\brief_lite\, then restart SDISameDay."
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
