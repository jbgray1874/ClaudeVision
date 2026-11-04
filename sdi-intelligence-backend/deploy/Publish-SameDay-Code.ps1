<#
    PUT SDI SAMEDAY'S CODE INTO ITS PRIVATE REPOSITORY - CODE ONLY.

    Run FROM THE LAPTOP, in the office or on the VPN. K: does not need to be
    mapped: the share is read by its full name, which also works in a
    PowerShell window opened as administrator (Windows hides a person's
    mapped drives from those - 4 November, "Cannot find drive K").

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Publish-SameDay-Code.ps1

    The first time, a GitHub sign-in window opens: sign in as jbgray1874, the
    account the private repository belongs to.

    -- WHY THIS EXISTS -------------------------------------------------------
    4 November 2026: "Pls let's make changes so the Voice AI is as strong as
    possible ... Create the private repo for SameDay." The code lives on K:,
    which no Claude session can read, and ClaudeVision is a PUBLIC repository,
    so it cannot go there. sdi-sameday is private, and this copies only code
    and documents into it.

    -- WHAT NEVER GOES IN ----------------------------------------------------
    The keys (.env), every database (chats, briefs, past work), the picture
    index, renders and GAs (out\), what account managers uploaded
    (client_files\), client profiles, logs, spend records (studio_data\), old
    copies (backups\), virtual environments, and any file over 5 MB.

    Before anything is committed, every file copied is read for anything
    shaped like an OpenAI, Anthropic or xAI key. One is enough to stop it,
    with nothing committed and nothing sent. A hit is reported by file and
    line, never by its text.
#>
[CmdletBinding()]
param(
    # The folder that HOLDS SDI_Automation and Muhammad's documents.
    # K: is this share (Check-SameDay-Ready, 3 November).
    [string]$Source = "\\sdi-dc01\shareddata$\Shared\IT\AI & Automation\Design\SDI Same Day Intelligence",
    # The user name in the address makes the sign-in ask for THAT account: the
    # laptop's saved GitHub sign-in is a different one (jbgraysdi2026).
    [string]$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git",
    # A folder of its own, used for nothing else.
    [string]$Work = "C:\SameDayRepo"
)

$ErrorActionPreference = "Continue"

# -- Helpers, all defined before anything uses them -------------------------
function Head([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}
function Yes ([string]$Text) { Write-Host "  [ok]    $Text" -ForegroundColor Green }
function Say ([string]$Text, [string]$Colour = "Gray") { Write-Host "          $Text" -ForegroundColor $Colour }
function Stop-Here([string]$Text) {
    Write-Host ""
    Write-Host "  [STOP]  $Text" -ForegroundColor Red
    Write-Host "          Nothing was committed and nothing was sent to GitHub." -ForegroundColor Red
    Write-Host ""
    exit 1
}
# NOT called "Git": PowerShell names are case-blind and a function beats a
# program, so a function called Git would call itself instead of git.exe.
# Git's own output is shown, not returned, so only the exit code comes back.
function RunGit([string[]]$Arguments) {
    & git.exe -C $Work @Arguments | Out-Host
    return $LASTEXITCODE
}

$skipDirs = @(".git", ".venv", ".venv-gpu", "venv", "__pycache__", "out", "client_files",
              "backups", "logs", "studio_data", "node_modules", ".idea", ".vscode")
$skipFiles = @(".env", ".env.local", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3",
               "*.npz", "*.npy", "*.pt", "*.pth", "*.onnx", "*.safetensors", "*.bin", "*.pkl",
               "*.log", "*.zip", "*.pyc", "PHONE_LINK.txt", "client_profiles.json",
               "*.before-cookie-fix")
$docs = @("README.md", "ARCHITECTURE.md", "DEPLOY_GUIDE.html", "USER_GUIDE.html",
          "requirements_full.txt", ".env.example", "UPDATE_SAME_DAY.bat")

Write-Host ""
Write-Host "  SDI SAMEDAY - CODE INTO ITS PRIVATE REPOSITORY" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# -- 1. Checks ---------------------------------------------------------------------
Head "1. Checks"
# FAIL CLOSED. An error INSIDE an if's condition makes PowerShell skip the
# whole if - so a failed check here once printed "[ok] readable" and went on.
# Plain strings for the paths, and the test itself caught.
$auto = "$Source\SDI_Automation"
$readable = $false
try { $readable = Test-Path -LiteralPath "$auto\brief_lite\lite_app.py" -ErrorAction Stop } catch { $readable = $false }
if (-not $readable) {
    Stop-Here "Cannot read $auto\brief_lite\lite_app.py. Connect FortiClient VPN (or be in the office) and run this again."
}
Yes "SameDay's code is readable on K:'s share"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-Here "git is not installed on this laptop." }

# The working folder is emptied (except its history) before each copy, so it
# must be a folder this script owns: new, or already holding sdi-sameday.
$full = [IO.Path]::GetFullPath($Work).TrimEnd("\")
if ($full.Length -le 3 -or $full -like "C:\ClaudeVision*" -or $full -like "C:\SDI_Automation*" -or
    $full -like "$env:USERPROFILE") {
    Stop-Here "$Work is not a folder this script may empty. Choose a new one with -Work."
}
if (Test-Path -LiteralPath $Work) {
    if (-not (Test-Path -LiteralPath (Join-Path $Work ".git"))) {
        Stop-Here "$Work exists and is not this script's. Move it, or choose another with -Work."
    }
    $remote = (& git -C $Work remote get-url origin 2>$null) -join ""
    if ($remote -and $remote -ne $Repo) {
        Stop-Here "$Work belongs to another repository ($remote)."
    }
} else {
    New-Item -ItemType Directory -Path $Work | Out-Null
    & git -C $Work init -q
    & git -C $Work checkout -q -b main 2>$null
}
Yes "Working folder: $Work"

# -- 2. Copy the code, and nothing else ----------------------------------------------
Head "2. Copying the code (no keys, data, renders, uploads or big files)"
Get-ChildItem -LiteralPath $Work -Force | Where-Object { $_.Name -ne ".git" } |
    Remove-Item -Recurse -Force
$robo = @($auto, (Join-Path $Work "SDI_Automation"), "/E", "/MAX:5000000", "/R:1", "/W:1",
          "/NP", "/NFL", "/NDL", "/NJH", "/NJS") + @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "Copying from K: failed (robocopy $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath (Join-Path $Work "SDI_Automation\brief_lite\lite_app.py"))) {
    Stop-Here "The copy does not hold brief_lite\lite_app.py - it did not complete."
}
foreach ($doc in $docs) {
    $from = "$Source\$doc"
    if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $Work }
}
# What stays behind for being big - named, so nothing is missing silently.
$big = @(Get-ChildItem -LiteralPath $auto -Recurse -File -Force -ErrorAction SilentlyContinue |
         Where-Object { $_.Length -gt 5000000 -and
                        $_.FullName -notmatch '\\(\.venv[^\\]*|venv|out|client_files|backups|logs|studio_data)\\' })
foreach ($f in $big) { Say ("left on K: (over 5 MB): " + $f.FullName.Substring($auto.Length).TrimStart("\")) }

# A .gitignore, so a later copy can never commit data either.
@("# SDI SameDay - code only. Written by Publish-SameDay-Code.ps1.") +
    ($skipDirs | Where-Object { $_ -ne ".git" } | ForEach-Object { "$_/" }) + $skipFiles |
    Set-Content -LiteralPath (Join-Path $Work ".gitignore") -Encoding ASCII
$count = @(Get-ChildItem -LiteralPath $Work -Recurse -File -Force |
           Where-Object { $_.FullName -notmatch '\\\.git\\' }).Count
Yes "$count file(s) copied"

# -- 3. Nothing key-shaped ------------------------------------------------------------
Head "3. Checking for keys (file and line only - never the key)"
$files = @(Get-ChildItem -LiteralPath $Work -Recurse -File -Force |
           Where-Object { $_.FullName -notmatch '\\\.git\\' })
$named = @($files | Where-Object { $_.Name -like ".env*" -and $_.Name -ne ".env.example" })
foreach ($f in $named) { Write-Host "  [STOP]  A settings file: $($f.FullName)" -ForegroundColor Red }
$keyShape = 'sk-ant-[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|xai-[A-Za-z0-9]{20,}'
$hits = @($files | Select-String -Pattern $keyShape -CaseSensitive -ErrorAction SilentlyContinue)
foreach ($hit in $hits) {
    Write-Host "  [STOP]  Key-shaped text in $($hit.Path), line $($hit.LineNumber)" -ForegroundColor Red
}
if ($named.Count -or $hits.Count) {
    Stop-Here "Take those out on K: first (and ask Muhammad whether the keys need replacing)."
}
Yes "Nothing key-shaped in $($files.Count) file(s)"

# -- 4. Commit and send ----------------------------------------------------------------
Head "4. Into sdi-sameday"
$version = ""
$stamp = "$auto\brief_lite\VERSION.txt"
if (Test-Path -LiteralPath $stamp) { $version = ((Get-Content -LiteralPath $stamp -TotalCount 1) -join "").Trim() }
if ((RunGit @("add", "-A")) -ne 0) { Stop-Here "git add failed." }
$pending = (& git -C $Work status --porcelain) -join ""
if ($pending) {
    $message = "SameDay from K:" + $(if ($version) { " - $version" } else { "" })
    if ((RunGit @("commit", "-q", "-m", $message)) -ne 0) {
        Stop-Here "git commit failed. If it asks who you are: git config --global user.name / user.email."
    }
    Yes "Committed: $message"
} else {
    Yes "Nothing new on K: since the last run"
}
if (-not ((& git -C $Work remote get-url origin 2>$null) -join "")) {
    RunGit @("remote", "add", "origin", $Repo) | Out-Null
}
if ((RunGit @("push", "-u", "origin", "main")) -ne 0) {
    Write-Host ""
    Write-Host "  [STOP]  GitHub did not take it. Nothing else was changed." -ForegroundColor Red
    Say "Repository not found: create it first - github.com, New repository, name"
    Say "sdi-sameday, Private, no README - and sign in as jbgray1874 when asked."
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host "  Done. SameDay's code is in github.com/jbgray1874/sdi-sameday (private)." -ForegroundColor Green
Write-Host "  Tell Claude, so the session can read it." -ForegroundColor White
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
