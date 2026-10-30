<#
    BEFORE YOU TELL ANYONE TO SIGN IN.

    Run from the LAPTOP, with FortiClient VPN (we.are.sdi) connected:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Ready-For-People.ps1

    ── WHY THIS EXISTS ──────────────────────────────────────────────────────
    Four company directors are about to open AM CRM for the first time. The
    usual way to find out whether somebody's access works is to ask them to
    try it, which means the FIRST person to discover a problem is the person
    you least want discovering it - and every one of these failures looks,
    from their side, like "the thing doesn't work" rather than "a setting
    needs changing".

    These are the failure modes, and what each one looks like TO THEM:

      not assigned in Entra ....... the sign-in page comes back, forever, with
                                    no error. Looks broken. Worst one.
      no SharePoint permission .... "This pilot uses a tracker you don't have
                                    access to"
      not in SDI_VOICECRM_OWNERS .. "Your records aren't mapped yet"
      initials not in the sheet ... an empty list (the app says which values
                                    DO exist, which is how you fix it)
      in OWNERS but not WRITERS ... can ask, politely refused on changes
      wrongly IN WRITERS .......... can change things they should not

    This checks everything reachable from the laptop and then prints, by
    name, the two gates that live in Entra and SharePoint and cannot be
    checked from here - so they get done rather than assumed.

    It NEVER prints a setting's value. It is given an address and answers
    yes or no about it, which discloses nothing you did not already type.
#>
[CmdletBinding()]
param(
    # Who should be able to CHANGE records.
    [string[]]$Writers = @(
        "james.gray@wearesdi.com",
        "nick.garrish@sdidisplays.co.uk",
        "andy.baxter@wearesdi.com",
        # Ian Jones - PM on Nick's accounts. Write access asked for by Nick,
        # 30 October. He sees Nick's rows (NG): his own initials live in the
        # PM Owner column, which this app does not filter on yet.
        "ian.jones@wearesdi.com"
    ),
    # Who should be able to ASK but not change.
    [string[]]$ReadOnly = @(
        "kayleigh.thornhill@wearesdi.com",
        "charlotte.blackwell@wearesdi.com",
        "matt.evans@wearesdi.com",
        # Read-only to EVERY row ("*"), 30 October. Found by the audit in
        # AM CRM's own logs, so these are the sign-in names the app sees.
        "jack.calow@wearesdi.com",
        "muhammad.yazir@wearesdi.com",
        "yogesh.kumar@wearesdi.com"
    ),
    [string]$Server = "10.0.0.5"
)

$ErrorActionPreference = "Continue"
$remote = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend"
$envPath = "$remote\.env"

# ── Helpers, all defined before anything uses them ───────────────────────────
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
function Block([string]$Text) { No $Text; $script:Blockers++ }

function FileHas([string]$Relative, [string]$Marker) {
    $path = Join-Path $remote $Relative
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    if (-not $Marker) { return $true }
    return (Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue) -like "*$Marker*"
}

# The raw line for one setting. Used only to ASK questions of it - which
# addresses are present - never to print it.
function SettingLine([string]$Name) {
    if (-not $script:EnvLines) { return $null }
    foreach ($line in $script:EnvLines) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=(.*)$") { return $Matches[1] }
    }
    return $null
}

Write-Host ""
Write-Host "  AM CRM - READY FOR PEOPLE?" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# ── 1. Can we reach the server at all? ───────────────────────────────────────
Head "1. The server"
if (-not (Test-Path -LiteralPath $envPath)) {
    No "Cannot reach $envPath"
    Say "Connect FortiClient VPN (we.are.sdi) and run this again." White
    Write-Host ""
    exit 1
}
Yes "Reached $Server over the VPN"
$script:EnvLines = @(Get-Content -LiteralPath $envPath -Encoding UTF8 -ErrorAction SilentlyContinue)
Say "$($script:EnvLines.Count) line(s) in .env"

# ── 2. Did the deploy land? ──────────────────────────────────────────────────
Head "2. Is the per-person code actually on the server?"
# The setting in step 3 does NOTHING without this file. Set first and deployed
# later leaves everyone seeing one person's records, with a .env that says
# otherwise - the exact silent state the mapping exists to prevent.
$hasOwners = FileHas "crm_owners.py" "def owner_for"
if ($hasOwners) {
    Yes "crm_owners.py is on the server - each person gets their OWN records"
} else {
    Block "crm_owners.py is NOT on the server."
    Say "Everyone who signs in would see the SAME person's records." Red
    Say "Deploy first:  .\sdi-intelligence-backend\deploy\Ship-It.ps1" White
}
if (FileHas "voicecrm.py" "owner_for(") {
    Yes "voicecrm.py calls it"
} else {
    Block "voicecrm.py on the server is older code and does not call owner_for."
    Say "Deploy:  .\sdi-intelligence-backend\deploy\Ship-It.ps1" White
}
if (FileHas "voicecrm_connector.py" "voicecrm.owner_for(user)") {
    Yes "the ChatGPT connector filters per person too"
} else {
    Block "The ChatGPT connector is older code. In ChatGPT - including VOICE"
    Say "mode, where there is no screen to notice it on - everyone would be" Red
    Say "answered about the same person's pipeline." Red
}

# ── 3. The owner map ─────────────────────────────────────────────────────────
Head "3. Does each person have their own records?"
$owners = SettingLine "SDI_VOICECRM_OWNERS"
if (-not $owners -or -not $owners.Trim()) {
    Block "SDI_VOICECRM_OWNERS is not set. EVERY signed-in person would see the"
    Say "same owner's records - another person's pipeline, labelled as theirs." Red
    Say "Set it:  .\sdi-intelligence-backend\deploy\Set-Setting.ps1 SDI_VOICECRM_OWNERS ""...""" White
} else {
    $mapped = @{}
    foreach ($pair in $owners.Split(",")) {
        $bits = $pair.Split("=", 2)
        if ($bits.Count -eq 2 -and $bits[0].Trim() -and $bits[1].Trim()) {
            $mapped[$bits[0].Trim().ToLower()] = $bits[1].Trim()
        }
    }
    Yes "SDI_VOICECRM_OWNERS maps $($mapped.Count) people"
    foreach ($who in ($Writers + $ReadOnly)) {
        $key = $who.Trim().ToLower()
        if ($mapped.ContainsKey($key)) {
            # The token IS printed: you typed it, it is initials, and seeing
            # "*" where you expected "AB" is the whole point of looking.
            $token = $mapped[$key]
            if ($token -eq "*") { Yes "$who sees EVERY row (*)" }
            else { Yes "$who sees rows owned by '$token'" }
        } else {
            Block "$who is NOT mapped - they would see nothing at all."
        }
    }
}

# ── 4. Who may change things ─────────────────────────────────────────────────
Head "4. Who can change records, and who definitely cannot?"
$writerLine = SettingLine "SDI_VOICECRM_WRITERS"
if (-not $writerLine -or -not $writerLine.Trim()) {
    Block "SDI_VOICECRM_WRITERS is empty - nobody can change anything."
} else {
    $listed = @($writerLine.Split(",") | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
    foreach ($who in $Writers) {
        if ($listed -contains $who.Trim().ToLower()) { Yes "$who can change records" }
        else { Block "$who should be able to change records and CANNOT." }
    }
    # The opposite mistake, which no one would notice until it happened.
    foreach ($who in $ReadOnly) {
        if ($listed -contains $who.Trim().ToLower()) {
            Block "$who is READ-ONLY but IS on the writers list."
        } else {
            Yes "$who is read-only, as intended"
        }
    }
}
$writeOn = SettingLine "SDI_VOICECRM_WRITE"
if ($writeOn -and $writeOn.Trim().ToLower() -in @("yes", "1", "true", "on")) {
    Yes "SDI_VOICECRM_WRITE is on"
} else {
    Block "SDI_VOICECRM_WRITE is not 'yes' - NOBODY can save, whatever the list says."
}

# ── 5. Is it running? ────────────────────────────────────────────────────────
Head "5. Is the service up on the new code?"
$state = (& sc.exe \\$Server query SDIIntelligence 2>&1 | Select-String "STATE") -join " "
if ($state -match "RUNNING") {
    Yes "SDIIntelligence is RUNNING"
    Say "If any setting above changed since it started, restart it:" Yellow
    Say "  .\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1 -Restart" White
} elseif ($state) {
    Block "SDIIntelligence is not running: $state"
} else {
    Warn "Could not read the service state from here. Check on the server."
}

# ── 6. What this cannot see ──────────────────────────────────────────────────
Head "6. BY HAND - the two gates that are not on this server"
Write-Host ""
Say "These cannot be checked over a file share, and BOTH fail silently." White
Write-Host ""
Say "A. ENTRA - each person assigned to the portal application" Yellow
Say "   Entra ID > Enterprise applications > [the app whose Application ID is"
Say "   SDI_CLIENT_ID] > Users and groups > Add user/group."
Say "   Find the Application ID with:"
Say "     Select-String $remote\.env -Pattern ""SDI_CLIENT_ID""" White
Say "   If Properties > 'Assignment required' is No, any tenant user can sign"
Say "   in and there is nothing to do here."
Say "   IF THIS IS WRONG THEY SEE: the sign-in page, again and again, with no" Red
Say "   error on it. It looks like the app is broken." Red
Write-Host ""
Say "B. SHAREPOINT - each person a member of Nick's sandbox site" Yellow
Say "   The app reads the workbook AS THEM, so Microsoft refuses them directly."
Say "   Nick does this, not you."
Say "   IF THIS IS WRONG THEY SEE: 'This pilot uses a tracker you don't have" Red
Say "   access to'." Red
Write-Host ""
Say "C. THE INITIALS HAVE TO EXIST IN THE SHEET" Yellow
Say "   Open the tracker, look down the AM Owner column, and confirm every"
Say "   token in step 3 actually appears. An initial nobody owns shows an"
Say "   empty list - the app then lists the values it DID find, which is how"
Say "   you correct it, but it is better found now than by a director."
Write-Host ""

# ── Verdict ──────────────────────────────────────────────────────────────────
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($script:Blockers -eq 0) {
    Write-Host "  Nothing on the server is blocking them." -ForegroundColor Green
    Write-Host "  Do A, B and C above, then ask ONE person to sign in before the rest." -ForegroundColor Green
} else {
    Write-Host "  $($script:Blockers) thing(s) would stop somebody. Fix them before telling anyone." -ForegroundColor Red
}
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
exit ([int]($script:Blockers -gt 0))
