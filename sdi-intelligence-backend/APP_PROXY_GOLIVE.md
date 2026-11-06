# SDI Intelligence AM CRM — go-live guide (Entra App Proxy route)

One day's work, in order. Each block ends with a test; do not move on until it
passes. Machine labels on every command: **[SERVER]** = SDI-App01 (10.0.0.5),
**[LAPTOP]** = your laptop, **[BROWSER]** = any browser as stated,
**[ENTRA]** = https://entra.microsoft.com signed in as your admin account,
**[PHONE]** = Nick's phone.

What exists already, so nothing here is building — only switching on:
the app is deployed and in the catalogue as **SDI Intelligence AM CRM**; the
Entra app registration exists (tenant + client IDs are in `.env`); the full
read/write/voice backend is deployed; the public-surface guard is deployed and
dormant until `SDI_PUBLIC_HOSTS` is set.

---

## Block 1 — Sign-in working (~30 min)

### 1.1 New client secret (the old one is burnt)

**[ENTRA]** Identity → Applications → App registrations → *SDI Intelligence
Portal* (the existing registration) → **Certificates & secrets**:

1. Delete the old secret (it was exposed; it must go even though we never used it).
2. **New client secret** → description `sdi-portal-2026`, expiry 180 days → Add.
3. Copy the **Value** column — NOT the Secret ID. The Value is the long random
   string; the Secret ID is a GUID and will fail with `AADSTS7000215`.
   The Value is shown only while you stay on this page.

**[SERVER]** put it in `.env` without it touching the screen or history:

```powershell
# Remove any old/placeholder secret line first:
(Get-Content C:\ClaudeVision\sdi-intelligence-backend\.env) |
  Where-Object { $_ -notmatch '^SDI_CLIENT_SECRET=' } |
  Set-Content C:\ClaudeVision\sdi-intelligence-backend\.env

$s = Read-Host "Paste the client secret VALUE" -AsSecureString
Add-Content C:\ClaudeVision\sdi-intelligence-backend\.env ("SDI_CLIENT_SECRET=" + [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)))
Restart-Service SDIIntelligence
```

### 1.2 Graph permission for the workbook

**[ENTRA]** same app registration → **API permissions**:

1. Add a permission → Microsoft Graph → **Delegated** → `Files.Read.All` → Add.
2. Click **Grant admin consent for SDI** → Yes. The Status column must show a
   green tick.

### 1.3 Test sign-in and the first real read

**[SERVER]** in the server's own browser (sign-in only works at `localhost`
until the HTTPS address exists):

1. `http://localhost:8071/app/` → you should be bounced to Microsoft sign-in →
   sign in → back to the catalogue with your name in the chip.
2. Open **SDI Intelligence AM CRM**. Success = Nick's rows on screen.

If instead of rows you get an explanation panel, it names the exact fix.
The three likely ones (my config values are best guesses at his sandbox):

| Screen says | Fix in `.env` |
|---|---|
| Workbook not found at '…' | The file is in a folder — set `SDI_VOICECRM_XLSX=General/CRM TEST - 2026 Account and Project Tracker.xlsx` (or whatever the folder is; open the sandbox's Documents library and read the path) |
| Site not found / 404 on site | `SDI_VOICECRM_SITE` — copy the site's real URL path from the browser: everything is `sdidisplays.sharepoint.com:/sites/<exactly-what-the-URL-says>` |
| Read fine, 0 records, "no record has AM Owner = NG" | The header cell text differs — open the sheet, read the owner column's header exactly, set `SDI_VOICECRM_OWNER_FIELD` to match |

After any `.env` change: `Restart-Service SDIIntelligence`, refresh the page.

---

## Block 2 — The voice brain: Anthropic API key (~20 min)

1. **[BROWSER]** https://console.anthropic.com → sign in / sign up (this is the
   developer console, separate from any Claude chat login).
2. **Billing** → buy the minimum credit (about $5 — months of pilot usage; each
   voice exchange costs fractions of a penny). No auto-reload.
3. **API Keys** → **Create Key** → name `sdi-intelligence-server` → copy the
   `sk-ant-…` value immediately (shown once).
4. **[SERVER]**:

```powershell
$k = Read-Host "Paste ANTHROPIC_API_KEY" -AsSecureString
Add-Content C:\ClaudeVision\sdi-intelligence-backend\.env ("ANTHROPIC_API_KEY=" + [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($k)))
Restart-Service SDIIntelligence
```

5. **Test — full voice rehearsal, [SERVER] browser** at
   `http://localhost:8071/app/voice-crm.html`:
   - Badge row shows **Voice brain ready**.
   - Tap the mic (allow microphone), ask: *"what's happening with …"* one of
     Nick's clients → it should answer out loud from the real rows.
   - Try an update: *"set the status on … to test"* → it reads the change back
     and asks for a yes → **it will refuse to write** with "writes_disabled".
     That refusal is the test passing: the loop works end to end and the write
     gate holds.

In the console, Settings → Limits: set a monthly spend cap (e.g. $20) — belt
and braces.

---

## Block 3 — Published to the internet via Entra Application Proxy (~1–2 h)

Why App Proxy over the Cloudflare tunnel: you have Entra ID P1 (it is
included), you are tenant admin so there is no third party or DNS conversation,
and pre-authentication means **nobody reaches the server at all without first
passing Microsoft sign-in + MFA** — the app's own sign-in then runs behind
that. Outbound-only, like the tunnel: nothing inbound opens on the firewall.

### 3.1 Install the connector on the server

1. **[ENTRA]** Identity → Applications → Enterprise applications →
   **Application proxy** (left menu). If it offers "Enable application proxy",
   enable it.
2. **Download connector service** → run the downloaded
   `MicrosoftEntraPrivateNetworkConnectorInstaller` **[SERVER]** → sign in as
   your admin account when prompted.
3. Back in the portal, the connector appears under the **Default** connector
   group with status **Active** (give it two minutes). The connector only makes
   outbound 443 connections; if the portal never shows Active, the server's
   firewall is blocking outbound 443 to `*.msappproxy.net` — allow it.

### 3.2 Publish the app

**[ENTRA]** Identity → Applications → Enterprise applications → **New
application** → **Add an on-premises application** (if the button instead says
"Configure App proxy", same thing):

| Setting | Value |
|---|---|
| Name | `SDI Intelligence` |
| Internal URL | `http://10.0.0.5:8071/` |
| External URL | accept the generated `https://sdiintelligence-<tenant>.msappproxy.net/` (a custom `apps.wearesdi.com` needs a certificate + DNS — do it later, nothing else changes) |
| Pre-authentication | **Microsoft Entra ID** |
| Connector group | Default |
| Translate URLs in headers | **No** ← important: the backend must see the external hostname, or the public-surface guard (next step) cannot tell inside from outside |
| Translate URLs in application body | No |

Save, and note the external URL — it is the company's app address from here on.

### 3.3 Tell the backend about its public face

**[SERVER]** — replace `<external-host>` with the hostname from 3.2 (no
`https://`, no trailing slash — e.g. `sdiintelligence-sdi.msappproxy.net`):

```powershell
Add-Content C:\ClaudeVision\sdi-intelligence-backend\.env @"

SDI_PUBLIC_HOSTS=<external-host>
SDI_REDIRECT_URI=https://<external-host>/auth/callback
"@
```

Also in `.env`: if a `SDI_COOKIE_SECURE=no` line exists, delete it (we are on
HTTPS now), and set `SDI_ALLOW_API_KEY=no` if present as `yes`. Then:

```powershell
Restart-Service SDIIntelligence
```

`SDI_PUBLIC_HOSTS` arms the guard that is already deployed: requests arriving
under the external hostname can reach **only** the app portal, sign-in, and
the AM CRM API. The intranet portal, estimating pages, file browser — 404 from
outside, unchanged from inside.

### 3.4 The HTTPS redirect URI

**[ENTRA]** App registrations → *SDI Intelligence Portal* → **Authentication**
→ Add URI: `https://<external-host>/auth/callback` → Save. (Keep the
`http://localhost:8071/auth/callback` one for server-side testing.)

### 3.5 Who gets in, and MFA

1. **[ENTRA]** Enterprise applications → the new `SDI Intelligence` app proxy
   app → Properties → **Assignment required = Yes** → Save.
2. Same app → **Users and groups** → Add: you and Nick Garrish (a group later
   for the whole company).
3. Do the same two steps on the *SDI Intelligence Portal* enterprise app (the
   registration's own service principal) so the app-level sign-in matches.
4. MFA: Identity → Protection → **Conditional Access** → New policy:
   - Name: `MFA — SDI Intelligence`
   - Users: the same users/group
   - Target resources: both apps above
   - Grant: **Require multifactor authentication**
   - Enable policy: **On** → Create.
   (If the tenant has security defaults or an existing all-apps MFA policy,
   this is already covered — check before doubling up.)

### 3.6 Test from outside

**[LAPTOP]** on a phone hotspot or any non-SDI network (this matters — from
inside, the test proves nothing):

1. `https://<external-host>/app/` → Microsoft sign-in → MFA prompt → catalogue.
2. Open **SDI Intelligence AM CRM** → Nick's rows → mic works (HTTPS = the
   browser will now allow the microphone).
3. Negative test: `https://<external-host>/` (the intranet portal root) must
   return **404**. If it shows the intranet portal, stop — `SDI_PUBLIC_HOSTS`
   does not match the hostname the backend is seeing; re-check 3.2's
   "Translate URLs in headers = No" and the exact hostname.

---

## Block 4 — Nick's phone (~10 min of his time)

Send him the external URL. On his phone:

**iPhone:** Safari (must be Safari) → open the URL → Microsoft sign-in with
his normal SDI account → MFA (Authenticator prompt) → once the app portal
loads: **Share button → Add to Home Screen → Add**. An *SDI Intelligence*
icon appears like any other app, launching full-screen.

**Android:** Chrome → same URL and sign-in → the **Install app** banner (or
⋮ menu → *Add to Home screen → Install*).

First launch from the icon: tap **SDI Intelligence AM CRM** → tap the mic →
Safari/Chrome asks to allow the microphone once → talk. Sign-in renews itself
silently; after long gaps Microsoft may re-prompt — that is Conditional Access
doing its job, not a fault.

What he can do immediately: ask anything of his records by voice and get
spoken answers. Updates will read back and then refuse politely — writes are
still gated until Block 5.

---

## Block 5 — Turning writing on (after the demo, with Nick's yes)

1. Demo the loop to Nick on the sandbox (the refusal at the end included).
2. He approves. **[ENTRA]** API permissions → add Delegated
   **Files.ReadWrite.All** → Grant admin consent. Sign out/in on the app
   (tokens carry the scopes from sign-in time).
3. **[SERVER]** `.env`:

```ini
SDI_VOICECRM_WRITE=yes
SDI_VOICECRM_APPROVED_BY=Nick Garrish, 2026-10-07
SDI_GRAPH_SCOPES=User.Read Files.ReadWrite.All
```

   `Restart-Service SDIIntelligence`.
4. First live write, with Nick: he says a real change, hears it back, says
   yes, then **both of you open the workbook and look at the cell**. Then
   open the app's journal (`/api/voicecrm/journal`) and show him the audit
   entry — who, when, old value, new value.

Still true afterwards: only columns in the allow-list (`Status`, `Action
date`, `End date` by default) can ever change, only rows whose AM Owner is NG,
only in the sandbox workbook named in `.env`, every change journalled, and a
repeated confirm can never write twice. The live tracker is not configured
anywhere and cannot be touched.

---

## End-state checklist

- [ ] Sign-in at localhost shows Nick's rows (Block 1)
- [ ] Voice rehearsal on the server browser, write refused at the gate (Block 2)
- [ ] External URL serves the app, 404s the intranet, MFA enforced (Block 3)
- [ ] Nick's phone has the icon and he has spoken to it (Block 4)
- [ ] Writes on, first confirmed change seen in the workbook + journal (Block 5)

Later, not blocking: custom hostname `apps.wearesdi.com` on the App Proxy app
(needs a certificate + one CNAME), filling in Nick's Project codes, the morning
outbound-call stage from his architecture doc, credential rotations preflight
still flags, and re-uploading the fixed Intune hosts script.
