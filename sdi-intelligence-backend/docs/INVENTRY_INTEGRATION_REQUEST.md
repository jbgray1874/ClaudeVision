# InVentry integration request — ready to send

This is the one thing blocking the BrightHR → InVentry pipeline. Everything up
to the file is built, tested and producing real output; what has never been
established is how InVentry *receives* it.

**To:** support@inventry.co.uk
**Phone (to chase):** 0113 322 9253, option 3
**Subject:** Integration request — pushing staff and on-site presence data into InVentry (SDI Displays Ltd)

---

## Draft email

> Hello,
>
> We're an existing InVentry customer — SDI Displays Ltd, Shepshed,
> Leicestershire — using InVentry for sign-in at reception.
>
> We've built an integration on our own Windows server that pulls data from
> BrightHR, our HR system, and we'd like InVentry to consume it automatically.
> We produce two datasets, on demand and on a schedule:
>
> 1. **Active staff roster** — first name, surname, email address, refreshed
>    when staff join or leave.
> 2. **Live on-site list** — who is currently clocked in via BrightHR Blip,
>    with their clock-in time, refreshed every few minutes.
>
> The goal is that InVentry's staff records stay current automatically, and that
> the on-site register and fire evacuation list reflect who is actually in the
> building rather than relying on people remembering to sign in at the terminal.
>
> Our questions:
>
> 1. **How does InVentry receive data from an external system?** Is it a folder
>    one of your services watches, a database we write into, an API we call, or
>    something else? We'd like to understand the supported route rather than
>    guess at one.
>
> 2. **If it's a watched folder — where must that folder live?** Our data is
>    generated on our own application server. Is there an InVentry service
>    running on our network that could read a local or shared path, and if so
>    which account does it run as and what path should we target? (We can expose
>    a UNC share on our file server if that's what's needed.)
>
> 3. **Can that same route carry live on-site presence**, or does it only
>    support the staff roster? This is the part that matters most to us — the
>    evacuation list is the reason for the project.
>
> 4. **If presence is supported:** what format and column headers do you expect,
>    and is the file treated as the *full current state* — anyone not in the
>    file is signed out — or as a set of individual sign-in/sign-out events?
>
> 5. **Which identifier do you match people on** — email address, an InVentry
>    staff ID, or name? We currently have name and email from BrightHR. If you
>    need your own staff ID, could we get an export of the current staff list
>    with those IDs so we can map them?
>
> 6. **How often can this run?** We'd like to refresh presence roughly every
>    five minutes. Is that reasonable, or are there constraints we should design
>    around?
>
> 7. **Is our instance on-premise or cloud-hosted, and does this need enabling
>    or licensing on our account?** We'd also like to know whether anything here
>    is affected by upgrades to our system.
>
> We're happy to share a sample of the data files, and a short call would work
> well if that's easier than email.
>
> Kind regards,
> James Gray
> AI & Systems Controller, SDI Displays Ltd
> james.gray@wearesdi.com

---

## What each answer unblocks

| Their answer | What it decides |
|---|---|
| Route (folder / database / API) | Whether stage 2 and 3 keep writing a CSV, or need a database or HTTP client. The data layer is unaffected either way. |
| Where the folder must live | `INVENTRY_CSV_PATH` / `INVENTRY_ONSITE_CSV_PATH`. Today's `C:\InVentryImports\` default is a placeholder and is not reachable from off-box. |
| Presence supported? | Whether stage 3 goes live at all, or falls back to the discrepancy-report option below. |
| Format, columns, full-state vs delta | `hr_blip_inventry.ONSITE_FIELDS` and whether "absent = signed out" holds. |
| Match identifier | Whether name + email is enough, or an ID mapping table is needed. |
| Frequency | The Task Scheduler interval. |
| Hosting and licensing | Network route, and whether anything must be switched on by them. |

## If presence isn't supported

Worth raising on a call, in order of preference:

1. **InVentry Anywhere** — the remote sign-in product may have an addressable
   endpoint behind it.
2. **MIS-style link** — InVentry advertise syncing from third-party databases.
   We could publish a read-only view for them to pull from, inverting the
   direction of travel. The BrightHR half is unchanged either way.
3. **Discrepancy report only** — needs nothing from InVentry. We already know
   who BrightHR says is on site; comparing that against InVentry's register and
   reporting the difference daily gives H&S most of the safety value without any
   write access.

## Sample data to attach

The pipeline already writes dated files to
`\\sdi-dc01\shareddata$\Shared\IT\HRSystemsOutput`:

- `brighthr_staff_<UTC>.json` — the roster
- `blip_onsite_<UTC>.json` — the on-site list

Attaching one of each makes the questions concrete. **Check the contents before
sending** — these contain real staff names, so treat it as a personal-data
disclosure to a supplier and keep it to a single small sample.
