# SDI Private Assistant — deployment

A read-only preview of **one person's own mailbox**, served by the SDI Intelligence
portal but authenticated entirely separately: its own Entra app registration, its own
credential, its own token cache, its own session database and its own cookies. The
shared portal sign-in cannot reach it and it cannot reach the shared portal's data.

Built and tested locally on 26 October 2026 (35 tests, Entra and Graph mocked).
**Nothing here is proven against real sign-in, MFA or live mail until section 8.**

Scope of this release: read the last seven days, with links. No drafting, sending,
deleting or moving. No ChatGPT/MCP, no voice, no AI summaries. The installer mounts
nothing at all unless `SDI_PRIVATE_ENABLED=yes`.

---

## Before you start

Three things are true of this change and worth stating plainly:

- **It opens a path on the public address.** `/api/private-email` is added to the
  portal's public allow-list, so it is reachable from the internet through App Proxy.
  That is the point — it has to be usable away from the office — and the code gates it
  on owner, tenant and client audience. But it is an internet-facing route to a mailbox,
  so the acceptance tests in section 8 are not optional.
- **It needs a new Entra registration and a new secret.** Do not reuse the portal's.
- **Mail.Read is delegated**, so it reads only the signed-in person's own mailbox, and
  the owner gate narrows that to one account.

---

## 1. Entra: a registration of its own (admin, once)

**Entra admin centre → App registrations → New registration**

- Name: **SDI Private Assistant**
- Supported account types: **this organisational directory only**
- Redirect URI: **Web** →
  `https://sdiintelligence-sdidisplays.msappproxy.net/api/private-email/auth/callback`

Do **not** add this URI to the shared portal registration, and do not copy the shared
registration's `/auth/callback` here.

Then, on the new registration:

- **API permissions → Add → Microsoft Graph → Delegated**: `User.Read`, `Mail.Read`.
  Grant admin consent, and read the consent prompt before you accept it rather than
  clicking through.
- **Certificates & secrets → New client secret.** Copy the **Value** once. It goes into
  the server's `.env` in section 4 and nowhere else — never into chat, a ticket or git.
- **Authentication**: no implicit grant, no public client flow.
- **Overview**: check the Application (client) ID matches
  `267fa0cc-38f7-4cc2-9a2d-7ecc436ad23b` in the configuration below. If a new
  registration was made instead, use the new ID.

**Assignment and MFA.** Assign only the ordinary `james.gray` account — not the cadmin
one. Then confirm in **Conditional Access → Policies → What If** that an MFA policy
actually applies to this user and this application. Having MFA methods registered is
not the same as a policy enforcing them.

---

## 2. Copy the files to the server

From the package folder to `C:\ClaudeVision\sdi-intelligence-backend`:

```
private_auth.py
private_email_integration.py
private_email_routes.py
private_email.py
private-email-readonly.html
```

The earlier draft UI is not copied: this installer always disables drafts.

So that later deploys carry them too, add the same five names to `$Files` in
`deploy\Deploy-AMCRM.ps1`.

---

## 3. The two host changes in `app.py`

Verified against the current checkout — the surrounding lines match, so apply the patch
with fuzz or make both edits by hand.

**a. The public allow-list** (around line 201), one line added:

```python
    "/api/hr/app",             # HRInventry Anywhere only - never the rest of /api/hr
    "/api/private-email",      # separate private registration and owner gate
    "/favicon.ico",
```

**b. Router registration** (around line 760), immediately after `auth.router`:

```python
app.include_router(auth.router)

from private_email_integration import install as install_private_email
install_private_email(app)  # disabled unless SDI_PRIVATE_ENABLED=yes

from voicecrm import router as voicecrm_router
```

`auth.py` is **not** changed. Before restarting, read any other global middleware for
anything that would intercept the private prefix.

---

## 4. Configuration and secrets

Settings, in the server's `.env`:

```
SDI_PRIVATE_ENABLED=no
SDI_PRIVATE_TENANT_ID=f0b45992-4294-4922-9ad5-8299efe0f57f
SDI_PRIVATE_CLIENT_ID=267fa0cc-38f7-4cc2-9a2d-7ecc436ad23b
SDI_PRIVATE_OWNER_ID=5acf6b37-147f-4468-bdb1-ecc3da1f1076
SDI_PRIVATE_ORIGIN=https://sdiintelligence-sdidisplays.msappproxy.net
SDI_PRIVATE_SESSION_DB=C:\ClaudeVision\private-data\private-sessions.db
```

Leave `SDI_PRIVATE_ENABLED=no` until section 7.

Secrets, typed on the server only, through whatever protected injection the service
already uses:

```
SDI_PRIVATE_CLIENT_SECRET=<the Value from section 1>
SDI_PRIVATE_ENCRYPTION_KEY=<generated on the server, see below>
```

Generate the encryption key **on the server**, never anywhere else:

```powershell
C:\ClaudeVision\sdi-intelligence-backend\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`SDI_PRIVATE_ORIGIN` is configuration and is never inferred from `X-Forwarded-Host`.
Check that App Proxy preserves the published Host header for these requests.

---

## 5. The session database folder

It holds encrypted session rows. Encryption is not a substitute for file permissions,
and it must not sit in a web root or on a share.

```powershell
New-Item -ItemType Directory -Force -Path C:\ClaudeVision\private-data | Out-Null
icacls C:\ClaudeVision\private-data /inheritance:r
icacls C:\ClaudeVision\private-data /grant "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"
icacls C:\ClaudeVision\private-data /grant "<the service account>:(OI)(CI)F"
icacls C:\ClaudeVision\private-data
```

The last line should show only those three. Expired rows are cleared on later writes;
there is no scheduled retention job yet.

---

## 6. Packages

On the service's **actual** runtime, not a test environment:

```powershell
C:\ClaudeVision\sdi-intelligence-backend\.venv\Scripts\python.exe -c "import msal, cryptography, fastapi, httpx; print('ok')"
```

Install anything missing individually. `requirements-test.txt` describes the isolated
test environment and is **not** a production dependency upgrade.

---

## 7. Turn it on

With it still disabled, restart and confirm the portal is unaffected and the private
path is absent:

```powershell
Restart-Service SDIIntelligence -Force
Start-Sleep 8
Invoke-WebRequest https://sdiintelligence-sdidisplays.msappproxy.net/api/private-email/auth/login -MaximumRedirection 0
```

A **404** is correct here: disabled means no routes mounted.

Then set `SDI_PRIVATE_ENABLED=yes`, restart, and check the service actually started.
Bad configuration is designed to **fail startup** rather than allow anonymous access —
so if the service does not come back, read the log before changing anything:

```powershell
Get-Service SDIIntelligence
Get-Content C:\ClaudeVision\output\logs\service-$(Get-Date -Format yyyy-MM-dd).log -Tail 40
```

---

## 8. Live acceptance — required before this is used

Mocked tests prove the logic, not the tenant. Every line below needs doing for real.

**Sign-in**
1. Ordinary `james.gray` signs in at
   `https://sdiintelligence-sdidisplays.msappproxy.net/api/private-email/auth/login`,
   and MFA is actually demanded.
2. A different user is refused. An admin identity is refused. A wrong-tenant identity
   is refused.
3. No private data is reachable via the office address, a machine key, an API key or a
   shared portal cookie.

**Reading**
4. Seven days of mail appear, with working source links.
5. The date window and any partial flags match Outlook. It is a preview reader: no full
   threads, no AI priority.

**Writing — there should be none**
6. No draft, send, delete or move is possible anywhere in the UI or the API.

**Sessions**
7. Cross-origin logout fails. After expiry or logout, private reads are refused.
8. Access logs contain no authorization codes or tokens.

**Reach**
9. Works in a real browser through App Proxy, then again from outside the office with
   the VPN off.

**No collateral damage**
10. HR, the AM CRM, estimating and the existing portal sign-in all still work.

**Before it is relied on**
11. Review dependency versions, reverse-proxy headers, TLS, rate limits, audit and
    retention.

---

## Rollback

```
SDI_PRIVATE_ENABLED=no
```
then restart. No routes are mounted and the portal is untouched. To remove it entirely,
revert the two `app.py` edits and delete the five files; nothing else in the service
references them.

---

## Testing the package itself

From the package folder, before any of the above:

```powershell
.test-env\Scripts\python.exe -m unittest -v test_private_email test_private_auth
```

35 tests, one Starlette HTTPX deprecation warning, no failures. This exercises the
router composition, not the full production app — so run the real host tests on
Windows as well before deploying.

---

## Not in this release

ChatGPT/MCP, voice, AI summaries, full threads, saved drafts, file shares, estimating
tools, admin privileges. Each needs its own implementation and tests.

Reference:
<https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens>
