<#
    BEFORE SDI SAME DAY GOES ON THE SERVER. Reads only - copies, changes and
    starts nothing.

    Run FROM THE LAPTOP, with FortiClient VPN (we.are.sdi) connected and K:
    mapped:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Check-SameDay-Ready.ps1

    Then send Claude everything it prints. It never prints a key: where it
    finds one it gives the file and line, never the text.

    -- WHY THIS EXISTS -------------------------------------------------------
    Same Day has run on a laptop, as a person, with that person's drives
    mapped. On the server it runs as a Windows service, and a service has no
    mapped drives: every W:\ or K:\ path in the code is a folder that is not
    there, and "SDI made this before" comes back empty with no error. That is
    the failure SDI Intelligence hit first ("cannot find the path specified:
    'K:\'"), and it is found here, in the code, before anything is installed
    rather than by Andy in front of a client.

    The other things checked are the ones the deploy guide relies on and
    nobody has looked at on this server: Python 3.11, disk space for the
    picture-matching model, NSSM, ports 5020 and 5030 being free, and no keys
    on K:.
#>
[CmdletBinding()]
param(
    # Where Muhammad put it. The folder that HOLDS SDI_Automation.
    [string]$Source = "K:\IT\AI & Automation\Design\SDI Same Day Intelligence",
    [string]$Server = "10.0.0.5",
    # The deploy guide's path. Several files read C:\SDI_Automation by name.
    [string]$Target = "C:\SDI_Automation",
    # Where it runs today, per the README's internal URL.
    [string]$Laptop = "LC-328802"
)

$ErrorActionPreference = "Continue"

# -- Helpers, all defined before anything uses them -------------------------
# PowerShell resolves functions at RUNTIME: one defined below its first use
# parses perfectly and then throws "is not recognized" half way down the run.
function Head([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}
function Yes ([string]$Text) { Write-Host "  [ok]    $Text" -ForegroundColor Green }
function No  ([string]$Text) { Write-Host "  [STOP]  $Text" -ForegroundColor Red }
function Warn([string]$Text) { Write-Host "  [check] $Text" -ForegroundColor Yellow }
function Say ([string]$Text, [string]$Colour = "Gray") { Write-Host "          $Text" -ForegroundColor $Colour }

$script:Blockers = 0
$script:Checks = 0
function Block([string]$Text) { No $Text; $script:Blockers++ }
function Flag([string]$Text) { Warn $Text; $script:Checks++ }

# A TCP connect with a short wait. Test-NetConnection takes twenty seconds to
# say a port is closed, and this asks about four of them.
function PortOpen([string]$HostName, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(2500)) { return $false }
        $client.EndConnect($wait)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# The code and its settings - not the databases, not the generated renders,
# not the uploaded client files, not a virtual environment.
$codeTypes = @(".py", ".bat", ".cmd", ".ps1", ".json", ".html", ".js", ".txt",
               ".md", ".cfg", ".ini", ".toml", ".yaml", ".yml", ".example")
function CodeFiles([string]$Root) {
    Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '\\(\.venv[^\\]*|venv|__pycache__|out|client_files|node_modules|\.git)\\' -and
            $_.Length -lt 2MB -and
            ($codeTypes -contains $_.Extension.ToLower() -or $_.Name -like ".env*")
        }
}

Write-Host ""
Write-Host "  SDI SAME DAY - READY FOR THE SERVER?" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')  -  reads only" -ForegroundColor DarkGray

# -- 1. The code on K: --------------------------------------------------------
Head "1. The code Muhammad left on K:"
$auto = Join-Path $Source "SDI_Automation"
$app = Join-Path $auto "brief_lite\lite_app.py"
if (-not (Test-Path -LiteralPath $app)) {
    Block "Cannot see $app"
    Say "Is K: mapped on this laptop, and is the folder name exactly as given?" White
    Write-Host ""
    exit 1
}
Yes "Found brief_lite\lite_app.py"
$letter = $Source.Substring(0, 1)
$drive = Get-PSDrive -Name $letter -ErrorAction SilentlyContinue
if ($drive -and $drive.DisplayRoot) {
    Say "${letter}: on this laptop is $($drive.DisplayRoot) - the server will need that"
    Say "share by its UNC name, because a service has no ${letter}: drive."
}
foreach ($doc in @("README.md", "requirements_full.txt", ".env.example")) {
    if (Test-Path -LiteralPath (Join-Path $Source $doc)) { Yes "$doc is there" }
    else { Flag "$doc is not in $Source" }
}
if (Test-Path -LiteralPath (Join-Path $auto "craft\craft_site.py")) { Yes "craft\craft_site.py (SDI Craft, port 5030) is there" }
else { Flag "craft\craft_site.py is not there - the guide starts it on port 5030" }

# How much there is to copy, by top-level folder, so the copy is not a surprise.
Say ""
Say "Size to copy, largest first:"
$sizes = @()
foreach ($dir in Get-ChildItem -LiteralPath (Join-Path $auto "brief_lite") -Directory -Force -ErrorAction SilentlyContinue) {
    $bytes = (Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
              Measure-Object -Property Length -Sum).Sum
    $sizes += [pscustomobject]@{ Name = "brief_lite\" + $dir.Name; Bytes = [double]$bytes }
}
foreach ($db in Get-ChildItem -LiteralPath (Join-Path $auto "brief_lite") -File -Filter *.db -ErrorAction SilentlyContinue) {
    $sizes += [pscustomobject]@{ Name = "brief_lite\" + $db.Name; Bytes = [double]$db.Length }
}
foreach ($row in ($sizes | Sort-Object Bytes -Descending | Select-Object -First 8)) {
    Say ("{0,-34} {1,8:N0} MB" -f $row.Name, ($row.Bytes / 1MB))
}
$total = (Get-ChildItem -LiteralPath $auto -Recurse -File -Force -ErrorAction SilentlyContinue |
          Where-Object { $_.FullName -notmatch '\\\.venv' } | Measure-Object -Property Length -Sum).Sum
Say ("{0,-34} {1,8:N1} GB" -f "SDI_Automation in all (no venv)", ($total / 1GB))

# -- 2. No keys on K: ---------------------------------------------------------
Head "2. Are any keys on K:? (file and line only - never the key)"
$files = @(CodeFiles $Source)
Say "$($files.Count) code and settings file(s) looked at."
$envFiles = @($files | Where-Object { $_.Name -like ".env*" -and $_.Name -ne ".env.example" })
foreach ($f in $envFiles) {
    Block "A settings file with keys may be on K: $($f.FullName)"
}
# OpenAI, Anthropic and xAI key shapes.
$keyShape = 'sk-ant-[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|xai-[A-Za-z0-9]{20,}'
$keyHits = @($files | Select-String -Pattern $keyShape -CaseSensitive -ErrorAction SilentlyContinue)
foreach ($hit in $keyHits) {
    Block "Key-shaped text in $($hit.Path), line $($hit.LineNumber)"
}
if (-not $envFiles.Count -and -not $keyHits.Count) {
    Yes "No .env and nothing key-shaped on K: - the keys are where the guide says"
} else {
    Say "Keys on a share are readable by everyone who can read the share. Move" Red
    Say "them off K:, and ask Muhammad whether they need replacing." Red
}

# -- 3. What a Windows service cannot see ---------------------------------------
Head "3. Paths in the code that a Windows service will not have"
# A drive letter other than C: followed by a slash. "https://" does not match:
# the letter before the colon must not follow another letter.
$drivePath = '(?<![A-Za-z0-9])([D-Zd-z]):[\\/]'
$driveHits = @($files | Where-Object { $_.Name -notlike ".env*" } |
               Select-String -Pattern $drivePath -AllMatches -ErrorAction SilentlyContinue)
if (-not $driveHits.Count) {
    Yes "No mapped-drive paths (D: to Z:) in the code"
} else {
    $byLetter = $driveHits | Group-Object { $_.Matches[0].Groups[1].Value.ToUpper() }
    foreach ($group in $byLetter) {
        Flag "$($group.Name): appears $($group.Count) time(s) - a service has no $($group.Name): drive"
        foreach ($hit in ($group.Group | Select-Object -First 8)) {
            $where = $hit.Path.Substring($Source.Length).TrimStart("\")
            Say "$where, line $($hit.LineNumber)"
        }
        if ($group.Count -gt 8) { Say "...and $($group.Count - 8) more" }
    }
    Say ""
    Say "Each needs the share's UNC name (\\server\share\...) or a setting that" White
    Say "can be given one. That is Muhammad's change, made once, in the code." White
}
$atTarget = @($files | Select-String -Pattern $Target -SimpleMatch -ErrorAction SilentlyContinue)
if ($atTarget.Count) {
    Say "$Target is named $($atTarget.Count) time(s) in the code - the guide is right"
    Say "that it must be installed at exactly that path."
}
$laptopHits = @($files | Select-String -Pattern $Laptop -SimpleMatch -ErrorAction SilentlyContinue)
foreach ($hit in ($laptopHits | Select-Object -First 5)) {
    Flag "The laptop's name ($Laptop) is in $($hit.Path.Substring($Source.Length).TrimStart('\')), line $($hit.LineNumber)"
}

# How the server listens. Printed: it is a host and a port, not a secret.
$serve = @(Select-String -LiteralPath $app -Pattern 'serve\(' -ErrorAction SilentlyContinue)
foreach ($line in ($serve | Select-Object -First 3)) {
    Say "lite_app.py, line $($line.LineNumber): $($line.Line.Trim())"
}

# App Proxy's "Long" backend timeout is 180 seconds. A call allowed longer
# than that is cut off at the proxy while the server finishes it - and pays
# for it - with nobody there to see the answer.
$timeouts = @($files | Where-Object { $_.Extension -eq ".py" } |
              Select-String -Pattern 'timeout\s*[=:]\s*(\d+)' -AllMatches -ErrorAction SilentlyContinue)
$longest = $null
foreach ($hit in $timeouts) {
    foreach ($m in $hit.Matches) {
        $secs = [int]$m.Groups[1].Value
        if (-not $longest -or $secs -gt $longest.Secs) {
            $longest = [pscustomobject]@{ Secs = $secs; Hit = $hit }
        }
    }
}
if ($longest -and $longest.Secs -gt 180) {
    Flag "A timeout of $($longest.Secs)s is longer than App Proxy's 180s"
    Say "$($longest.Hit.Path.Substring($Source.Length).TrimStart('\')), line $($longest.Hit.LineNumber)"
    Say "Past 180s the phone sees an error while the server carries on and pays."
} elseif ($longest) {
    Yes "The longest timeout in the code is $($longest.Secs)s, inside App Proxy's 180s"
}

# The laptop publishes itself to the internet today.
$tunnel = @($files | Where-Object { $_.Name -like "*.bat" -or $_.Name -like "*.cmd" } |
            Select-String -Pattern 'lite_tunnel' -SimpleMatch -ErrorAction SilentlyContinue)
if ((Test-Path -LiteralPath (Join-Path $auto "brief_lite\lite_tunnel.py")) -or $tunnel.Count) {
    Flag "The Cloudflare quick tunnel is in the code$(if ($tunnel.Count) { ' and a start-up script runs it' })"
    Say "It puts the laptop's copy on the public internet behind only the team"
    Say "code. Once the server copy is live, it must be switched off on $Laptop."
}

# -- 4. The server ------------------------------------------------------------
Head "4. The server ($Server)"
$remoteC = "\\$Server\c$"
if (-not (Test-Path -LiteralPath $remoteC)) {
    Block "Cannot reach $remoteC - connect FortiClient VPN (we.are.sdi) and run this again."
} else {
    Yes "Reached $Server over the VPN"
    $there = Join-Path $remoteC ($Target.Substring(3))
    if (Test-Path -LiteralPath $there) {
        Flag "$Target already exists on the server - an install would land on top of it"
        if (Test-Path -LiteralPath (Join-Path $there ".env")) { Say "It has a .env (not read)." }
    } else {
        Yes "$Target is not on the server yet"
    }

    try {
        $fso = New-Object -ComObject Scripting.FileSystemObject
        $freeGb = $fso.GetDrive($remoteC).FreeSpace / 1GB
        if ($freeGb -ge 25) { Yes ("{0:N0} GB free on the server's C:" -f $freeGb) }
        else { Flag ("Only {0:N0} GB free on the server's C: - the Python packages alone (torch) are several GB" -f $freeGb) }
    } catch {
        Warn "Could not read the server's free space from here."
    }

    $pythons = @("Program Files\Python311\python.exe", "Python311\python.exe")
    $found = @($pythons | Where-Object { Test-Path -LiteralPath (Join-Path $remoteC $_) })
    $perUser = @(Get-ChildItem -Path (Join-Path $remoteC "Users\*\AppData\Local\Programs\Python\Python311\python.exe") -ErrorAction SilentlyContinue)
    if ($found.Count) {
        Yes "Python 3.11 for all users: C:\$($found[0])"
    } elseif ($perUser.Count) {
        Flag "Python 3.11 is installed for ONE user only ($($perUser[0].FullName.Substring($remoteC.Length)))"
        Say "A service runs as another account and may not be able to use it. Install"
        Say "Python 3.11.9 (64-bit) 'for all users' on the server."
    } else {
        Flag "No Python 3.11 found on the server. Install 3.11.9 (64-bit), for all users."
    }

    if (Test-Path -LiteralPath (Join-Path $remoteC "Tools\nssm.exe")) {
        Yes "NSSM is there (C:\Tools\nssm.exe) - Same Day can run as a service like SDI Intelligence"
    } else {
        Flag "C:\Tools\nssm.exe is not on the server"
    }

    foreach ($port in @(5020, 5030)) {
        if (PortOpen $Server $port) { Flag "Something on $Server is already answering on port $port" }
        else { Yes "Port $port is free on $Server" }
    }
}

if (PortOpen $Laptop 5020) { Say "The laptop copy ($Laptop`:5020) is answering - it is the live one today." }
else { Say "The laptop copy ($Laptop`:5020) is not answering from here." }

# -- 5. What this cannot see ----------------------------------------------------
Head "5. BY HAND - what is not on any disk this can read"
Say "A. ENTRA - Same Day is its OWN App Proxy application, with 'Assignment" Yellow
Say "   required' on. Every person must be assigned to IT, as well as to SDI"
Say "   Intelligence: missing that is what stopped Kayleigh (AADSTS50105)."
Say "   Once it exists, send Claude its Application ID, and the Entra audit"
Say "   (Check-Entra-Access.ps1) will check this door too."
Say ""
Say "B. THE KEYS - Muhammad gives them to you directly. They go into" Yellow
Say "   $Target\.env on the server, typed there. Not on K:, not in chat."
Say ""
Say "C. WHO CAN REACH PORT 5020 - only the App Proxy connector needs to." Yellow
Say "   Open to the whole office network, the team code is the only lock on it."
Say ""
Say "D. OUTBOUND - the server must reach api.openai.com and api.anthropic.com," Yellow
Say "   and office browsers must reach api.openai.com for the live voice."

# -- Verdict ------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($script:Blockers) {
    Write-Host "  $($script:Blockers) thing(s) to fix before installing, and $($script:Checks) to look at." -ForegroundColor Red
} elseif ($script:Checks) {
    Write-Host "  Nothing blocks the install. $($script:Checks) thing(s) to look at first." -ForegroundColor Yellow
} else {
    Write-Host "  Nothing found that would stop it on the server." -ForegroundColor Green
}
Write-Host "  Send Claude everything above." -ForegroundColor White
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
exit ([int]($script:Blockers -gt 0))
