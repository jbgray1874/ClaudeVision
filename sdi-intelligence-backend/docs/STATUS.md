# BrightHR → InVentry — status

Updated 6 Oct 2026.

## Where it stands

BrightHR extraction works and has for months. The InVentry side is built,
tested and configured, and as of 6 Oct **everything on SDI's side is verified
working against the live system**. `CheckAuth` reaches InVentry and returns a
clean **HTTP 401**.

That 401 is the whole remaining project. One credential is wrong, and it is not
one we hold.

---

## 1. Blocking — one credential, and it is InVentry's to issue

| # | Item | Owner | State |
|---|---|---|---|
| 1.1 | **Partner secret** | **InVentry** | The only unverified value left. We send the one pre-filled in their Postman collection; their overview says it is common across on-premises installations. Asked 28 Sep and 6 Oct. |
| 1.2 | Does a new API key need the InVentry service restarted? | **InVentry** | Would explain the 401 on its own. Asked with 1.1. |

### Verified on SDI's side — 6 Oct 2026

Listed because a 401 invites the question "are you sure it isn't your end?",
and each of these was checked rather than assumed:

| What | How it was proven |
|---|---|
| Network | `Test-NetConnection 10.0.0.241 -Port 4816` from 10.0.0.91 |
| TLS | Certificate pinned and verified — see below; connection now completes |
| Partner API enabled | Console, Settings → System → Partner API, toggle On |
| Key correctly scoped | One key, partner **"End User Developer"**, the option InVentry named |
| Key is the current one | `hr_config.INVENTRY_API_KEY` matches the console character for character |
| Headers | `apikey` + `partnersecret`, lowercase, as request headers — 84 tests |
| Reached InVentry | Response is an HTTP 401 from their server, not a transport failure |

**TLS took a correction.** The notes claimed a hosts entry plus a pinned
certificate would verify. It does not: their certificate is `CN=InVentry-PC`
with no `subjectAltName`, which modern TLS ignores, so no hostname can ever
match. `curl` falls back to `CN` and appeared to prove otherwise. Fixed with
`INVENTRY_API_CHECK_HOSTNAME=false` alongside the pinned bundle — the
certificate is still verified, only its name is not. See
`docs/INVENTRY_API_NOTES.md`.

## 2. The moment the secret lands

| # | Item | Notes |
|---|---|---|
| 2.1 | `python tools\probe_inventry.py` | Read-only. Prints which `.env` it loaded, then credentials, personnel and on-site counts |
| 2.2 | `python tools\probe_inventry.py --sign-in "<you>" --confirm` | **One** record. Answers whether `ActionLocation` is accepted, and whether the marker round-trips — see 5.2 |
| 2.3 | **Dry run, and read `matched_by`** | `python hr_onsite_push.py`. The one genuinely unknown outcome — see 5.1 |
| 2.4 | `HR_PUSH_APPLY = true` in the portal | Go live on sign-ins |

> Two `.env` files exist — `C:\ClaudeVision\...` and `C:\ClaudeVision-HR\...`.
> They are untracked by design and drift, and a setting added to the wrong one
> is indistinguishable from a setting that did not work. It has cost time twice.
> The probe now prints the path it loaded as its first line.

## 3. Production deployment (SDI-APP01) — not started

Everything so far is on **DESKTOP-GFAAP80**, a desktop. The portal runs as a
Windows service on SDI-APP01, and a fire roll call cannot depend on a desktop
being awake.

| # | Item |
|---|---|
| 3.1 | `Test-NetConnection 10.0.0.241 -Port 4816` **from SDI-APP01** — only ever proven from 10.0.0.91 |
| 3.2 | Check out this branch there |
| 3.3 | `.env` with the `INVENTRY_*` settings |
| 3.4 | Copy `inventry.pem` there |
| 3.5 | Hosts entry `10.0.0.241  InVentry-PC` — add it to `SDI-Intelligence-HostsEntry.ps1` so a rebuild does not silently break it |
| 3.6 | Scheduled task: Blip query + push every 5 minutes. Without it, presence is only as fresh as the last button click, and the code refuses snapshots over 15 minutes old |

### When the task will not run

`deploy\check_presence_task.ps1` answers this in one command: whether the
task exists and is enabled, what account it runs as, whether a repetition
interval actually stuck, the last result code translated into English, the
tail of the run log, and how old the snapshot is.

Three faults were found and fixed on 28 Sep, all of which produce a task that
looks healthy and does nothing:

* **No repetition duration.** `New-ScheduledTaskTrigger -Once` with a
  repetition interval and no duration registers a task that fires once and
  never again. The installer now asks for an indefinite duration, falls back
  to ten years where that is rejected, and reads the trigger back to confirm.
* **A hard-coded interpreter path.** The runner assumed
  `C:\ClaudeVision\.venv`, which does not exist in the `C:\ClaudeVision-HR`
  worktree. Worse, PowerShell treats a missing command as non-terminating, so
  `$LASTEXITCODE` kept a stale value and the script carried on to the push
  with no Blip data. The path is now resolved at install time, baked into the
  task argument, and the runner aborts with exit 1 if it is not there.
* **`-User SYSTEM` without a logon type.** SYSTEM needs
  `LogonType ServiceAccount`, and a named account with no password needs S4U,
  or the task registers and then fails at run time with 0x8007052E.

The runner also appends everything it prints to
`C:\SDIIntelligence\hr\snapshots\presence_sync.log`. Task Scheduler discards
a task's console output, so before this a failed cycle left nothing behind but
an exit code.

## 4. Waiting on InVentry — none of it blocking

| # | Item | Impact |
|---|---|---|
| 4.1 | Does `ActionLocation` accept free text, or must it be an existing location? | Decides whether automatic sign-out can be enabled (6.2) |
| 4.2 | Confirm the partner secret in the collection is ours to use | Only matters if `CheckAuth` fails |
| 4.3 | Current password for the `\\10.0.0.241\Inventry` share | Mostly moot — the certificate was taken off the TLS handshake instead |

## 5. Unknowns that could still create work

| # | Item |
|---|---|
| 5.1 | **Matching quality.** People are matched on `PersonID`, then email, then name. InVentry's `PersonID` is probably empty for SDI staff, and their email addresses may be too. If matching falls through to names, duplicates are skipped rather than guessed. Fix if needed: backfill `PersonID` with the BrightHR id using `AddPersonnel`/update, which the client already supports. The first dry run answers this in seconds. |
| 5.2 | Whether the `ActionLocation` marker round-trips as `LastEventLocation` on the live system. `/api/hr/inventry/check` reports `on_site_signed_in_by_us`. **No longer a risk to sign-ins**: if InVentry refuses the field the client drops it, warns, and completes the sign-in (30 Sep). It still gates safe sign-out. Note there is no Locations list in the console, so we cannot make the marker a real location — only InVentry can say whether free text is accepted. |

## 6. Deliberately deferred

| # | Item |
|---|---|
| 6.1 | TLS verification is on here (`InVentry-PC` + pinned certificate) and proven working. Falling back to `INVENTRY_API_VERIFY=false` is acceptable if the name ever stops resolving. |
| 6.2 | **Sign-out stays off** (`INVENTRY_ENABLE_SIGN_OUT=false`) until 5.2 is confirmed. Sign-ins carry no equivalent risk; a wrong sign-out drops someone off the evacuation list. |

## 7. Found along the way — separate from this project

| # | Item | Why it matters |
|---|---|---|
| 7.1 | **15 forgotten clock-outs in BrightHR**, oldest open since 28 July (62 days). Includes James and Simon. | The sync now excludes them, but each is a payroll and H&S problem in BrightHR. Needs chasing by someone. |
| 7.2 | `HR_OUTPUT_DIR=K:\IT\HRSystemsOutput` is a **mapped drive** | A Windows service cannot see user drive mappings, so the browsable on-site file silently fails to write when run as a service. Use the UNC path `\\sdi-dc01\shareddata$\Shared\IT\HRSystemsOutput`. Failure is now reported rather than silent. |
| 7.3 | **`.env` was committed to git** | Removed from tracking on this branch, but it remains in history: the BrightHR client secret / PAT and the SDI API key need **rotating**. |
| 7.4 | **SDI API key is hardcoded in the portal HTML** (line 2042) and served to every browser | It is the only gate on `/api/files`, `/api/file` and all of `/api/hr/*`. Rotating helps; the real fix is checking Entra ID group claims instead of a shared secret. |

## 8. Repository

73 tests, no network or credentials required: `python -m pytest tests -q`.

`main` is static at `2730c0d`. **`main-2026` is the live trunk**, and this work
is already on it: a parallel session ported the Partner API client, the on-site
push, the Blip loader, the `/api/hr` routes and the 73 tests across as `5b47cce`,
then merged the app portal in as `b1b3977`, restoring the InVentry button.

Consequences:

* PR **#1** (`claude/hr-inventory-handover-vnjqw7` → `main`) is **redundant**.
  Merging it would fork the work onto a dormant branch. Recommend closing it.
* `sdi-intelligence-backend/deploy/` does **not** exist on `main-2026` — the
  four `.ps1` scripts postdate the port. They still need lifting across, either
  by copying the files or by a small PR into `main-2026`.

## 9. Next work stream — after the presence sync is bedded in

Named on 28 Sep, not yet scoped:

| # | Item |
|---|---|
| 9.1 | Estimating: PDF / PNG prompting |
| 9.2 | Speed improvements |
| 9.3 | Breaking the job down into smaller units |
