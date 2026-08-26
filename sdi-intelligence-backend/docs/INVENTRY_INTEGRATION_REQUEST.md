# InVentry integration request — ready to send

This is the one thing blocking the BrightHR → InVentry pipeline. Everything up
to the file is built, tested and producing real output; what has never been
established is how InVentry *receives* it.

## What we already know (found publicly, 23 Aug 2026)

InVentry do have both routes — so the question is not *whether* they integrate,
but which route carries **presence** and how we get onto it:

- **An API exists, at least for partners.** timeware (a time & attendance
  vendor) documents an API integration with InVentry, v4.11.0 onwards. Note the
  direction though: their published description is personnel data flowing
  *out of* InVentry into timeware. That is the opposite of what we need, so an
  API existing does not by itself mean we can write presence *in*.
- **A documented data import exists.** InVentry supply a spreadsheet with
  mandatory and optional fields as part of installation, uploaded into the
  onsite InVentry system, described in an **"InVentry Data Import Document" in
  the Welcome pack**. Worth finding ours before emailing — it may answer the
  format questions outright.
- **Staff records can sync automatically** from Active Directory, Google
  Workspace, and MIS systems. All are *roster* sync (who exists), not presence.
- Their wording "your onsite InVentry system" suggests an on-premise server
  component, which would make a share-based route plausible after all.

**Do this first:** find the Welcome pack / InVentry Data Import Document, and
check the admin console for an API keys or integrations page. Either may remove
the need to ask at all.

---

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
> We understand you support integration at several levels — an API (we've seen
> your integration with timeware), MIS and Google Workspace sync, Active
> Directory import, and a data import spreadsheet documented in the Welcome
> pack. We'd like to know which of those routes we should be using.
>
> Our questions:
>
> 1. **Is there an API we can use to write data into InVentry**, and could you
>    send us the documentation and whatever credentials it needs? If the API is
>    read-only or partner-only, please say so and point us at the right route
>    instead.
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
> 7. **Is our instance on-premise or cloud-hosted, which version are we on, and
>    does this need enabling or licensing on our account?** We'd also like to
>    know whether anything here is affected by upgrades.
>
> 8. **Could you re-send the InVentry Data Import Document** from our Welcome
>    pack? We may not have it to hand, and it sounds like it covers the import
>    format directly.
>
> 9. **Would Active Directory sync cover the staff roster for us?** We're on
>    Microsoft Entra ID. If so we may only need an integration for the live
>    on-site data, which would simplify things considerably.
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
| API available for writes? | Whether stage 3 gets an API driver instead of a file. An API would also sidestep the network-path problem entirely. |
| AD sync viable? | Whether stages 1–2 (the BrightHR roster pull) are needed at all — see below. |

## A strategic note

If InVentry can sync the staff roster straight from Entra ID / Active Directory,
then stages 1–2 of this pipeline are redundant: the roster would maintain itself
without BrightHR in the loop. The thing BrightHR uniquely provides is **Blip
presence** — who is clocked in right now — which no directory can supply.

That would be a good outcome: less to maintain, and the project narrows to the
one problem it actually exists to solve, the live fire roll call.

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
