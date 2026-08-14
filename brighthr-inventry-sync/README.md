# BrightHR → InVentry presence sync

Keeps InVentry's on-site staff register in step with BrightHR Blip clock-in
data, so the fire evacuation roll call reflects who is actually in the building.

SDI Displays Ltd, Shepshed. Built from the 29 May 2026 handover document.

## Status

| Side | State |
|---|---|
| BrightHR | **Built and tested.** Works against a stubbed API; needs a real API key to run live. |
| Sync engine | **Built and tested.** 46 tests, including every edge case in the handover. |
| InVentry | **Blocked on the vendor.** Dry-run driver works now; the SQL Server driver is written but unverified — InVentry have not supplied credentials or confirmed the schema. See `docs/INVENTRY_SUPPORT_EMAIL.md`. |

Nothing writes to InVentry until `--apply` is passed *and* `INVENTRY_DRIVER` is
changed from `dryrun`. Both are deliberate.

## Two open items

1. **The real BrightHR JSON.** Field names are unconfirmed, so no field name is
   hardcoded — they live in `field_map.json`, which tries several candidates per
   field. Run `python tools/inspect_brighthr_json.py your_sample.json` to see
   what matches and what needs adding. Both the snake_case shape from the
   handover and a camelCase/nested variant parse today without a code change.
2. **InVentry credentials.** `docs/INVENTRY_SUPPORT_EMAIL.md` is ready to send
   and asks for everything the code needs in one round trip.

## Quick start

```bash
cd brighthr-inventry-sync
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt

copy .env.example .env                              # add the BrightHR API key
python sync.py --check                              # connectivity check, no writes
python sync.py                                      # dry run: log what would change
```

The API key comes from app.brighthr.com → Settings → Integrations → Customer
API. It is read from `.env`, which is gitignored — no credentials in source.

## How it works

```
BrightHR Blip  ──►  sync.py  ──►  InVentry
 clock in/out       every 5 min     on-site register
 breaks                             fire roll call
 absences
```

Each run: read who BrightHR says is on site, read who InVentry says is on site,
sign in the difference one way, sign out the difference the other, log both.

## Safety rails

InVentry drives the fire evacuation list, so the failure modes that matter are
the ones that *empty* it. The sync never signs the building out by accident:

| Situation | Behaviour |
|---|---|
| BrightHR unreachable or erroring | Abort the run. No writes at all. |
| BrightHR reports nobody on site | Sign-outs suppressed — treated as a data problem, not an empty building. Override with `SYNC_ALLOW_FULL_SIGN_OUT`. |
| More than half the register would be signed out | Suppressed. `SYNC_MAX_SIGN_OUT_RATIO`. |
| More than 25 sign-outs in one run | Suppressed. `SYNC_MAX_SIGN_OUTS_PER_RUN`. |
| Someone signed in manually at the terminal | Never auto-signed-out. A human decision outranks the sync. |
| Someone on site in InVentry but not in the employee map | Left alone — could be a visitor or contractor. |
| InVentry write fails for one person | Logged, run continues, exit code 2. |

Sign-*ins* are never suppressed: signing someone in wrongly is recoverable,
signing the building out is not.

Exit codes: `0` clean, `2` partial (something was suppressed or failed), `1` the
run aborted without writing.

## Handover edge cases

Each of these is a decision the handover flagged, wired to a setting:

- **Breaks** — staff on a break stay on site, since they're still in the
  building (`SYNC_TREAT_BREAK_AS_ON_SITE=true`). The handover leaves this to
  James/Matt; flipping it to `false` is tested and works.
- **Absences** — approved holiday or sickness in BrightHR blocks a sign-in, so a
  stale clock-in event can't put someone on the roll who isn't there. If the
  absences endpoint fails, the sync continues without it rather than aborting.
- **Manual overrides** — rows not tagged with `INVENTRY_SOURCE_TAG` are treated
  as manual and left alone. If the real schema has no source column, set
  `INVENTRY_COL_SOURCE=` empty and *nothing* gets auto-signed-out — the safe
  direction until InVentry confirm a field.
- **Employee ID mapping** — BrightHR and InVentry IDs differ, so
  `employee_map.json` is required. Unmapped people are reported, never guessed.

## Layout

```
sync.py                   Sync engine + CLI (--check / --apply / --loop)
brighthr_client.py        BrightHR API: retries, rate limits, presence derivation
inventry_client.py        InVentryClient interface + dry-run and SQL Server drivers
employee_map.py           BrightHR ID <-> InVentry ID lookup
config.py                 Settings from .env
field_map.json            BrightHR field names (edit this, not the code)
employee_map.example.json Template for the ID mapping
tools/
  inspect_brighthr_json.py  Check field_map.json against a real JSON sample
  build_employee_map.py     Build the ID map from BrightHR + an InVentry export
deploy/
  install_scheduled_task.ps1  Windows Task Scheduler (preferred)
  install_nssm_service.ps1    NSSM service (alternative — do not run both)
tests/                    46 tests, no network access needed
docs/INVENTRY_SUPPORT_EMAIL.md
```

## Tests

```bash
python -m pytest tests -q
```

No network, no credentials, no InVentry. BrightHR responses are stubbed and
InVentry is faked, so the whole thing is verifiable before either vendor is
reachable.

## Deployment

Once dry-run logs look right for a few days:

```powershell
# Preferred: scheduled task, every 5 minutes, still dry run
.\deploy\install_scheduled_task.ps1

# Live, once InVentry access is confirmed
.\deploy\install_scheduled_task.ps1 -Apply -User "SDI\svc_brighthr"
```

Then watch `logs\sync.log` daily for the first week, per the handover.

## When InVentry reply

1. Fill the `INVENTRY_*` settings in `.env` from their answer.
2. Correct the table and column names — the defaults are the handover's guess,
   not confirmed by the vendor.
3. `python sync.py --check` to prove the connection reads.
4. Run dry for a few days, then `--apply`.

If they offer a REST API or insist on a stored procedure instead of direct
writes, add a class to `inventry_client.py` implementing `get_on_site`,
`sign_in` and `sign_out`. Nothing else changes.
