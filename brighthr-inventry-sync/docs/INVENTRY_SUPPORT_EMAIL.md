# InVentry integration request — ready to send

InVentry access is the one thing blocking this project. Everything else is
built and tested; the sync runs today against the dry-run driver.

**To:** support@inventry.co.uk
**Phone (if chasing):** 0113 322 9253, option 3
**Subject:** Integration request — programmatic staff sign-in from BrightHR (SDI Displays Ltd)

The draft below asks for everything the code needs in one round trip, so we're
not waiting on a second and third email. Each question maps to a setting in
`.env.example` that is currently blank or a guess.

---

## Draft email

> Hello,
>
> We're an existing InVentry business customer — SDI Displays Ltd, Shepshed,
> Leicestershire.
>
> We're building an integration that keeps InVentry's on-site staff register in
> step with our HR system. Staff clock in and out using BrightHR Blip, and we
> want InVentry to reflect who is physically on site in near real time, so that
> the fire evacuation roll call and our H&S reporting are accurate. A scheduled
> script on our own Windows server would push presence updates to InVentry
> every five minutes.
>
> Could you tell us what integration options you support for this? In
> particular:
>
> 1. **Method** — do you provide a REST API, a database integration, or a
>    supported MIS/third-party sync for updating staff sign-in and sign-out
>    programmatically? We understand from your integrations page that custom
>    database integrations are supported.
>
> 2. **Hosting** — is our InVentry instance on-premise or cloud-hosted? This
>    determines how our server connects.
>
> 3. **Credentials** — what would we need from you: a database server name,
>    database name, and a service account with the right permissions, or API
>    credentials?
>
> 4. **Schema or endpoints** — which table (or endpoint) holds the current
>    on-site staff register, and which fields represent staff ID, name, sign-in
>    time and sign-out time? Are direct INSERT/UPDATE statements supported, or
>    should we call a stored procedure or API method so your business logic
>    runs?
>
> 5. **Staff identifiers** — what is the staff identifier in InVentry, and can
>    we export the current staff list with those IDs so we can map them to our
>    BrightHR employee records?
>
> 6. **Distinguishing automated from manual sign-ins** — is there a field
>    recording the source of a sign-in? We need our automated updates not to
>    override anyone signed in manually at the terminal.
>
> 7. **Rate limits or scheduling guidance** — is a five-minute update cycle
>    reasonable, and are there constraints we should design around?
>
> 8. **Support and licensing** — does this integration need to be enabled on our
>    account, and is there a cost or a support agreement involved?
>
> Happy to arrange a call if that's easier.
>
> Kind regards,
> James Gray
> AI & Systems Controller, SDI Displays Ltd
> james.gray@wearesdi.com

---

## What each answer unblocks

| Their answer | What it sets |
|---|---|
| Method (API vs database) | `INVENTRY_DRIVER` — `sqlserver` exists; a REST answer means writing a third driver against the same `InVentryClient` interface |
| Hosting (on-prem vs cloud) | `INVENTRY_DB_SERVER`, whether the VPN route or a firewall rule is needed |
| Credentials | `INVENTRY_DB_NAME`, `INVENTRY_DB_USER`, `INVENTRY_DB_PASSWORD` |
| Schema / endpoints | `INVENTRY_TABLE` and the `INVENTRY_COL_*` settings — all currently the handover's guess |
| Staff identifiers + export | `employee_map.json`, built with `tools/build_employee_map.py --inventry-csv` |
| Source-of-sign-in field | `INVENTRY_COL_SOURCE` — protects manual sign-ins from being overridden |
| Rate limits | `SYNC_INTERVAL_MINUTES` |

If they answer "stored procedure only" or "REST API", that is a new driver class
in `inventry_client.py` implementing `get_on_site` / `sign_in` / `sign_out`.
Nothing else in the project changes.

## If they say no

Fallbacks worth raising on a call, in order of preference:

1. **InVentry Anywhere API** — the mobile/web sign-in product mentioned in the
   handover may have an addressable endpoint behind it.
2. **MIS link** — InVentry advertise syncing from third-party databases. We
   could publish a view from our side that InVentry pulls from, inverting the
   direction of travel; the BrightHR half of this project is unchanged either
   way.
3. **Read-only first** — even without write access, reading InVentry's register
   and reporting the mismatch against BrightHR gives H&S a daily discrepancy
   report, which is most of the safety value.
