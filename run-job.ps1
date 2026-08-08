<#
    Run one job through the estimator.

    RUN IT FROM THE REPO ROOT. This script lives beside src\, not inside it, so from
    C:\ClaudeVision\src the name does not resolve and PowerShell reports it as an unknown
    command rather than a missing file:

        cd C:\ClaudeVision
        .\run-job.ps1 12392

        .\run-job.ps1 12392                        # a bare job number is enough
        .\run-job.ps1 'C:\ClaudeVision\input\drawings\12392-02'
        .\run-job.ps1 12392 -Deliverables
        .\run-job.ps1 12392 -Twice                 # reproducibility check

    A BARE JOB NUMBER RESOLVES. Typing the full path is where this goes wrong: three
    sessions in a row were lost to a placeholder path being pasted verbatim, and the
    script's only answer was "no such job folder" — true, unhelpful, and identical
    whether the pack was missing, on a share that had not mounted, or simply spelled
    differently. Give it 12392 and it searches:

        input\drawings\                            the local working copy
        $env:SDI_JOBS_ROOT                         set this to the estimating share
        the current directory

    and, when nothing matches, PRINTS WHAT IT DID FIND so the next attempt is a
    correction rather than another guess.

    To make the share searchable, set it once per machine. Point it at the folder that
    HOLDS the packs, not at a pack:

        setx SDI_JOBS_ROOT "K:\Shared\Estimating\Completed\AI Estimating\Live Enquiry"

    setx writes it for FUTURE consoles and does not touch the one that ran it, so either
    reopen the console or set it for this session as well:

        $env:SDI_JOBS_ROOT = "K:\Shared\Estimating\Completed\AI Estimating\Live Enquiry"

    Pointing it at one pack still works — the parent is searched too — but every sibling
    pack on the enquiry is then reachable by number, which is the point of setting it.

    PREFER THE UNC PATH TO A DRIVE LETTER:

        setx SDI_JOBS_ROOT "\\<server>\<share>\Shared\Estimating\...\Live Enquiry"

    A mapped letter is per-logon-token and per-session. It disappears in an elevated
    console, it goes stale while still holding its letter (which is what "System error 85
    — the local device name is already in use" means when the drive is nowhere to be
    seen), and it is absent entirely on a machine that never mapped it. A UNC path has
    none of those properties. Where a letter has gone stale, release it before re-mapping:

        net use K: /delete
        net use K: \\<server>\<share> /persistent:yes

    Exists because a long command line pasted into a console loses its first character
    often enough to matter, and PowerShell then runs the fragment: "C:\ClaudeVision\..."
    arriving as ":\ClaudeVision\..." leaves a bare "r 42", which is Invoke-History, which
    silently re-runs whatever command 42 happened to be. Twice in one day that looked like
    the engine hanging when it was replaying an old run.

    -Twice runs the same pack through unchanged and prints both totals. Same code, same
    pack, same answer is the property the caches exist for, and nobody had actually
    measured it.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Job,
    [switch] $Deliverables,
    [switch] $Twice
)

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$main   = Join-Path $root 'src\main.py'

if (-not (Test-Path $python)) { Write-Error "no virtualenv at $python"; exit 1 }

# ── RESOLVE THE JOB ─────────────────────────────────────────────────────────────────
# Where a pack can live, most specific first. SDI_JOBS_ROOT is how a machine points at
# the estimating share without this script carrying anybody's drive letter — a hardcoded
# path is exactly the kind of per-site detail that stops working on the next machine.
# The @() WRAPS THE PIPELINE, not just the list. A pipeline that yields one item unwraps
# to that item, so with only one existing root $searchRoots would be a bare string — and
# the += below would concatenate onto it rather than append to a list, producing a path
# that is two paths glued together and exists nowhere.
$searchRoots = @(
    @(
        (Join-Path $root 'input\drawings')
        $env:SDI_JOBS_ROOT
        (Get-Location).Path
    ) | Where-Object { $_ -and (Test-Path $_) }
)

# A SET-BUT-DEAD ROOT WAS SILENT, and silence here is the worst possible answer: the
# variable was set correctly, the console echoed nothing, and the script then reported
# "no job folder matching '12392'" while listing two roots that never included the share.
# Every part of that is true and it points at the wrong thing entirely.
$jobsRootUnreachable = [bool]($env:SDI_JOBS_ROOT -and -not (Test-Path $env:SDI_JOBS_ROOT))

function Show-PathDiagnosis([string] $p) {
    <#
        WHY a path is not reachable, not merely that it is not. On Windows the three
        causes need three different actions and look identical from Test-Path:

          the drive is not mapped in this session
          the drive IS mapped but this shell cannot see it (elevation)
          the drive is fine and the path below it is wrong

        The third is diagnosed by walking up to the deepest ancestor that DOES exist —
        which names the exact component where the typed path leaves reality.
    #>
    Write-Host "`nSDI_JOBS_ROOT is set but not reachable from this session:" -ForegroundColor Red
    Write-Host "    $p"

    $qual = ''
    try { $qual = Split-Path $p -Qualifier -ErrorAction Stop } catch { }

    if ($p -like '\\*') {
        Write-Host "`nIt is a UNC path. Check the server name and that you have access:" -ForegroundColor Yellow
        Write-Host "    Test-Path '$(($p -split '\\')[0..3] -join '\')'"
    }
    elseif ($qual) {
        $drv = Get-PSDrive -Name $qual.TrimEnd(':') -ErrorAction SilentlyContinue
        if (-not $drv) {
            Write-Host "`nDrive $qual is not mapped in this session." -ForegroundColor Yellow

            # REGISTERED BUT DISCONNECTED IS NOT THE SAME AS UNMAPPED, and it is the case
            # that wastes the most time: Get-PSDrive cannot see the letter, so the obvious
            # move is to map it — and `net use K: \\server\share` then fails with
            # "System error 85 — the local device name is already in use", which reads as a
            # contradiction. It is not. The persistent mapping is still registered, the
            # redirector is holding the letter, and the connection behind it is dead. The
            # letter must be released before it can be re-used, and trying a DIFFERENT
            # letter usually fails the same way because it is stale for the same reason.
            $stale = $null
            try {
                $stale = (& net use 2>$null | Select-String -SimpleMatch "$qual ")
            } catch { }
            if ($stale) {
                Write-Host "`n...but $qual IS registered as a persistent mapping. `net use` says:" -ForegroundColor Yellow
                $stale | ForEach-Object { Write-Host "    $($_.Line.Trim())" }
                Write-Host "`nA registered-but-disconnected mapping still holds the letter, which"
                Write-Host 'is why mapping it again returns "System error 85 - the local device'
                Write-Host 'name is already in use". Release it first:'
                Write-Host "    net use $qual /delete" -ForegroundColor Cyan
                Write-Host "    net use $qual \\<server>\<share> /persistent:yes" -ForegroundColor Cyan
            }

            $elevated = $false
            try {
                $elevated = ([Security.Principal.WindowsPrincipal] `
                    [Security.Principal.WindowsIdentity]::GetCurrent()
                    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            } catch { }
            if ($elevated) {
                # This has cost this project a day before. Mapped drives belong to a logon
                # token, and an elevated shell runs under a DIFFERENT token — so a drive
                # that is present in Explorer and in a normal console is simply absent
                # here, with no error anywhere to say why.
                Write-Host "`nThis console is ELEVATED, and mapped drives belong to the" -ForegroundColor Yellow
                Write-Host 'non-elevated logon token. A drive you can see in Explorer is'
                Write-Host 'invisible here. Run this script from a NORMAL PowerShell, or'
                Write-Host 'use the UNC path, which does not depend on the mapping.'
            } elseif (-not $stale) {
                Write-Host "    net use $qual \\<server>\<share> /persistent:yes"
            }

            # THE ROUTE THAT AVOIDS ALL OF THE ABOVE. A UNC path needs no drive letter, so
            # it cannot be stale, cannot be held by another session, and does not vanish
            # when the shell is elevated. Where the letter has ever been mapped the server
            # is recoverable from the persistent mapping, so the exact line to paste can be
            # printed rather than described.
            $unc = ''
            if ($stale) {
                $m = [regex]::Match($stale[0].Line, '(\\\\[^\s]+)')
                if ($m.Success) { $unc = $p -replace [regex]::Escape($qual), $m.Groups[1].Value }
            }
            Write-Host "`nOr skip the drive letter entirely — a UNC path needs no mapping," -ForegroundColor Cyan
            Write-Host 'survives elevation, and is the more robust thing to put in the variable:'
            if ($unc) {
                Write-Host "    `$env:SDI_JOBS_ROOT = '$unc'"
            } else {
                Write-Host "    `$env:SDI_JOBS_ROOT = '\\<server>\<share>$($p.Substring($qual.Length))'"
                Write-Host '    (find <server>\<share> with:  net use   — or in Explorer, the'
                Write-Host "     drive shows as \\server\share ($qual))"
            }
        }
        elseif ($drv.DisplayRoot) {
            Write-Host "`nDrive $qual is mapped to $($drv.DisplayRoot), so the drive is fine" -ForegroundColor Yellow
            Write-Host 'and the path below it is not. The UNC equivalent of what you set is:'
            Write-Host "    $($p -replace [regex]::Escape($qual), [regex]::Escape($drv.DisplayRoot).Replace('\\','\'))"
        }
    }

    # THE DEEPEST THING THAT DOES EXIST. Naming it turns "that path is wrong" into "the
    # path is right up to here and wrong after it", which is one look rather than a hunt.
    $probe = $p
    while ($probe -and -not (Test-Path $probe)) {
        # STOP AT THE SHARE ROOT. Above \\server\share there is nothing to test — the walk
        # would climb to \\server and then to \\, neither of which is a place a pack could
        # be, and reporting "the path exists as far as \\" is worse than reporting nothing.
        if ($probe -like '\\*' -and (($probe.TrimStart('\') -split '\\').Count -le 2)) {
            $probe = ''; break
        }
        $next = Split-Path $probe -Parent
        if (-not $next -or $next -eq $probe) { $probe = ''; break }
        $probe = $next
    }
    # A bare root is not a useful answer. "The path exists as far as \" tells the reader
    # only that their filesystem exists, in the place a real finding would have gone.
    if ($probe -and ($probe.TrimEnd('\', '/').Length -gt 2)) {
        Write-Host "`nThe path exists as far as:" -ForegroundColor Cyan
        Write-Host "    $probe"
        $kids = @(Get-ChildItem -LiteralPath $probe -Directory -ErrorAction SilentlyContinue |
                  Select-Object -First 15 -ExpandProperty Name)
        if ($kids) {
            Write-Host '  and below that are:'
            foreach ($k in $kids) { Write-Host "    $k" }
        }
    } else {
        Write-Host "`nNo part of that path is reachable." -ForegroundColor Cyan
    }
}

# A ROOT POINTED AT ONE PACK STILL WORKS. "Jobs root" reads as "where my job is" at least
# as naturally as "where my jobs are", and the first person to set it pointed it straight
# at 12392-02. Searching only the CHILDREN of that would look inside the pack — at its DXF
# and PDF sub-folders — and match nothing, for a reason no message would have explained.
# So a root that is itself a pack has its PARENT searched too, which also makes the sibling
# packs on the same enquiry reachable by number.
$jobsRootIsAPack = $false
if ($env:SDI_JOBS_ROOT -and (Test-Path $env:SDI_JOBS_ROOT)) {
    if ((Split-Path $env:SDI_JOBS_ROOT -Leaf) -match '^\d{3,6}([-_].*)?$') {
        $jobsRootIsAPack = $true
        $parent = Split-Path $env:SDI_JOBS_ROOT -Parent
        if ($parent -and (Test-Path $parent)) { $searchRoots += $parent }
    }
}

function Resolve-Job([string] $wanted) {
    if (Test-Path $wanted) { return (Resolve-Path $wanted).Path }

    # A bare number, or a partial code. Prefer an exact folder name, then a prefix match,
    # so '12392' finds '12392-02' but '12392-02' is never answered with '12392-04'.
    $leaf = Split-Path $wanted -Leaf
    foreach ($mode in @('exact', 'prefix')) {
        # The roots themselves, before their children: a root that IS the pack answers
        # here rather than being searched fruitlessly from the inside.
        foreach ($r in $searchRoots) {
            $rn = Split-Path $r -Leaf
            $isHit = if ($mode -eq 'exact') { $rn -ieq $leaf } else { $rn -ilike "$leaf*" }
            if ($isHit) { return (Resolve-Path $r).Path }
        }
        foreach ($r in $searchRoots) {
            $hits = @(Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
                      Where-Object {
                          if ($mode -eq 'exact') { $_.Name -ieq $leaf }
                          else { $_.Name -ilike "$leaf*" }
                      })
            if ($hits.Count -eq 1) { return $hits[0].FullName }
            if ($hits.Count -gt 1) {
                Write-Host "'$leaf' matches more than one folder under ${r}:" -ForegroundColor Yellow
                $hits | ForEach-Object { Write-Host "    $($_.FullName)" }
                Write-Error 'Name the one you want.'
                exit 1
            }
        }
    }
    return $null
}

$resolved = Resolve-Job $Job
if (-not $resolved) {
    # SAY WHAT IS THERE. "No such job folder" is true of a typo, an unmounted share and a
    # pack that was never copied down, and those need three different next actions.
    Write-Host "no job folder matching '$Job'." -ForegroundColor Red
    Write-Host "`nSearched:" -ForegroundColor Cyan
    foreach ($r in $searchRoots) { Write-Host "    $r" }
    if ($jobsRootUnreachable) {
        Show-PathDiagnosis $env:SDI_JOBS_ROOT
    }
    elseif (-not $env:SDI_JOBS_ROOT) {
        Write-Host "`nSDI_JOBS_ROOT is not set in THIS console, so the estimating share was" -ForegroundColor Yellow
        Write-Host 'not searched. setx writes it for future consoles and does NOT affect the'
        Write-Host 'one that ran it, which is the usual reason this appears right after setting it.'
        Write-Host '    $env:SDI_JOBS_ROOT = "K:\...\Live Enquiry"     # this console, now'
        Write-Host '    setx SDI_JOBS_ROOT "K:\...\Live Enquiry"       # every console after'
        Write-Host "`nA UNC path is the better value: no drive letter to go stale, nothing" -ForegroundColor Cyan
        Write-Host 'to break when the console is elevated, and it works on a machine that'
        Write-Host 'never mapped the share at all:'
        Write-Host '    $env:SDI_JOBS_ROOT = "\\<server>\<share>\...\Live Enquiry"'
    }
    elseif ($jobsRootIsAPack) {
        Write-Host "`nSDI_JOBS_ROOT points at ONE PACK, not at the folder that holds your" -ForegroundColor Yellow
        Write-Host "packs: $env:SDI_JOBS_ROOT"
        Write-Host 'Its parent was searched as well, so this should still have worked — if it'
        Write-Host 'did not, set it one level up:'
        Write-Host "    setx SDI_JOBS_ROOT `"$(Split-Path $env:SDI_JOBS_ROOT -Parent)`""
    }
    # Collected, then printed. Assigning to an outer variable from inside a pipeline
    # script block is a scoping question with a version-dependent answer, and this file
    # exists because a console surprise cost a day.
    # A JOB FOLDER IS ONE WITH DRAWINGS IN IT. Listing every directory under the roots put
    # .venv, .github, .pytest_cache and src on a list headed "Jobs found", which is worse
    # than printing nothing: it invites the reader to try one. Tested by what a pack IS —
    # it holds drawings — rather than by a blocklist of names that would need extending
    # for every new directory anybody adds.
    $found = @()
    foreach ($r in $searchRoots) {
        $found += @(
            Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
                Select-Object -First 60 |
                Where-Object {
                    $null -ne (Get-ChildItem -LiteralPath $_.FullName -File -Recurse -Depth 1 `
                                   -Include *.pdf, *.dxf, *.sldprt, *.sldasm `
                                   -ErrorAction SilentlyContinue |
                               Select-Object -First 1)
                } |
                Select-Object -First 25 -ExpandProperty FullName
        )
    }
    Write-Host "`nFolders holding drawings:" -ForegroundColor Cyan
    if ($found.Count -eq 0) {
        Write-Host '    (none under the roots above — no pack has been copied down yet)'
    } else {
        foreach ($f in $found) { Write-Host "    $f" }
    }
    exit 1
}
$Job = $resolved
Write-Host "job: $Job" -ForegroundColor DarkGray

$estArgs = @($main, '--job', $Job, '--generate-ai-spreadsheet')
if ($Deliverables) { $estArgs += '--deliverables' }

function Invoke-Run([string] $label) {
    Write-Host "`n=== $label ===`n" -ForegroundColor Cyan
    & $python @estArgs 2>&1 | Tee-Object -Variable out | Out-Host
    ($out | Select-String 'stamped real totals into JSON').Line
}

$first = Invoke-Run 'run 1'
if ($Twice) {
    $second = Invoke-Run 'run 2 (same code, same pack)'
    Write-Host "`n=== REPRODUCIBILITY ===" -ForegroundColor Cyan
    Write-Host "run 1: $first"
    Write-Host "run 2: $second"
    if ($first -eq $second) {
        Write-Host 'IDENTICAL — the caches and the deterministic path hold.' -ForegroundColor Green
    } else {
        Write-Host 'DIFFERENT — same code and same pack produced two answers.' -ForegroundColor Red
    }
}

Write-Host "`nMeasure it:" -ForegroundColor Cyan
Write-Host "  $python $(Join-Path $root 'tools\three_numbers.py')"
