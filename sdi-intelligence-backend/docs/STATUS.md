# BrightHR → InVentry — status

Updated 28 Sep 2026.

## Where it stands

BrightHR extraction works and has for months. The InVentry side is built,
tested and configured. **One thing is missing: an API key**, which is created in
the InVentry Console. Everything else is either done or waiting on that.

---

## 1. Blocking — nothing else can be proven until these are in

| # | Item | Owner | Notes |
|---|---|---|---|
| 1.1 | **InVentry API key** | James | Created in the InVentry Console (Setup & Options → System → Partner API → Add API key → "End User Development"). Console not installed locally — the share password from the 2025 engineer email no longer works. Three routes: phone InVentry support 0113 322 9253 and have them create it remotely; borrow Simon's console; or use the reception touchscreen. |
| 1.2 | **Partner secret** | James | Almost certainly the value pre-filled in InVentry's Postman collection (AddPersonnelAction headers). Cannot be validated on its own — `CheckAuth` checks both credentials together. |

## 2. Next, once the key exists — all quick

| # | Item | Notes |
|---|---|---|
| 2.1 | `git pull` on DESKTOP-GFAAP80 | Branch is behind; then restart whatever serves port 8072 |
| 2.2 | Put key + secret in `.env` | `INVENTRY_API_KEY`, `INVENTRY_PARTNER_SECRET` |
| 2.3 | `CheckAuth` | `curl.exe --cacert C:\SDIIntelligence\inventry.pem -H "apikey: …" -H "partnersecret: …" https://InVentry-PC:4816/PartnerAPI/CheckAuth` |
| 2.4 | **Dry run, and read `matched_by`** | The one genuinely unknown outcome — see 5.1 |
| 2.5 | `HR_PUSH_APPLY = true` in the portal | Go live on sign-ins |

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
| 5.2 | Whether the `ActionLocation` marker round-trips as `LastEventLocation` on the live system. `/api/hr/inventry/check` reports `on_site_signed_in_by_us`. |

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

PR **#1** — `claude/hr-inventory-handover-vnjqw7` → `main`. Open, not merged.
73 tests, no network or credentials required: `python -m pytest tests -q`.
