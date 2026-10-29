# TTI Despatch in ChatGPT: setting it up for Selina, Lee, Sue, Liam and James

`tti_connector.py` lets them ask the TTI Despatch Plan the same six questions
the web app answers, and search the TTi folders on W: by name (Liam's request:
Design, Production and Prototype), from the ChatGPT app — typed or out loud. It runs
the same code as the web view (`tti_search.py` over `tti_data.py`), so there is
one set of rules about what the workbook means rather than two.

**Every tool reads. Nothing in it can write a cell, book anything in with TTI,
or send email.** The morning summary comes back as words for a person to send.

It is **off** until step 5. Nothing below changes the web app, the AM CRM
connector, or Nick's tracker.

```
Selina's phone ─ ChatGPT app ─▶ OpenAI cloud ──(Entra token for Selina)──▶ App Proxy (pass-through)
        ──▶ SDI-App01:8074  tti_connector.py ──(checks the token, checks SDI_TTI_OIDS,
                                                then Graph as Selina)──▶ SharePoint Despatch Plan
```

## Which machine runs what

| Step | Where |
|---|---|
| 1 Python packages | **Server** (SDI-App01), PowerShell as admin |
| 2 Entra | **Any browser**, as a tenant admin |
| 3 App Proxy | **Any browser**, as a tenant admin |
| 4 `.env` | **Server**, edit the file on SDI-App01 |
| 5 Windows service | **Server**, PowerShell as admin |
| 6 ChatGPT connector | **Laptop** (ChatGPT workspace admin), then each person once on their own phone |
| Deploying the code | **Laptop**, VPN on: `.\sdi-intelligence-backend\deploy\Deploy-AMCRM.ps1` |

## 0. Before anything: who is allowed

The connector uses **`SDI_TTI_OIDS`** — the same list the web app's TTI view
uses, so nobody can be in on one surface and out on the other. It holds Entra
**object IDs**, comma separated.

Known so far:

| Person | Object ID |
|---|---|
| Sue Rogers | `cc53597a-c1b5-4bf9-b862-f63f7392ff81` |
| James Gray (ordinary account, not admin) | `5acf6b37-147f-4468-bdb1-ecc3da1f1076` |
| Selina Kuddus | **needed** |
| Lee Merril | **needed** |
| Liam | **needed** |

To find one: Entra ID → Users → the person → **Object ID** on their overview. Or
the person opens `https://sdiintelligence-sdidisplays.msappproxy.net/api/me`
signed in with their usual account and reads the `"oid"` value.

An empty list admits **nobody**, on both surfaces, and the connector refuses to
start rather than run as a service that refuses every call.

## 1. Server: the Python packages (once)

Already installed if the AM CRM connector is running. Otherwise, on SDI-App01:

```powershell
C:\ClaudeVision\sdi-intelligence-backend\.venv\Scripts\python.exe -m pip install "mcp==2.3.0" "PyJWT[crypto]>=2.8"
```

## 2. Entra (portal.azure.com → Microsoft Entra ID → App registrations)

**a. The existing *SDI Intelligence* registration → Expose an API.** It is an
App Proxy app, so its Application ID URI is
`https://SDIIntelligence-sdidisplays.msappproxy.net`, not `api://<id>`. Leave
that URI alone: outside access to the intranet depends on it. App Proxy's own
`user_impersonation` scope is there too; leave that alone as well.

If `tracker.access` is not listed, **Add a scope**:
scope name `tracker.access`, *Admins only*, admin consent display name
*Read SDI Intelligence as the signed-in person*, description *Lets an approved
app (ChatGPT, Claude) read SDI Intelligence data as the person signed in. It
cannot sign anyone else in.*, Enabled → Add scope. Its full name is then
`https://SDIIntelligence-sdidisplays.msappproxy.net/tracker.access`, which goes
in `.env` in step 4 as `SDI_TTI_CONNECTOR_SCOPE_URI`.

**b. A new registration, *SDI TTI Despatch for ChatGPT***. A separate one from
*SDI Tracker for ChatGPT* so the two can be switched off independently and so
the assigned-users list on each names the right people.

1. **New registration** → name *SDI TTI Despatch for ChatGPT* → *Accounts in
   this organizational directory only* → Register. Note its **Application
   (client) ID**.
2. **Certificates & secrets** → New client secret (12 months) → copy the
   **Value** now (it is shown once). It goes in the server's `.env` in step 4
   and nowhere else — in particular, not into ChatGPT, and not into an email.
3. **API permissions** → Add → *My APIs* → *SDI Intelligence* → Delegated →
   `tracker.access` → Add → **Grant admin consent**.
4. **Authentication** → Add Redirect URI → Web →
   `https://sdittidespatch-sdidisplays.msappproxy.net/oauth/callback`
   (the connector's own sign-in front door, below).
5. **Enterprise applications** → *SDI TTI Despatch for ChatGPT* → Properties →
   **Assignment required: Yes** → Users and groups → add **Selina, Lee, Sue, Liam and
   James**. Nobody else can connect it.

Step 5 and `SDI_TTI_OIDS` are two separate doors, deliberately. Entra decides
who may connect the app at all; the object-ID list decides who gets an answer.
Either one alone keeps somebody out.

The same registration serves the Claude app.

## 3. App Proxy (Entra ID → Enterprise applications → New → Add an on-premises application)

| Setting | Value |
|---|---|
| Name | SDI TTI Despatch connector |
| Internal URL | `http://sdi-app01:8074/` (App Proxy refuses an IP address) |
| External URL | `https://sdittidespatch-sdidisplays.msappproxy.net/` (no hyphen allowed in the prefix) |
| Pre-authentication | **Passthrough** |
| Connector group | Default |

Why pass-through: the caller is OpenAI's cloud presenting the person's token,
not a browser with a sign-in cookie. The connector checks every request itself
— signature, SDI tenant, audience, `tracker.access`, which app asked, and that
the token is about a *person* rather than a daemon — and then checks the
object-ID list, before any tool runs.

## 4. The server's `.env`

Add, keeping everything else as it is:

```ini
SDI_TTI_CONNECTOR_ENABLED=yes
SDI_TTI_CONNECTOR_URL=https://sdittidespatch-sdidisplays.msappproxy.net/mcp
SDI_TTI_CONNECTOR_CLIENTS=<Application ID of SDI TTI Despatch for ChatGPT>
SDI_TTI_CONNECTOR_OAUTH_CLIENT=<Application ID of SDI TTI Despatch for ChatGPT>
SDI_TTI_CONNECTOR_OAUTH_SECRET=<its client secret Value>
SDI_TTI_CONNECTOR_SCOPE_URI=https://SDIIntelligence-sdidisplays.msappproxy.net/tracker.access
SDI_TTI_CONNECTOR_AUDIENCE=https://SDIIntelligence-sdidisplays.msappproxy.net
```

The last two are the scope's full name from step 2a, and the audience Entra
writes into the token for it. Without them the connector would ask for
`api://<id>/tracker.access`, which this App Proxy app does not answer to.

and make sure these are already there, from the web view:

```ini
SDI_TTI_ENABLED=yes
SDI_TTI_OIDS=<Selina>,<Lee>,<Liam>,cc53597a-c1b5-4bf9-b862-f63f7392ff81,5acf6b37-147f-4468-bdb1-ecc3da1f1076
SDI_TTI_PLAN_SITE=sdidisplays.sharepoint.com:/sites/SUESOSOD
SDI_TTI_PLAN_PATH=General/TTI Delivery Schedule 2021 V3.xlsx
```

For the TTi folder search (web tab and the `tti_find_files` tool), the server
needs W:'s network path, and an index built on a schedule:

```ini
SDI_DRIVE_MAP=K=\\sdi-dc01\shareddata$\Shared;W=<Remote name from "net use W:" on a PC>
```

Keep the `K=` part: this line replaces the default. Then run
`tools\tti_index_folders.py` once by hand and schedule it (twice a day); see
the TTI user guide on the app portal for what people see. Optional:
`SDI_TTI_FOLDERS` (default: the three TTi folders), `SDI_TTI_FOLDER_INDEX`
(default `C:\SDIIntelligence\tti\tti_folders.sqlite3`).

Optional: `SDI_TTI_CONNECTOR_PORT` (default 8074).
`SDI_TTI_PLAN_TTL` (default `0`) is how many seconds a parse of the workbook may
be reused **without asking SharePoint at all**. Leave it at 0 unless the views
feel slow: at 0, every single request still asks SharePoint about the file as
that person, and only the download and the parse are skipped when its eTag says
nothing has been saved since. Setting it above 0 trades freshness for speed, and
a stale answer is the failure this app cannot afford.

`.env` is read **once at startup**, so a change needs a restart of both the main
service and this one.

## 5. The Windows service (PowerShell as admin, on SDI-App01)

```powershell
$nssm = "C:\Tools\nssm.exe"
$dir  = "C:\ClaudeVision\sdi-intelligence-backend"
& $nssm install SDITTIConnector "$dir\.venv\Scripts\python.exe" "$dir\tti_connector.py"
& $nssm set SDITTIConnector AppDirectory $dir
& $nssm set SDITTIConnector DisplayName "SDI TTI Despatch connector (ChatGPT / Claude)"
& $nssm set SDITTIConnector Start SERVICE_AUTO_START
& $nssm set SDITTIConnector AppExit Default Restart
& $nssm set SDITTIConnector AppStdout "C:\ClaudeVision\output\logs\sdi_tti_connector.log"
& $nssm set SDITTIConnector AppStderr "C:\ClaudeVision\output\logs\sdi_tti_connector_error.log"
New-NetFirewallRule -DisplayName "SDI TTI Despatch connector 8074" -Direction Inbound -LocalPort 8074 -Protocol TCP -Action Allow
Start-Service SDITTIConnector
Get-Service SDITTIConnector
```

From then on `Deploy-AMCRM.ps1` copies its files and restarts it with the main
app.

**If it will not start**, read
`C:\ClaudeVision\output\logs\sdi_tti_connector_error.log`. It says in one line
what is missing — an empty `SDI_TTI_OIDS` and a missing `SDI_TTI_CONNECTOR_URL`
both stop it on purpose rather than running as something that refuses every
call.

**Check it** (from anywhere):

```powershell
Invoke-RestMethod https://sdittidespatch-sdidisplays.msappproxy.net/.well-known/oauth-protected-resource/mcp
Invoke-RestMethod https://sdittidespatch-sdidisplays.msappproxy.net/.well-known/oauth-authorization-server
```

The first should name the connector's own address as its authorization server
and `tracker.access`; the second should list `/authorize`, `/token` and
`/register`. A request to `/mcp` with no token should get **401**.

## 6. ChatGPT

**Workspace admin, once, at a desk.** Create a second custom connector in the
SDI workspace (the menu names change; the values are what matter):

| Field | Value |
|---|---|
| Name | SDI TTI Despatch |
| Server URL | `https://sdittidespatch-sdidisplays.msappproxy.net/mcp` |
| Authentication | OAuth |
| Advanced → Registration method | **Dynamic Client Registration** (ChatGPT registers itself; no client ID or secret goes into ChatGPT) |
| Advanced → everything else | as discovered; leave Resource as the server URL |

**Each person, once, on their own phone.** ChatGPT → Apps → SDI TTI Despatch →
Connect → "Connect SDI TTI Despatch to ChatGPT?" → **Continue** → their SDI
Microsoft account → MFA. The account picker always appears, so a browser signed
in to another Microsoft account cannot be used by mistake.

Because every tool is read-only, ChatGPT should not ask for confirmation before
each lookup. If it offers "always allow", that is safe here: there is nothing in
this connector that changes anything.

## 7. Proving voice actually works

Voice chat working is not the same as voice **using the tools**. Check all three:

1. **Typed, in ChatGPT:** "Where is TTI order 15194?" → it should name the sheet
   and row, e.g. *Oct 26 WK 40, row 5*, and say when the plan was last saved.
2. **Spoken:** the same question out loud. The reply must contain the sheet and
   row — if it answers in general terms without them, it answered from the
   conversation rather than from the workbook, and that is the failure mode to
   catch.
3. **Spoken, with a hedge:** "What is leaving SDI on Thursday?" If any departure
   date in the plan is unreadable, the spoken answer must say so in the same
   sentence ("…but N lines have a date I could not read"). That caveat is
   written into the answer rather than left to the assistant, because a voice
   answer has no footer for somebody to notice afterwards.

4. **The folders:** "Find the TTi drawings for 9287" → it should give full
   `W:\…` paths and say how old the folder index is.

If a tool is never called, the usual causes are: the person is not in
`SDI_TTI_OIDS` (the reply says so plainly — read the log line
`state=not_named`), or the connector is not Connected in their ChatGPT app.

## Switching it off

Any one of these, immediately:

- `Stop-Service SDITTIConnector` (and `SDI_TTI_CONNECTOR_ENABLED=no` so it stays
  off);
- Entra → *SDI TTI Despatch for ChatGPT* → Properties → **Enabled for users to
  sign in: No**;
- remove the person from `SDI_TTI_OIDS` and restart — that closes the web view
  for them as well, which is usually what is wanted;
- remove them from the app's assigned users, or revoke their sessions.

Switching this off does not affect the AM CRM connector, and switching that off
does not affect this one.

## Logs

`C:\ClaudeVision\output\logs\sdi_tti_connector.log`: one line per lookup
(`[tti-connector] tool=… user=… secs=…`), every refused token with the reason
(`[tti-connector.auth] refused: wrong scope …`), and every refusal for somebody
not on the list (`state=not_named`). Sign-in codes are kept out of the access
log. There is no journal, because there is nothing to journal: nothing here
changes anything.
