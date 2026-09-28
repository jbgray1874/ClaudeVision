# InVentry Partner API — what the documentation actually says

Source: three documents from Charlotte Fastenbauer (Product Coordinator,
InVentry), 16 Sep 2026 — *Customer API Overview*, *Partner API field
information*, *Linking your system to your partner*. This file records the
facts the code depends on, so nobody has to re-read the PDFs to check an
assumption.

**This supersedes the watched-folder idea entirely.** There is no file drop.
The supported route is an HTTP API, and it does support writes.

## Authentication

Two credentials, both sent as **request headers**:

| Header | Where it comes from |
|---|---|
| `apikey` | The InVentry Console — a **Windows desktop application**, not a web page, installed as part of the InVentry system (it lives on the main reception touchscreen; InVentry can install it on an admin PC). Needs an InVentry **admin** login. Path: **Setup & Options → left menu, System section (at the bottom) → Partner API → toggle "Enable partner API" ON → Add API key → Partner: "End User Development" → copy**. That toggle starts Off. |
| `partnersecret` | Issued by **InVentry Ltd**. The same key across all their on-premises installations; it exists so one partner cannot impersonate another in their logs. |

When adding the key, the **Partner** dropdown matters — the documentation's
example uses *"End User Developer"*, which is what we are, but it also says to
confirm the right option with a manager. Pick the wrong one and the key is
scoped to the wrong integration.

## Network shape — the part that decides the architecture

> "The API is only accessible from the customer network, it cannot be made
> available externally."

The API is an extension of the **on-premises** InVentry system, normally running
on the reception sign-in touchscreen itself (about 5% of customers put it on a
dedicated VM instead). Cloud solutions are told to run a local bridge client.

For us this is good news: SDI-APP01 already runs on the network, so it can call
the API directly. No bridge needed.

Certificates are **locally issued and self-signed**, so TLS verification fails
by default. Two options, in order of preference:

1. Export the certificate and set `INVENTRY_API_CA_BUNDLE` — verification stays on.
2. Set `INVENTRY_API_VERIFY=false` — trusts any certificate on that host. Only
   acceptable because this is a LAN call to a known machine. The client emits a
   warning whenever it runs this way.

## Rate limits

- **20 GET calls per minute.** Exceeding it returns 429.
- **POST is exempt from the limit** — explicitly stated, and it is why pushing
  presence frequently is viable.
- Polling should be no more often than **once per 5 seconds**.
- For bulk personnel writes they ask that we consider the organisation's working
  patterns and prefer quiet periods.

Our client enforces a 19/minute sliding window on GETs and leaves POSTs
unthrottled, matching the above.

## Request shapes

| | GET | POST |
|---|---|---|
| Auth | headers | headers |
| Payload | query parameters | **`x-www-form-urlencoded` key/value pairs — not JSON** |
| Response | JSON object of the requested type | dict with at least `response` and `message`; adding a person also returns the new record's ID |

Non-200 responses carry a useful message string in the body.

## Fields — what we can actually set

From *Partner API field information*. The personnel table has ~55 fields; these
are the ones that matter to us, and whether InVentry allows us to set them:

| Field | Type | Settable | Why it matters |
|---|---|---|---|
| `ID` | uniqueidentifier | **NO** | InVentry's own key. Read it, never set it. |
| `PersonID` | varchar(40) | **YES** | *"If you are adding a person and wish to store your systems ID against that record, you should use this field."* The BrightHR employee UUID goes here. **This is what removes the need for a mapping table.** |
| `FirstName`, `Surname` | varchar(60) | YES | |
| `EmailAddress` | varchar(100) | YES | Secondary match key |
| `MemberOfStaff` | bit | YES | Staff vs visitor |
| `EvacuationGroup` | varchar(30) | YES | Relevant to the fire roll |
| `Department`, `StaffPosition` | varchar | YES | Optional enrichment |
| `LastActivityType` | varchar(10) | **NO** | Read-only — how we tell who InVentry currently shows as on site |
| `LastActivityDateTime`, `LastActivityLocation` | | **NO** | Read-only |
| `MISID` | varchar(40) | **NO** | Their MIS key; not ours to use |
| `Gender` | varchar(10) | YES | Must be exactly `Male` or `Female` if sent |

Presence is written through the **events** table, not by setting those
read-only activity fields:

| Field | Type | Settable |
|---|---|---|
| `EventDateTime` | datetime | **YES** |
| `EventType` | varchar(10) | **YES** |
| `Reason` | varchar(50) | YES |
| `LocID` | varchar(40) | YES |
| `EventID`, `SiteID`, `Duration` | | NO |

`EventDateTime` is a SQL Server datetime, so the client sends
`YYYY-MM-DD HH:MM:SS` rather than an ISO string with a `Z`.

## Presence writes are supported

The clearest evidence is InVentry's own ANPR integration, which uses this API to:

> - Set a booked visitor as arrived …
> - **Sign in a member of staff on arrival.**
> - **Sign out a member of staff on arrival** [sic — presumably departure].

So signing staff in and out through the Partner API is an established pattern,
not something we are inventing.

## Sandbox

- IP **162.13.119.241**, self-signed certificate, mimics an on-premises system.
- Keys are issued separately by InVentry.
- **Shared with other partners — dummy data only.** Never push real staff data
  there; it would be a personal-data disclosure to unknown third parties.

## The endpoints (from the Postman collection, 25 Sep 2026)

All under `https://<host>:4816/PartnerAPI/`. **Port 4816.**

| | Endpoint | Notes |
|---|---|---|
| GET | `CheckAuth` | Credentials test, cheapest possible call |
| GET | `GetPersonnel/?IncludeNonStaff=true` | The personnel list. Returns a **bare JSON array** |
| GET | `GetLatestPersonnelActions?LastCollectionId=N` | Incremental sign-in/out feed |
| GET | `GetSystemTime` | Their clock — useful for spotting skew against ours |
| GET | `GetDepartments` / `GetScanCodes` / `GetVisitors` / `GetExpectedVisitors` | |
| POST | `AddPersonnel` | Create a person |
| POST | `AddPersonnelAction` | **Sign in / sign out** |
| POST | `AddPersonnelScanCode` | |

### AddPersonnelAction — the presence call

Form-encoded, per their own example:

| Field | Required | Example |
|---|---|---|
| `PersonnelID` | yes | `9aa8a5b6-8569-4bd6-bd5c-0097fd7203bd` (InVentry's `ID`) |
| `ActionType` | yes | `IN` or `OUT` |
| `ActionDateTime` | optional | `1983-07-08T00:00:00` — **"T" separator, no timezone** |
| `ActionLocation` | optional | see below |

POST responses look like `{"response":"OK","message":"OK"}`, and `AddPersonnel`
adds `"ID"` for the new record.

## ⚠ The collection contradicts the field-information PDF

The live JSON is authoritative, and it differs in ways that break code written
from the PDF alone:

| Field PDF says | What the API actually returns |
|---|---|
| `LastActivityType` | **`LastActivity`** — values `"IN"`, `"OUT"` or `null` |
| `LastActivityDateTime` | **`LastActivityDate`** — e.g. `2020-12-22T18:08:46.307`, or `0001-01-01T00:00:00` for never |
| `LastActivityLocation` | **`LastEventLocation`** |
| `Postcode` | `PostCode` |
| `VehicleReg` | `CarReg` |

`PersonID` in real data is a short external key (e.g. `"1932"` on a site that
syncs from Arbor), confirming it is the external-system field. InVentry confirmed
it **should be unique per person**. Note that on a site using AD integration
they populate it with the PID from AD — so check ours is free before writing to
it.

## Sign-out, and the field that makes it safe

InVentry confirmed (25 Sep) that **`LastEventLocation` records where a sign-in
came from** — the main touchscreen, a Quickscan, the Anywhere app, and so on,
named per site. Real values in their sample data include `"CONSOLE"` and a
location id. If a sign-out came from a rule, such as their automatic sign-out,
a reason is recorded against it.

So we send `ActionLocation=BRIGHTHR SYNC` (`INVENTRY_ACTION_LOCATION`) with our
own writes, and InVentry reflects it back as `LastEventLocation`. With
`INVENTRY_ONLY_SIGN_OUT_OUR_OWN` on — the default — **only people whose last
event carries our marker are ever signed out**, so a sign-in made at reception
is never undone by the sync.

Sign-out is still off by default (`INVENTRY_ENABLE_SIGN_OUT=false`) for one
remaining unknown: whether InVentry accepts free text in `ActionLocation` or
requires an existing location. Turn it on once `/api/hr/inventry/check` shows
`on_site_signed_in_by_us` counting our sign-ins correctly on the live system.
Sign-outs are also capped per run by `INVENTRY_MAX_SIGN_OUTS_PER_RUN`.

## Other answers from InVentry, 25 Sep

- **Partner type:** use **"End User Development"** when creating the API key.
  Charlotte noted that as this is our own system it "wouldn't require the
  Partner API" in the partner sense — the same endpoints, keyed as an end-user
  developer.
- **Host:** the **main touchscreen**, unless we run our own VM for the InVentry
  software. Their support team can connect and confirm which.
- **Certificate:** exportable from the **V4 folder on the main unit**; support
  can supply it if that fails.
- **Load:** their Development QA team reviewed our example traffic (~190 staff,
  bursts of 50–100 sign-ins) and expect no issues.
- **ANPR:** a separate console setting, and their ANPR material is about
  visitors and barriers (and needs a Bi3 licence). Not needed for staff
  presence — `AddPersonnelAction` is a plain Partner API call.

## Our site: where everything lives

Confirmed from InVentry engineer Adam Stiff's setup instructions (9 May 2025,
forwarded 28 Sep 2026):

> "\\10.0.0.241\Inventry (this is the IP address the sign in system is fixed to)"

| What | Where |
|---|---|
| InVentry system | **10.0.0.241**, a fixed address |
| Partner API | `https://10.0.0.241:4816/PartnerAPI/` |
| InVentry Console | `\\10.0.0.241\Inventry\V4\Console\` — the shortcut with the blue V |
| Certificate | `\\10.0.0.241\Inventry\V4\` — the "V4 folder" InVentry refer to |

Reaching the console means mapping that share with the InVentry share account
(credentials are in Adam's email; they are **not** recorded here), then making a
desktop shortcut to the console link. Logging into the console itself needs an
InVentry admin account, which is a separate thing again.

The sync service needs **none** of that: the API is a plain TCP call to
10.0.0.241:4816 with the two headers. The file share matters only for
installing the console and fetching the certificate.

Quickest confirmation that the API is up, before touching anything else:

```powershell
Test-NetConnection -ComputerName 10.0.0.241 -Port 4816
```

### Settings this maps to

```
INVENTRY_API_BASE_URL=https://10.0.0.241:4816
INVENTRY_API_KEY=<from the console>
INVENTRY_PARTNER_SECRET=<from InVentry, or the value in the Postman collection>
INVENTRY_API_CA_BUNDLE=<the certificate exported from the V4 folder>
INVENTRY_ENABLE_SIGN_OUT=false          # until the location marker is proven
```

### The certificate (captured 28 Sep 2026)

Pulled off the TLS handshake rather than the V4 folder, since the share
credentials in the 2025 engineer email no longer work:

```
Subject : CN=InVentry-PC, O=InVentry-PC, L=Leeds, S=West Yorkshire, C=UK
Issuer  : CN=InVentry-PC, O=InVentry-PC, L=Leeds, S=West Yorkshire, C=UK
Expires : 30/04/2034
```

Self-signed by itself, as their documentation says, and long-lived. Saved to
`C:\SDIIntelligence\inventry.pem`.

**The name matters.** The certificate is issued to `InVentry-PC`, not to
`10.0.0.241`. Trusting the certificate alone is not enough: TLS also checks the
hostname, so `https://10.0.0.241:4816` fails verification even with the right
CA bundle. Three options:

1. **Hosts entry, then use the name** — full verification, and in keeping with
   `SDI-Intelligence-HostsEntry.ps1`, which this project already uses for the
   same reason:
   ```
   10.0.0.241   InVentry-PC
   ```
   then `INVENTRY_API_BASE_URL=https://InVentry-PC:4816` and
   `INVENTRY_API_CA_BUNDLE=C:\SDIIntelligence\inventry.pem`.
   Note OpenSSL only falls back to CN when the certificate has no
   subjectAltName, so check for a SAN before relying on this.
2. **Use the name if DNS already resolves it** — same thing without the hosts
   file. Test with `Test-NetConnection InVentry-PC -Port 4816`.
3. **`INVENTRY_API_VERIFY=false`** — no verification. Defensible for a LAN call
   to a fixed address on our own network, and the client logs a warning every
   run so it never becomes invisible. Reversible at any time.

To capture the certificate again, or after an InVentry upgrade replaces it, see
`tools/get_inventry_cert.ps1`.
