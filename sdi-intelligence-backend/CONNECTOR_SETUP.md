# SDI Tracker connector: setting it up for Nick

The connector (`voicecrm_connector.py`) lets Nick use the tracker from his
ChatGPT app (or the Claude app): ChatGPT's voice and conversation, our back
end. Every lookup and change runs through the same code as the AM CRM web app
- owner check, writers only, formula and owner columns locked, read-back,
plain yes, version check, save once, journal - and every change shows in the
web app's **Recent activity**, marked "via ChatGPT / Claude".

It is **off** until step 5. Nothing below changes the web app.

```
Nick's phone ─ ChatGPT app ─▶ OpenAI cloud ──(Entra token for Nick)──▶ App Proxy (pass-through)
        ──▶ SDI-App01:8073  voicecrm_connector.py ──(checks the token, then Graph as Nick)──▶ SharePoint tracker
```

## 1. Server: two Python packages (once)

On SDI-App01, PowerShell as admin:

```powershell
C:\ClaudeVision\sdi-intelligence-backend\.venv\Scripts\python.exe -m pip install "mcp==2.3.0" "PyJWT[crypto]>=2.8"
```

(They are also in `requirements.txt`.)

## 2. Entra (portal.azure.com → Microsoft Entra ID → App registrations)

**a. The existing *SDI Intelligence* registration** (its id is `SDI_CLIENT_ID` in the server's `.env`):

1. **Expose an API** → Application ID URI → **Add** → accept `api://<SDI_CLIENT_ID>` → Save.
2. **Add a scope**: name `tracker.access`; who can consent **Admins and users**;
   display name *Use the SDI tracker as you*; description *Look up and change your
   tracker records through SDI's rules*; State **Enabled**.

Its Microsoft Graph permissions stay as they are: the connector uses them on
Nick's behalf, exactly as the web app does.

**b. A new registration, *SDI Tracker for ChatGPT***: this is what ChatGPT signs in with.

1. **New registration** → name *SDI Tracker for ChatGPT* → *Accounts in this
   organizational directory only* → Register. Note its **Application (client) ID**.
2. **Certificates & secrets** → New client secret (12 months) → copy the **Value**
   now (it is shown once). It goes into ChatGPT in step 6, nowhere else.
3. **API permissions** → Add → *My APIs* → *SDI Intelligence* → Delegated →
   `tracker.access` → Add → **Grant admin consent**.
4. **Authentication** → Add a platform → Web → the **callback URL ChatGPT shows**
   when you create the connector in step 6 (come back and add it then).
5. **Enterprise applications** → *SDI Tracker for ChatGPT* → Properties →
   **Assignment required: Yes** → Users and groups → add **Nick** and **James**.
   Nobody else can connect it.

For the Claude app later: the same again as *SDI Tracker for Claude*, with the
callback URL Claude shows.

## 3. App Proxy (Entra ID → Enterprise applications → New → Add an on-premises application)

| Setting | Value |
|---|---|
| Name | SDI Tracker connector |
| Internal URL | `http://10.0.0.5:8073/` |
| External URL | `https://sdi-tracker-sdidisplays.msappproxy.net/` (or what the portal offers) |
| Pre-authentication | **Passthrough** |
| Connector group | Default |

Why pass-through: the caller is OpenAI's cloud presenting Nick's token, not a
browser with a sign-in cookie. The connector checks every request itself
(signature, SDI tenant, audience, `tracker.access`, which app asked) and
refuses anything else before any tool runs.

## 4. The server's `.env`

Add (keep everything else as it is):

```ini
SDI_CONNECTOR_ENABLED=yes
SDI_CONNECTOR_URL=https://sdi-tracker-sdidisplays.msappproxy.net/mcp
SDI_CONNECTOR_CLIENTS=<Application ID of SDI Tracker for ChatGPT>
```

Optional: `SDI_CONNECTOR_PORT` (default 8073). Writers, write switch and
approval are the web app's own settings (`SDI_VOICECRM_WRITERS` and so on).

## 5. The Windows service (PowerShell as admin, on SDI-App01)

```powershell
$nssm = "C:\tools\nssm-2.24\win64\nssm.exe"
$dir  = "C:\ClaudeVision\sdi-intelligence-backend"
& $nssm install SDITrackerConnector "$dir\.venv\Scripts\python.exe" "$dir\voicecrm_connector.py"
& $nssm set SDITrackerConnector AppDirectory $dir
& $nssm set SDITrackerConnector DisplayName "SDI Tracker connector (ChatGPT / Claude)"
& $nssm set SDITrackerConnector Start SERVICE_AUTO_START
& $nssm set SDITrackerConnector AppExit Default Restart
& $nssm set SDITrackerConnector AppStdout "C:\ClaudeVision\output\logs\sdi_connector.log"
& $nssm set SDITrackerConnector AppStderr "C:\ClaudeVision\output\logs\sdi_connector_error.log"
New-NetFirewallRule -DisplayName "SDI Tracker connector 8073" -Direction Inbound -LocalPort 8073 -Protocol TCP -Action Allow
Start-Service SDITrackerConnector
Get-Service SDITrackerConnector
```

From then on `Deploy-AMCRM.ps1` copies its files and restarts it with the main app.

**Check it** (from anywhere):

```powershell
Invoke-RestMethod https://sdi-tracker-sdidisplays.msappproxy.net/.well-known/oauth-protected-resource/mcp
```

should name `login.microsoftonline.com/<tenant>/v2.0` and `tracker.access`; and a
request to `/mcp` with no token should get **401**.

## 6. ChatGPT (workspace admin, at a desk)

Create a custom connector / app in the SDI workspace (the menu names change;
the values are what matter):

| Field | Value |
|---|---|
| Name | SDI Tracker |
| URL | `https://sdi-tracker-sdidisplays.msappproxy.net/mcp` |
| Authentication | OAuth |
| Client ID / secret | from *SDI Tracker for ChatGPT* (step 2b) |
| Authorization URL | `https://login.microsoftonline.com/<tenant id>/oauth2/v2.0/authorize` |
| Token URL | `https://login.microsoftonline.com/<tenant id>/oauth2/v2.0/token` |
| Scope | `api://<SDI_CLIENT_ID>/tracker.access offline_access` |

Copy the callback URL ChatGPT shows into step 2b.4. Publish it to the workspace
(or to Nick and James).

**Nick, once:** ChatGPT → Apps → SDI Tracker → Connect → Microsoft sign-in with
MFA. If ChatGPT offers "always allow" for saving changes, choose it, so he is
never asked to tap while driving: our server still saves only on his plain yes.

## Switching it off

Any one of these, immediately:
- `Stop-Service SDITrackerConnector` (and `SDI_CONNECTOR_ENABLED=no` so it stays off);
- Entra → *SDI Tracker for ChatGPT* → Properties → **Enabled for users to sign in: No**;
- remove Nick from its users, or revoke his sessions.

## Logs

`C:\ClaudeVision\output\logs\sdi_connector.log`: one line per action
(`[connector] tool=… user=… secs=…`), and every refused token with the reason
(`[connector.auth] refused: wrong scope …`). Changes are in the journal, as for
the web app.
