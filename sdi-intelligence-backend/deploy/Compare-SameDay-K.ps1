<#
    WHAT IS ON K: COMPARED WITH THE REPOSITORY?  READS ONLY.
    Run FROM THE LAPTOP, in the office or on the VPN:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Compare-SameDay-K.ps1

    -- WHY ---------------------------------------------------------------------
    4 November 2026: "I asked what he had put into the K: and if we can
    compare that with what's in the repo - not to do anything with it but
    just to understand it ... I don't want his code pushed."

    Publish-SameDay-Code.ps1 SENDS K:'s code to GitHub. This one does not.
    It reads K:'s code - the same files Publish would take, never the keys,
    databases, renders, uploads, logs or budget settings - and reads the
    repository, then says:
      1. what has changed on K: since its last copy in the repository
      2. which of those files the server's code has changed too
    and saves the details in a report on this laptop, for Claude.

    Nothing is committed and nothing is sent: GitHub is only read, and K: is
    only read. The work happens in C:\SameDayCompare, a folder of its own.
#>
[CmdletBinding()]
param(
    # The folder that HOLDS SDI_Automation and Muhammad's documents (K:).
    [string]$Source = "\\sdi-dc01\shareddata$\Shared\IT\AI & Automation\Design\SDI Same Day Intelligence",
    [string]$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git",
    # What the server runs (Update-SameDay.ps1 -Branch ...).
    [string]$Branch = "claude/inspiring-planck-8juriz",
    # A folder of its own, used for nothing else.
    [string]$Work = "C:\SameDayCompare"
)

$ErrorActionPreference = "Continue"
$auto = "$Source\SDI_Automation"
$Reports = "$Work-reports"
# The same key shapes as Publish-SameDay-Code.ps1.
$keyShape = 'sk-ant-[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|xai-[A-Za-z0-9]{20,}'
# The same as Publish-SameDay-Code.ps1: code and documents only.
$skipDirs = @(".git", ".venv", ".venv-gpu", "venv", "__pycache__", "out", "client_files",
              "backups", "logs", "studio_data", "node_modules", ".idea", ".vscode")
$skipFiles = @(".env", ".env.local", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3",
               "*.npz", "*.npy", "*.pt", "*.pth", "*.onnx", "*.safetensors", "*.bin", "*.pkl",
               "*.log", "*.zip", "*.pyc", "PHONE_LINK.txt", "client_profiles.json",
               "*.before-cookie-fix")
$docs = @("README.md", "ARCHITECTURE.md", "DEPLOY_GUIDE.html", "USER_GUIDE.html",
          "requirements_full.txt", ".env.example", "UPDATE_SAME_DAY.bat")

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
    Write-Host "          Nothing was sent anywhere, and K: was not touched." -ForegroundColor Red
    Write-Host ""
    [Console]::OutputEncoding = $script:wasEncoding
    exit 1
}
# NOT called "Git": PowerShell names are case-blind and a function beats a
# program, so a function called Git would call itself instead of git.exe.
function RunGit([string[]]$Arguments) {
    & git.exe -C $Work @Arguments | Out-Host
    return $LASTEXITCODE
}
# Git's answer as lines of text (file names as they are, not quoted).
function GitText([string[]]$Arguments) {
    return @(& git.exe -C $Work -c core.quotepath=off @Arguments 2>$null)
}
function NoKeys([string]$Text) { return ($Text -replace $keyShape, '[key removed]') }
# "12<TAB>3<TAB>path" lines from --numstat, as path -> "+12 -3"
function Counts([string[]]$Lines) {
    $out = @{}
    foreach ($l in $Lines) {
        $p = $l -split "`t", 3
        if ($p.Count -eq 3) { $out[$p[2]] = $(if ($p[0] -eq "-") { "picture or binary" } else { "+" + $p[0] + " -" + $p[1] + " lines" }) }
    }
    return $out
}

$script:wasEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8      # code with a pound sign or an arrow reads right

Write-Host ""
Write-Host "  SDI SAMEDAY - WHAT IS ON K: COMPARED WITH THE REPOSITORY  (reads only)" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# -- 1. Checks ---------------------------------------------------------------------
Head "1. Checks"
# FAIL CLOSED: the test itself caught, so an error can never read as "readable".
$readable = $false
try { $readable = Test-Path -LiteralPath "$auto\brief_lite\lite_app.py" -ErrorAction Stop } catch { $readable = $false }
if (-not $readable) {
    Stop-Here "Cannot read $auto\brief_lite\lite_app.py. Connect FortiClient VPN (or be in the office) and run this again."
}
Yes "SameDay's code on K: is readable"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-Here "git is not installed on this laptop." }

# The working folder is emptied (except its history) before each look, so it
# must be a folder this script owns - never the ones Publish or Update use.
$full = [IO.Path]::GetFullPath($Work).TrimEnd("\")
if ($full.Length -le 3 -or $full -like "C:\ClaudeVision*" -or $full -like "C:\SDI_Automation*" -or
    $full -like "C:\SameDayRepo*" -or $full -like "C:\SameDayDeploy*" -or $full -like "$env:USERPROFILE") {
    Stop-Here "$Work is not a folder this script may empty. Choose a new one with -Work."
}
if (Test-Path -LiteralPath $Work) {
    if (-not (Test-Path -LiteralPath (Join-Path $Work ".git"))) {
        Stop-Here "$Work exists and is not this script's. Move it, or choose another with -Work."
    }
    $remote = (& git -C $Work remote get-url origin 2>$null) -join ""
    if ($remote -ne $Repo) { Stop-Here "$Work belongs to another repository ($remote)." }
} else {
    New-Item -ItemType Directory -Path $Work | Out-Null
    & git -C $Work init -q
    & git -C $Work remote add origin $Repo
}
# K: keeps Windows line endings, the repository plain ones. Set on THIS folder (every step reads it - a comparison
# reads the file on disk too), so only real changes show, not every line of every file.
& git -C $Work config core.autocrlf true
& git -C $Work config core.safecrlf false
Yes "Working folder: $Work (on this laptop only)"

# -- 2. The repository - read only ---------------------------------------------------
Head "2. Reading the repository (nothing is sent)"
$fetched = & git.exe -C $Work fetch -q origin "+refs/heads/*:refs/remotes/origin/*" 2>&1
if ($LASTEXITCODE -ne 0) {
    $fetched | Out-Host
    Stop-Here "Could not read sdi-sameday. Sign in as jbgray1874 when asked, on the office network or the VPN."
}
$lastK = ""
if ((GitText @("rev-parse", "-q", "--verify", "refs/remotes/origin/from-k")) -join "") {
    $lastK = "origin/from-k"
} else {
    $lastK = ((GitText @("log", "refs/remotes/origin/main", "-1", "--format=%H", "--grep=^SameDay from K:")) -join "").Trim()
}
if (-not $lastK) { Stop-Here "The repository holds no copy of K: to compare with." }
$lastWhat = ((GitText @("log", "-1", "--format=%s, put in the repository %ad", "--date=format:%d %b %Y %H:%M", $lastK)) -join "").Trim()
Yes "Last copy of K: in the repository: $lastWhat"
$haveBranch = [bool]((GitText @("rev-parse", "-q", "--verify", "refs/remotes/origin/$Branch")) -join "")
if ($haveBranch) { Yes "What the server runs: $Branch" } else { Warn "No branch $Branch in the repository - part 5 is skipped." }

# -- 3. K: - read only ------------------------------------------------------------------
Head "3. Reading K: (code only - no keys, data, renders, uploads or logs)"
if ((RunGit @("checkout", "-q", "-f", "--detach", $lastK)) -ne 0) { Stop-Here "Could not set out the last copy of K: ($lastK)." }
Get-ChildItem -LiteralPath $Work -Force | Where-Object { $_.Name -ne ".git" -and $_.Name -ne ".gitignore" } |
    Remove-Item -Recurse -Force
$robo = @($auto, (Join-Path $Work "SDI_Automation"), "/E", "/MAX:5000000", "/R:1", "/W:1",
          "/NP", "/NFL", "/NDL", "/NJH", "/NJS") + @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "Reading K: failed (robocopy $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath (Join-Path $Work "SDI_Automation\brief_lite\lite_app.py"))) {
    Stop-Here "The copy of K: does not hold brief_lite\lite_app.py - it did not complete."
}
foreach ($doc in $docs) {
    $from = "$Source\$doc"
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $Work }
}
# Any other settings file is left out of the comparison altogether.
Get-ChildItem -LiteralPath $Work -Recurse -File -Force |
    Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.Name -like ".env*" -and $_.Name -ne ".env.example" } |
    ForEach-Object { Warn ("Left out, a settings file: " + $_.Name); Remove-Item -LiteralPath $_.FullName -Force }
$files = @(Get-ChildItem -LiteralPath $Work -Recurse -File -Force |
           Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.Name -ne ".gitignore" })
foreach ($hit in @($files | Select-String -Pattern $keyShape -CaseSensitive -ErrorAction SilentlyContinue)) {
    Warn ("Key-shaped text on K: in " + $hit.Path.Substring($Work.Length).TrimStart("\") + ", line " + $hit.LineNumber +
          " - removed from the report. Ask Muhammad whether that key needs replacing.")
}
$kver = ""
if (Test-Path -LiteralPath "$Work\SDI_Automation\brief_lite\VERSION.txt") {
    $kver = ((Get-Content -LiteralPath "$Work\SDI_Automation\brief_lite\VERSION.txt" -TotalCount 1) -join "").Trim()
}
Yes ("K: now: version " + $(if ($kver) { $kver } else { "(no VERSION.txt)" }) + ", " + $files.Count + " file(s)")
Say "Most recently changed on K:" White
foreach ($f in @($files | Sort-Object LastWriteTime -Descending | Select-Object -First 6)) {
    Say ("  " + $f.LastWriteTime.ToString("ddd d MMM HH:mm") + "  " + $f.FullName.Substring($Work.Length).TrimStart("\"))
}
# Into this folder's own index only - line endings as the repository keeps them. Nothing is committed.
& git.exe -C $Work add -A 2>$null
if ($LASTEXITCODE -ne 0) { Stop-Here "Could not line K:'s files up with the repository's (git add)." }

# -- 4. What has changed on K: --------------------------------------------------------------
Head "4. What has changed on K: since its last copy"
$skip = ":(exclude).gitignore"
$status = GitText @("diff", "--cached", "--no-renames", "--name-status", $lastK, "--", ".", $skip)
$counts = Counts (GitText @("diff", "--cached", "--no-renames", "--numstat", $lastK, "--", ".", $skip))
$theirs = @()
foreach ($l in $status) {
    $p = $l -split "`t", 2
    if ($p.Count -lt 2) { continue }
    $theirs += $p[1]
    $what = switch -Regex ($p[0]) { "^A" { "new     " } "^D" { "removed " } default { "changed " } }
    Say ($what + $p[1] + $(if ($counts[$p[1]] -and $p[0] -notmatch "^D") { "  (" + $counts[$p[1]] + ")" } else { "" })) White
}
if (-not $theirs.Count) { Yes "Nothing has changed on K: since that copy." }
else { Say ("" + $theirs.Count + " file(s) changed on K:. '+' lines are new on K:, '-' lines were taken out.") }

# -- 5. Against what the server runs --------------------------------------------------------
$ours = @()
if ($haveBranch) {
    Head "5. Those files against the server's code ($Branch)"
    $ours = GitText @("diff", "--no-renames", "--name-only", $lastK, "refs/remotes/origin/$Branch", "--", ".", $skip)
    foreach ($f in $theirs) {
        if ($ours -contains $f) { Warn "Changed on K: AND in the server's code: $f" }
        else { Say ("Only on K:, not on the server: " + $f) }
    }
    Say ("The server's code has " + $ours.Count + " file(s) of its own changes since that copy, which K: has not got:")
    foreach ($f in $ours) { Say ("  " + $f) }
}

# -- The report ---------------------------------------------------------------------------
$null = New-Item -ItemType Directory -Force -Path $Reports
$report = Join-Path $Reports ("K-compared-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".txt")
$lines = @("SDI SameDay - K: compared with the repository, " + (Get-Date -Format "dddd d MMMM yyyy, HH:mm"),
           "K: now: version $kver",
           "Last copy of K: in the repository: $lastWhat",
           "What the server runs: $Branch",
           "",
           "== Changed on K: since that copy ==") + $status +
         @("", "== The server's own changes since that copy (not on K:) ==") + $ours +
         @("", "== What changed on K:, line by line ('+' new on K:, '-' taken out) ==") +
         (GitText @("diff", "--cached", "--no-renames", $lastK, "--", ".", $skip))
[IO.File]::WriteAllLines($report, [string[]]@($lines | ForEach-Object { NoKeys ([string]$_) }), (New-Object Text.UTF8Encoding($false)))

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host "  Nothing was sent to GitHub and nothing on K: was changed." -ForegroundColor Green
Write-Host "  The details, line by line (keys removed), are in:" -ForegroundColor White
Write-Host "    $report" -ForegroundColor White
Write-Host "  Send Claude that file, or everything above." -ForegroundColor Gray
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
[Console]::OutputEncoding = $script:wasEncoding
