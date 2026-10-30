<#
    AUDIT ENTRA AND THE SERVER CONFIG BEFORE ANYBODY IS CONTACTED.

    Run ON THE LAPTOP, with FortiClient VPN (we.are.sdi) connected:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Check-Entra-Access.ps1

    ── WHY ──────────────────────────────────────────────────────────────────
    The alternative was sending four company directors a link and asking them
    to paste back what it said. That is using the people you least want
    inconvenienced as a test harness, and every one of these facts can be read
    from Entra directly. So this reads them.

    For each person it answers, without anybody being asked anything:

      1. does the account exist, and what is its EXACT sign-in address?
         The owner map is keyed on e-mail. "Thornhill" and "Thirnhill" are one
         keystroke apart and the wrong one fails silently - the person sees
         "your records aren't mapped yet" and it looks like a broken app.
      2. are they assigned to the application the portal signs in with?
         An unassigned person gets the sign-in page back, forever, with no
         error on it. It looks broken rather than unauthorised.
      3. is that exact address in SDI_VOICECRM_OWNERS on the server?
      4. and in SDI_VOICECRM_WRITERS, if they are meant to write?

    IT ONLY READS. The Graph scopes requested are *.Read.All, it calls no
    write operation, and it changes nothing in Entra or on the server. It
    tells you what to change; it does not change it.

    It needs the Microsoft.Graph PowerShell module. If it is missing it says
    so and gives you the one-line install rather than failing obscurely.

    The sign-in opens in the BROWSER. If that will not work, use a code:

        .\sdi-intelligence-backend\deploy\Check-Entra-Access.ps1 -DeviceCode
#>
[CmdletBinding()]
param(
    [string[]]$Writers = @(
        "james.gray@wearesdi.com",
        "nick.garrish@wearesdi.com",
        "andy.baxter@wearesdi.com"
    ),
    [string[]]$ReadOnly = @(
        "kayleigh.thornhill@wearesdi.com",
        "charlotte.blackwell@wearesdi.com",
        "matt.evans@wearesdi.com"
    ),
    [string]$Server = "10.0.0.5",
    # Skip the Entra half and audit only the server's .env.
    [switch]$ConfigOnly,
    # Sign in with a code typed at microsoft.com/devicelogin, for when the
    # browser sign-in will not open or is blocked.
    [switch]$DeviceCode
)

$ErrorActionPreference = "Continue"
$remote  = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend"
$envPath = "$remote\.env"

# ── Helpers. All defined before anything calls them: PowerShell resolves ─────
# functions at RUNTIME, so one defined further down parses fine and then
# throws "is not recognized" half way through the audit.
function Head([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 74) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 74) -ForegroundColor DarkGray
}
function Yes ([string]$Text) { Write-Host "  [ok]    $Text" -ForegroundColor Green }
function No  ([string]$Text) { Write-Host "  [STOP]  $Text" -ForegroundColor Red }
function Warn([string]$Text) { Write-Host "  [check] $Text" -ForegroundColor Yellow }
function Say ([string]$Text, [string]$Colour = "Gray") { Write-Host "          $Text" -ForegroundColor $Colour }

$script:Blockers = 0
function Block([string]$Text) { No $Text; $script:Blockers++ }

function SettingLine([string]$Name) {
    if (-not $script:EnvLines) { return $null }
    foreach ($line in $script:EnvLines) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=(.*)$") { return $Matches[1] }
    }
    return $null
}

Write-Host ""
Write-Host "  AM CRM - ARE THESE PEOPLE ACTUALLY SET UP?" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')  -  reads only, changes nothing" -ForegroundColor DarkGray

$everyone = @()
foreach ($w in $Writers)  { $everyone += [pscustomobject]@{ Email = $w; Writes = $true } }
foreach ($r in $ReadOnly) { $everyone += [pscustomobject]@{ Email = $r; Writes = $false } }

# ── 1. The server's own settings ─────────────────────────────────────────────
Head "1. What the server has been told"
if (-not (Test-Path -LiteralPath $envPath)) {
    Block "Cannot reach $envPath - connect FortiClient VPN (we.are.sdi)."
    $script:EnvLines = @()
} else {
    Yes "Read .env on $Server"
    $script:EnvLines = @(Get-Content -LiteralPath $envPath -Encoding UTF8 -ErrorAction SilentlyContinue)
}

$ownerMap = @{}
$ownersRaw = SettingLine "SDI_VOICECRM_OWNERS"
if ($ownersRaw -and $ownersRaw.Trim()) {
    foreach ($pair in $ownersRaw.Split(",")) {
        $bits = $pair.Split("=", 2)
        if ($bits.Count -eq 2 -and $bits[0].Trim() -and $bits[1].Trim()) {
            $ownerMap[$bits[0].Trim().ToLower()] = $bits[1].Trim()
        }
    }
    Yes "SDI_VOICECRM_OWNERS maps $($ownerMap.Count) people"
} else {
    Block "SDI_VOICECRM_OWNERS is not set - everyone would see the same person's records."
}

$writerSet = @()
$writersRaw = SettingLine "SDI_VOICECRM_WRITERS"
if ($writersRaw) {
    $writerSet = @($writersRaw.Split(",") | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
    Yes "SDI_VOICECRM_WRITERS names $($writerSet.Count) people"
} else {
    Block "SDI_VOICECRM_WRITERS is empty - nobody could change anything."
}

$clientId = (SettingLine "SDI_CLIENT_ID")
if ($clientId) { $clientId = $clientId.Trim() }
if ($clientId) {
    # The ID, not the name. This tenant has two registrations both reading as
    # "SDI Intelligence" and on 29 October the groups claim went on the wrong
    # one, which looked identical on screen and worked for nobody.
    Yes "Portal signs in with application $clientId"
} else {
    Block "SDI_CLIENT_ID is not in .env - cannot tell which application to check."
}

if ($ConfigOnly) {
    Head "Entra half skipped (-ConfigOnly)"
    Write-Host ""
    exit ([int]($script:Blockers -gt 0))
}

# ── 2. Entra ─────────────────────────────────────────────────────────────────
Head "2. Entra - do these accounts exist, and can they reach the app?"

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Users)) {
    Warn "The Microsoft.Graph module is not installed on this laptop."
    Say "Install it once (a few minutes), then run this again:" White
    Say "  Install-Module Microsoft.Graph -Scope CurrentUser -Force" White
    Say ""
    Say "Until then the Entra half is unchecked. Re-run with -ConfigOnly to" Yellow
    Say "audit just the server, or do section 4's manual steps." Yellow
    Write-Host ""
    exit 2
}

try {
    Import-Module Microsoft.Graph.Users -ErrorAction Stop
    Import-Module Microsoft.Graph.Applications -ErrorAction Stop

    # ── NOT THROUGH WAM ──────────────────────────────────────────────────────
    # Graph PowerShell signs in through Windows' Web Account Manager by
    # default. On 30 October, inside Windows Terminal, that took the WHOLE
    # PowerShell process down straight after the sign-in - "process exited
    # with code 5", no error, no output, nothing a try/catch can see. WAM also
    # asks "Sign in to all apps and websites on this device?", where the
    # highlighted answer makes an ADMIN account the laptop's default sign-in
    # and registers the device with Entra.
    #
    # So WAM is switched off and the sign-in happens in the browser. That is a
    # preference for the Graph module on THIS laptop only - nothing in Entra,
    # nothing on the server - and it persists, which is what you want for the
    # next run too. An older module without the option just carries on.
    try { Set-MgGraphOption -DisableLoginByWAM $true -ErrorAction Stop } catch { }

    # READ-ONLY SCOPES. Nothing here creates, assigns or changes anything.
    # One list, used by both sign-in routes, so they cannot drift apart.
    $scopes = "User.Read.All", "Application.Read.All", "Directory.Read.All"
    if ($DeviceCode) {
        # For when the browser route is blocked too. Prints a code; you type
        # it at microsoft.com/devicelogin in any browser, on any device.
        Connect-MgGraph -Scopes $scopes -UseDeviceCode -NoWelcome -ErrorAction Stop
    } else {
        Say "A browser tab opens for the Microsoft sign-in. Use the cadmin- account," White
        Say "then come back to this window." White
        Connect-MgGraph -Scopes $scopes -NoWelcome -ErrorAction Stop
    }
    $ctx = Get-MgContext
    Yes "Signed in to Entra as $($ctx.Account)"
} catch {
    Block "Could not sign in to Entra: $($_.Exception.Message)"
    Say "You need an account that can READ users and applications." White
    Write-Host ""
    exit 1
}

# Which service principal does the portal use? Found by APPLICATION ID.
$sp = $null
if ($clientId) {
    try {
        $sp = Get-MgServicePrincipal -Filter "appId eq '$clientId'" -ErrorAction Stop |
              Select-Object -First 1
    } catch { }
}
if ($sp) {
    Yes "Enterprise application: '$($sp.DisplayName)'"
    $required = $sp.AppRoleAssignmentRequired
    if ($required) {
        Say "Assignment IS required - every person must be assigned individually or by group."
    } else {
        Say "Assignment is NOT required - any tenant user can sign in, so nobody" Green
        Say "can be locked out by a missing assignment." Green
    }
} else {
    Block "No enterprise application found for application id $clientId."
    Say "Check SDI_CLIENT_ID is the one the portal really uses." White
    $required = $true
}

# Who is assigned, by object id. One call, then everybody is checked against it.
$assigned = @{}
if ($sp) {
    try {
        foreach ($a in (Get-MgServicePrincipalAppRoleAssignedTo -ServicePrincipalId $sp.Id -All -ErrorAction Stop)) {
            $assigned[[string]$a.PrincipalId] = $a.PrincipalType
        }
        Yes "$($assigned.Count) assignment(s) on that application (people and groups)"
    } catch {
        Warn "Could not read the assignment list: $($_.Exception.Message)"
    }
}

# ── 3. Person by person ──────────────────────────────────────────────────────
Head "3. Each person"
foreach ($person in $everyone) {
    $wanted = $person.Email.Trim().ToLower()
    Write-Host ""
    Say "$($person.Email)" White

    $user = $null
    try {
        $user = Get-MgUser -Filter "userPrincipalName eq '$wanted' or mail eq '$wanted'" `
                           -Property "id,displayName,userPrincipalName,mail,accountEnabled" `
                           -ErrorAction Stop | Select-Object -First 1
    } catch { }

    if (-not $user) {
        Block "  No Entra account found with that address."
        # Don't stop at "not found" - go and find them. The likeliest cause is
        # the address being one letter out, and the fix is the right address,
        # which Entra has. Searched by first name, from the address given.
        $first = ($wanted.Split("@")[0].Split(".")[0])
        if ($first.Length -ge 3) {
            $first = $first.Substring(0, 1).ToUpper() + $first.Substring(1)
            try {
                $near = @(Get-MgUser -Filter "startswith(displayName,'$first')" `
                                     -Property "displayName,userPrincipalName,accountEnabled" `
                                     -Top 10 -ErrorAction Stop)
            } catch { $near = @() }
            if ($near.Count -gt 0) {
                Say "  People in Entra whose name starts '$first':" White
                foreach ($n in $near) {
                    $state = if ($n.AccountEnabled) { "" } else { "  (DISABLED)" }
                    Say "    $($n.DisplayName)  ->  $($n.UserPrincipalName)$state" Yellow
                }
                Say "  If one of those is them, use THAT address everywhere." White
            } else {
                Say "  Nobody in Entra has a name starting '$first'. They may not have" White
                Say "  an SDI account at all yet - that is an IT request, not a setting." White
            }
        }
        continue
    }

    $upn = $user.UserPrincipalName
    Yes "  Account exists: $($user.DisplayName)"
    if (-not $user.AccountEnabled) { Block "  The account is DISABLED." }

    # ── THE ONE-KEYSTROKE FAILURE ────────────────────────────────────────────
    # The owner map is keyed on e-mail. A near-miss means the person signs in
    # fine and then sees "your records aren't mapped yet", which reads as a
    # broken app rather than a typo in a setting.
    if ($upn.ToLower() -ne $wanted) {
        Block "  Their real sign-in address is $upn - NOT $wanted"
        Say "  Use $upn everywhere: in SDI_VOICECRM_OWNERS, in WRITERS, and in" White
        Say "  anything you send them." White
    } else {
        Yes "  Sign-in address matches exactly"
    }

    # Assigned to the application?
    if (-not $required) {
        Yes "  Can sign in (the application does not require assignment)"
    } elseif ($assigned.ContainsKey([string]$user.Id)) {
        Yes "  Assigned to the application directly"
    } else {
        $viaGroup = $false
        # DIRECT membership on purpose, not transitive. Entra application
        # assignment does not flow through nested groups: somebody in a group
        # that is inside the assigned group is NOT assigned. "Improving" this
        # to Get-MgUserTransitiveMemberOf would report people as fine who then
        # get the endless sign-in page.
        try {
            foreach ($g in (Get-MgUserMemberOf -UserId $user.Id -All -ErrorAction Stop)) {
                if ($assigned.ContainsKey([string]$g.Id)) { $viaGroup = $true; break }
            }
        } catch { }
        if ($viaGroup) {
            Yes "  Assigned through a group"
        } else {
            Block "  NOT assigned to the application - they would get the sign-in"
            Say "  page back forever, with no error. It looks broken." Red
        }
    }

    # And the server settings, checked against the address Entra actually has.
    $key = $upn.ToLower()
    if ($ownerMap.ContainsKey($key)) {
        Yes "  Mapped to owner '$($ownerMap[$key])' in SDI_VOICECRM_OWNERS"
    } elseif ($ownerMap.ContainsKey($wanted)) {
        Block "  Mapped under $wanted, but their address is $upn - it will not match."
    } else {
        Block "  Not in SDI_VOICECRM_OWNERS - they would see no records at all."
    }

    if ($person.Writes) {
        if ($writerSet -contains $key) { Yes "  Can change records" }
        else { Block "  Should be able to change records and is NOT on the writers list." }
    } else {
        if ($writerSet -contains $key) { Block "  Is READ-ONLY but IS on the writers list." }
        else { Yes "  Read-only, as intended" }
    }
}

# ── 4. What even this cannot see ─────────────────────────────────────────────
Head "4. The one thing Entra cannot answer"
Write-Host ""
Say "SHAREPOINT - each person needs access to Nick's sandbox site, because the" Yellow
Say "app reads the workbook AS THEM and Microsoft refuses them directly." Yellow
Say "Nick grants it. Without it they see 'This pilot uses a tracker you don't"
Say "have access to'."
Write-Host ""
Say "AND THE INITIALS MUST EXIST IN THE SHEET. Open the tracker, look down the" Yellow
Say "AM Owner column, and confirm every token above actually appears there." Yellow
Write-Host ""

Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null

Write-Host ("=" * 74) -ForegroundColor DarkGray
if ($script:Blockers -eq 0) {
    Write-Host "  Everything checkable is in place. Do section 4, then invite them." -ForegroundColor Green
} else {
    Write-Host "  $($script:Blockers) problem(s). Nobody should be invited until these are fixed." -ForegroundColor Red
}
Write-Host ("=" * 74) -ForegroundColor DarkGray
Write-Host ""
exit ([int]($script:Blockers -gt 0))
