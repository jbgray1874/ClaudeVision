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
| `apikey` | The InVentry console: **Setup & Options → (scroll to bottom) Partner API → toggle ON → Add API Key → choose the partner → copy the key**. Admin rights needed. |
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

## The one thing still missing

**The endpoint paths.** They live in the Postman collection, which Charlotte
mentions attaching but which did not arrive with the three PDFs. Every path is
therefore a setting (`INVENTRY_PATH_*`) with a placeholder default, and the
client raises a clear error on a 404 saying exactly that.

Applying the collection is a `.env` change, not a code change. Ask Charlotte to
re-send it, or export the request URLs from Postman.

## Settings this maps to

```
INVENTRY_API_BASE_URL=https://<touchscreen-or-vm-host>
INVENTRY_API_KEY=<from the console>
INVENTRY_PARTNER_SECRET=<from InVentry Ltd>
INVENTRY_API_CA_BUNDLE=<path to exported cert>   # or INVENTRY_API_VERIFY=false
INVENTRY_PATH_PERSONNEL=/...                     # from the Postman collection
INVENTRY_PATH_SIGN_IN=/...
INVENTRY_PATH_SIGN_OUT=/...
INVENTRY_ENABLE_SIGN_OUT=false                   # see below
```

## Why sign-out starts disabled

There is no settable field recording **which system** signed someone in, so we
cannot distinguish our own sign-ins from someone signing in at the reception
touchscreen. A sign-out driven by "BrightHR has no clocking for this person"
could therefore override a real human sign-in and remove someone from the
evacuation list who is in the building.

Sign-ins carry no equivalent risk. So sign-ins go live first; sign-outs are
enabled deliberately, once matching is proven correct, and are capped per run by
`INVENTRY_MAX_SIGN_OUTS_PER_RUN`.

Worth asking InVentry whether any field distinguishes the source of a sign-in —
if one exists, sign-out becomes materially safer.
