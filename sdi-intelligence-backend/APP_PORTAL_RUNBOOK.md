# SDI Intelligence App Portal — Runbook

Everything needed to run the portal, put it behind Microsoft sign-in, get it onto
phones, add an app, and expose it safely.

Written for someone with tenant admin. Where a step needs a decision rather than
a click, it says so.

---

## 0. Before anything else — rotate two credentials

These are live in the repository right now and this portal is about to become
reachable from more places, so do this first.

1. **`SDI_API_KEY` is hardcoded in `sdi-intelligence-portal.html`** (search for
   `const API_KEY`). Every browser that loads the portal receives it.
2. **`.env` is tracked in git**, including `SDI_DB_PASSWORD` (the AIBot login to
   SDILive), `BH_CLIENT_SECRET` and `BH_PAT`.

Adding `.env` to `.gitignore` (already done) does not untrack it and does not
remove it from history. **Rotating the values is the fix.** Specifically:

- Generate a new `SDI_API_KEY`, put it in `.env` only, and delete the constant
  from the portal HTML — once SSO is on (step 2) the page no longer needs a key,
  because the browser sends a session cookie instead.
- Change the AIBot SQL password and update `.env`.
- Regenerate the BrightHR PAT / client secret.

---

## 1. Run it

On the server, from `sdi-intelligence-backend`:

```powershell
C:\ClaudeVision\.venv\Scripts\python.exe -m pip install fastapi uvicorn python-dotenv msal itsdangerous httpx
C:\ClaudeVision\.venv\Scripts\python.exe app.py
```

It reads `.env` next to `app.py` and listens on `SDI_HOST`:`SDI_PORT`
(default `0.0.0.0:8071`).

| URL | What it is |
|-----|------------|
| `http://<host>:8071/` | The intranet portal (unchanged) |
| `http://<host>:8071/app/` | The new app portal — **note the trailing slash** |
| `http://<host>:8071/api/services` | The app catalogue as JSON |
| `http://<host>:8071/api/me` | Who the server thinks you are |

If `/app/` loads but looks unstyled or won't install, you almost certainly
dropped the trailing slash. `/app` redirects, but a bookmark to `/app` saved
before this fix may be cached.

To run it as a service rather than a console window, the existing
`SDI-Intelligence-WindowsService.ps1` in this folder already does that — point it
at the same command.

---

## 2. Register the app in Entra (Day 2)

### 2.1 Create the registration

1. <https://entra.microsoft.com> → **Applications** → **App registrations** →
   **New registration**.
2. Name: `SDI Intelligence Portal`.
3. Supported account types: **Accounts in this organizational directory only**
   (single tenant).
4. Redirect URI: platform **Web**, value
   `http://localhost:8071/auth/callback`.
   Add the real external one later, in step 5 — a registration can hold several.
5. **Register**.

From the Overview page copy:

- **Application (client) ID** → `SDI_CLIENT_ID`
- **Directory (tenant) ID** → `SDI_TENANT_ID`

### 2.2 Client secret

**Certificates & secrets** → **Client secrets** → **New client secret**. Set an
expiry you will actually diary (24 months maximum).

Copy the **Value**, not the Secret ID — the value is shown once and never again.
→ `SDI_CLIENT_SECRET`

### 2.3 Permissions

**API permissions** → **Add a permission** → **Microsoft Graph** →
**Delegated permissions**:

- `User.Read` — already there by default. Enough for sign-in alone.
- `Sites.Read.All` — add this only when you wire up Nick's app (step 4).

Then **Grant admin consent for SDI Displays**. Without that click, every user
gets a consent prompt they cannot approve.

> **On `Sites.Read.All` being broad:** with *delegated* permissions the app acts
> **as the signed-in person and can never see more than they can**. Nick signing
> in gives the app Nick's access, not the tenant's. That is the whole reason this
> is built on delegated rather than application permissions — an application
> permission genuinely would grant tenant-wide access and would need
> `Sites.Selected` scoped to one site.

### 2.4 Restrict who can sign in

Do this at the enterprise app, not in code:

1. **Enterprise applications** → find `SDI Intelligence Portal` → **Properties**.
2. Set **Assignment required?** to **Yes** → Save.
3. **Users and groups** → **Add user/group** → assign the people or a security
   group (e.g. `SDI-Intelligence-Users`).

Anyone not assigned now gets a clean "not assigned" message from Microsoft
instead of reaching the portal.

`SDI_ALLOWED_GROUPS` in `.env` does a second, in-app check. It is optional and
needs **Token configuration → Add groups claim → Security groups**. Leave it
empty unless you want belt and braces — and be aware that a user in more than
~200 groups gets no `groups` claim at all and would be denied.

### 2.5 Fill in `.env` and restart

```ini
SDI_TENANT_ID=<directory tenant id>
SDI_CLIENT_ID=<application client id>
SDI_CLIENT_SECRET=<the secret VALUE>
SDI_SESSION_SECRET=<any long random string — signs the session cookie>
SDI_REDIRECT_URI=http://localhost:8071/auth/callback
SDI_GRAPH_SCOPES=User.Read
SDI_SESSION_HOURS=10

# Only while testing over plain http on the intranet. Remove once on HTTPS.
SDI_COOKIE_SECURE=no

# Keep the old shared key working for scheduled scripts during the changeover.
# Set to no once nothing uses it.
SDI_ALLOW_API_KEY=yes
```

Restart. On startup the log should no longer say
`[WARN] Entra SSO is NOT configured`.

Browse to `http://localhost:8071/` — you should bounce to Microsoft, sign in,
and land back on the portal. `/api/me` then shows your name.

### 2.6 Retire the shared key

Once every scheduled script (Task Scheduler jobs, the estimating host) either
signs in properly or has been moved onto its own identity:

```ini
SDI_ALLOW_API_KEY=no
```

From then on `X-SDI-Key` is dead and every request is attributable to a person.
That is the point of the whole exercise — it is what makes "Nick changed P1001
at 08:47" a fact you can evidence rather than an assumption.

---

## 3. Get it onto phones

### 3.1 The hard prerequisite: HTTPS

A Progressive Web App installs and works offline only in a **secure context** —
`https://`, or `localhost`. Over `http://10.0.0.5:8071`:

- iOS Safari will **not** offer "Add to Home Screen" as an app,
- the service worker will **not** register, so no offline,
- `SDI_COOKIE_SECURE=no` is required or sign-in breaks.

So installation on phones effectively requires step 5 (a real HTTPS hostname)
first. You can browse to it over http in the meantime; it just won't install.

### 3.2 iPhone / iPad

Must be **Safari** — Chrome and Edge on iOS cannot install web apps.

1. Open the portal URL in Safari.
2. Sign in with the work account.
3. **Share** (square with the up arrow) → **Add to Home Screen** → **Add**.

It appears as "SDI" with the yellow S icon and opens full screen with no browser
chrome.

### 3.3 Android

1. Open the URL in Chrome and sign in.
2. Either take the **Install app** prompt, or **⋮** → **Add to Home screen** →
   **Install**.

### 3.4 Desktop

Chrome or Edge show an install icon in the address bar. Useful for anyone who
wants it in the taskbar.

### 3.5 Rolling it out

There is nothing to distribute — no store, no MDM package, no APK. Send the URL.
If you would rather push it, Intune can deploy a **web link** to managed devices,
which is the same URL with a nicer icon.

---

## 4. Add an app to the portal

### 4.1 An entry that is just described

Edit **`services.json`**. One object, and both portals pick it up:

```json
{
  "id": "my-app",
  "name": "My App",
  "status": "Planned",
  "cls": "c-plan",
  "category": "Internal tools",
  "surface": "both",
  "desc": "One line shown on the card.",
  "detail": "The longer description. HTML is allowed.",
  "inputs": ["..."], "outputs": ["..."], "tech": ["..."],
  "phase": "Phase 2",
  "invoke": "How someone actually runs it."
}
```

- `cls` sets the chip colour: `c-done` green, `c-prog` yellow, `c-plan` grey.
- `category` groups it. Existing ones: `Live & in-flight`, `Co-worker agents`,
  `Pipeline`, `Customer-facing`, `Internal tools`, `Meta`.
- `surface`: `both` (default), or `intranet` to hide it from the app portal
  because it needs the shares or SDILive.

> `surface` decides what is *listed*. It is not a security control — it does not
> stop anyone calling an endpoint. Protect endpoints in code.

### 4.2 An app with a real screen

Add an HTML file to `appportal/` and point at it:

```json
"app_url": "my-app.html"
```

An **Open** button then appears on the app's detail page. `appportal/voice-crm.html`
is the worked example. Every screen there is gated — only the manifest, icons and
`sw.js` are reachable without signing in.

### 4.3 Nick's Voice CRM app specifically

The screen exists and is wired to Microsoft Graph. It is **read-only** — see
"Why it does not write" below. To make it show real records:

**Step 1 — build the List.** In Nick's sandbox site, create a SharePoint **List**
(not a spreadsheet in a document library — his sandbox link currently points at
`Shared Documents`, which is the wrong shape for this).

Columns, at minimum:

| Column | Type | Notes |
|--------|------|-------|
| Project ID | Single line of text | Must be unique. This is the handle used on a call. |
| Customer | Single line of text | |
| AM Owner | Choice | Values including `NG`. The filter key. |
| Status | Choice | In progress / On hold / Complete — use a **view** per status, never move or delete records |
| Next action | Single line of text | |
| Next action date | Date | |

Turn on **version history** (List settings → Versioning settings). The write path
will depend on it to detect a record changed mid-conversation.

**Step 2 — find the internal name of the owner column.** Displayed names and
internal names differ; "AM Owner" is usually `AMOwner` or `AM_x0020_Owner`. List
settings → click the column → read `Field=` at the end of the URL.

**Step 3 — grant the Graph scope.** Back in the app registration, add delegated
`Sites.Read.All` and grant admin consent (step 2.3).

**Step 4 — configure and restart:**

```ini
SDI_GRAPH_SCOPES=User.Read Sites.Read.All
SDI_VOICECRM_SITE=sdidisplays.sharepoint.com:/sites/NickGarrish-ACCOUNTSANDPROJECTTRACKER2026
SDI_VOICECRM_LIST=Project Tracker
SDI_VOICECRM_OWNER=NG
SDI_VOICECRM_OWNER_FIELD=AMOwner
```

Sign out and back in — the new scope is only in tokens issued after it was
granted.

**Step 5 — open the app.** The screen tells you exactly what is wrong if anything
is: which setting is missing, whether the scope was consented, what Graph itself
said, or that the List read fine but no record has `AMOwner = NG`. It never shows
an invented record to look finished.

#### Why it does not write

Writing a record by voice needs the loop the architecture specifies: validate the
change, read it back, take explicit confirmation, re-check the owner and the
record version, write, and journal the outcome durably so a retry cannot repeat a
saved change. None of that exists yet, and a write endpoint without it would be
worse than no endpoint — it is exactly the "confidently wrong value" failure the
programme has been avoiding everywhere else.

Read-only also means the pilot cannot damage anything while it is being tested,
which makes it a much easier approval to get.

#### And on ChatGPT updating SharePoint

Separately from this app: the SharePoint connector in ChatGPT is read-only
grounding. Where writes are enabled at all they are admin-gated and file-level —
create a folder, upload or replace a file. There is no row-level List update. If
Nick needs ChatGPT itself to commit changes, that is a custom GPT Action calling
Graph through an endpoint you host and govern, which is a separate decision from
this portal.

---

## 5. Expose it safely (Day 3)

**Do not port-forward this.** It reaches the file shares and SDILive.

### Option A — Microsoft Entra Application Proxy (recommended here)

Fits because you are already a Microsoft tenancy, and it needs no inbound
firewall rule at all: a connector on the LAN makes an outbound connection to
Microsoft and traffic comes back down it.

**Requires Entra ID P1 or P2.** Check your licensing before planning around it —
this is the usual blocker.

1. Entra admin centre → **Applications** → **Enterprise applications** →
   **New application** → **Add an on-premises application**.
2. Download and install the **Application Proxy connector** on a Windows server
   on the LAN (not necessarily the portal host, but it must reach it).
3. Configure:
   - Internal URL: `http://<portal-host>:8071/`
   - External URL: `https://sdi-apps-<tenant>.msappproxy.net/` (or a custom
     domain with your own certificate)
   - Pre Authentication: **Microsoft Entra ID**
4. **Users and groups** → assign the same group as step 2.4.
5. Add `https://<external-url>/auth/callback` as a redirect URI on the app
   registration, and set `SDI_REDIRECT_URI` to match.
6. Remove `SDI_COOKIE_SECURE=no` — you are on HTTPS now.

You will be signed in twice conceptually (once at the proxy, once by the app) but
it is silent in practice — the second is satisfied by existing SSO.

### Option B — Cloudflare Tunnel

No Entra licensing requirement, also no inbound ports. You take on a second
vendor, and access control is Cloudflare Access rather than Entra assignment.

```yaml
# config.yml
tunnel: sdi-intelligence
credentials-file: C:\Users\<svc>\.cloudflared\<tunnel-id>.json
ingress:
  - hostname: apps.wearesdi.com
    service: http://localhost:8071
  - service: http_status:404
```

`cloudflared service install` to run it permanently. Then set the redirect URI
and `SDI_REDIRECT_URI` to `https://apps.wearesdi.com/auth/callback`.

### Either way, before you expose it

- [ ] SSO on and tested (`/api/me` returns a real person)
- [ ] `SDI_ALLOW_API_KEY=no`, and the hardcoded key removed from the portal HTML
- [ ] Credentials from step 0 rotated
- [ ] `SDI_COOKIE_SECURE` unset (defaults to secure)
- [ ] `SDI_ALLOWED_ORIGINS` set to the real external origin
- [ ] Assignment required = Yes, with a group assigned
- [ ] Check what `surface: both` apps expose — anything needing the shares should
      be `intranet`

---

## 6. Known limits

Honest list, so none of these surprise you later.

- **Sessions are in process memory.** Restarting the service signs everyone out,
  and it will not survive `uvicorn --workers > 1`. Move to Redis or a signed
  stateless token before this carries real load.
- **One worker.** Same reason.
- **Group overage.** If you use `SDI_ALLOWED_GROUPS` and someone is in more than
  ~200 groups, Entra omits the claim and they are denied. Enterprise-app
  assignment (2.4) does not have this problem — prefer it.
- **The catalogue is a file.** `services.json` is read from disk per request. Fine
  at this size; it is not a database.
- **No write path for Voice CRM.** Deliberate. See above.
- **Offline cache is per device.** The app portal caches the last catalogue it
  saw. File-share traffic is never cached.
