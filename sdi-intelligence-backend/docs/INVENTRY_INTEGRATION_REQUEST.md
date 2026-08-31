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

---

# Vendor correspondence

## Round 1 — sent 25 Aug 2026 (ticket #1052488, via Simon Foister)

Asked: how does InVentry receive data from an external system — watched folder,
database, or API — and can that route carry live on-site presence?

## Round 1 reply — Manuel Thomas, InVentry Support, 26 Aug 2026

> We can pull data directly from your MIS, provided the users have been added to
> your MIS. Alternatively, if you have a list of users in an Excel spreadsheet,
> you can import them directly into the system by following the guide below:
> *Manually Adding Personnel Records*.

**Assessment: this does not answer the question.** It is a first-line reply that
treats the request as "how do I add users", and neither option is usable:

| Offered | Why it does not fit |
|---|---|
| Pull from MIS | We are a manufacturer with no MIS. A school concept. |
| Manual spreadsheet import | Manual, and roster-only. We need unattended refresh every ~5 minutes. |

Critically, **live on-site presence was not addressed at all** — both options
concern personnel records (who exists), not who is in the building. Nothing here
describes a watched folder or drop-off location.

The one genuinely useful thread: if InVentry can *pull* from an MIS database,
the same mechanism might be pointed at a database or view we publish. That is
the "MIS link" the original handover mentioned, and it is worth pursuing.

## Round 2 — to send

Reply below. Two changes of approach: ask for escalation past first-line, and
separate the two data flows explicitly, since conflating roster with presence is
what caused the mismatch.

> Hi Manny,
>
> Thanks for coming back to us. I think we may have crossed wires, so let me be
> precise about what we're trying to do — and could this be passed to your
> technical or integrations team? I don't think it's a first-line question.
>
> Two points on the options you suggested. We're a manufacturer rather than a
> school, so we have no MIS. And the manual spreadsheet import won't work for
> us: this needs to be automated and unattended, refreshing roughly every five
> minutes.
>
> There are two separate data flows here, and I think only the first has been
> addressed so far:
>
> 1. **Staff roster** — who exists. Around 190 people, changing only when
>    someone joins or leaves.
> 2. **Live on-site presence** — who is physically in the building right now.
>    This is the one that matters most to us: it drives the fire evacuation
>    list, and it changes continuously through the day as people clock in and
>    out.
>
> Our staff clock in and out using BrightHR Blip. We already extract both
> datasets automatically onto our own server. What we need is a supported way to
> get them into InVentry with no human in the loop.
>
> So, specifically:
>
> 1. **Can InVentry's on-site register and evacuation list be updated
>    programmatically by an external system** — can we tell InVentry "these
>    people are currently on site"? If that simply isn't possible, please say so
>    plainly and we'll stop pursuing it.
>
> 2. **You mentioned you can pull data directly from an MIS. Can that same pull
>    mechanism point at a database or endpoint we provide instead?** If so, what
>    connection method does it use, and what table and field structure does it
>    expect?
>
> 3. **Do you have an API for writing data into InVentry?** We understand you
>    have an API integration with timeware from v4.11.0 onwards. Could you send
>    the documentation and tell us what credentials we would need?
>
> 4. **Is there an automated file-based import**, as opposed to the manual
>    process in the guide? If so: where must the file live for your service to
>    reach it, what format, and does it replace the whole list or apply changes
>    to it?
>
> 5. **Which field do you match a person on** — email address, an InVentry staff
>    ID, or name?
>
> For reference, this is the shape of what we hold for each person on site
> (illustrative values):
>
> ```json
> {
>   "id": "062b2236-…",          // BrightHR employee ID, stable per person
>   "first_name": "Jane",
>   "surname": "Doe",
>   "email": "jane.doe@wearesdi.com",
>   "clocked_in": "2026-08-27T07:45:00Z"
> }
> ```
>
> We can supply any subset of that, as CSV, JSON, or a database view — whatever
> suits your system. If you tell us the format you need, we'll produce it.
>
> Lastly, could you confirm **which version of InVentry we're running, and
> whether our system is on-premise or hosted by you**? That determines which
> network routes are even possible.
>
> Thanks,
> James Gray
> AI & Systems Controller, SDI Displays Ltd

## If round 2 also comes back roster-only

Then presence-into-InVentry is probably not a supported capability, and the
honest move is to stop trying to push it. The fallback needs nothing from
InVentry: we already know who BrightHR says is on site, so comparing that
against InVentry's register and reporting the difference gives H&S most of the
safety value. Worth putting that to Simon as a decision rather than continuing
to chase the vendor.
