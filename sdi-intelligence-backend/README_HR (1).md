# BrightHR → InVentry pipeline (HR ingestion)

Two stages for the staff **roster**, plus a third for live **presence**, with a
snapshot on local disk in between, all wired into the intranet.

```
 COO clicks "Run ingestion"  ─▶  /api/hr/sync
                                   │
              Stage 1: PULL  ──────┤  hr_pull.py
              BrightHR API ──▶ active staff ──▶  snapshot on disk
                                   │            C:\SDIIntelligence\hr\snapshots\
                                   │              brighthr_<UTC>.json   (audit)
                                   │              latest.json           (latest good)
              Stage 2: LOAD  ──────┘  hr_load_inventry.py
              latest snapshot ──▶ InVentry CSV (atomic write)
                                   C:\InVentryImports\brighthr_staff.csv
                                          │
              InVentry CSV Automation Service sweeps it ──▶ front-desk tablets
```

**Why a snapshot in the middle:** audit trail of every pull, the load can retry
without re-hitting the API, and the safety guard can compare against the last
good pull before it ever overwrites InVentry.

---

## Files

| File | Role |
|---|---|
| `hr_config.py` | Settings (reads the same `.env`) |
| `hr_brighthr.py` | Auth (pluggable) + paginated fetch + field normalisation |
| `hr_pull.py` | **Stage 1** — pull → store snapshot |
| `hr_load_inventry.py` | **Stage 2** — snapshot → InVentry roster CSV |
| `hr_blip.py` | **Blip** — who is clocked in right now → snapshot |
| `hr_blip_inventry.py` | **Stage 3** — Blip snapshot → InVentry on-site CSV |
| `hr_routes.py` | Backend endpoints (`/api/hr/...`) |
| `tests/` | `python -m pytest tests -q` — no network or credentials needed |

---

## Stage 3 — live presence (fire roll call)

Stages 1–2 sync who *exists*. Stage 3 syncs who is *in the building*, so the
InVentry evacuation list is live rather than manual.

```
 COO clicks "Who's clocked in?"  ─▶  /api/hr/blip     hr_blip.py
      BrightHR Blip clockings ──▶ blip_latest.json + K:\IT\HRSystemsOutput\blip_onsite_<UTC>.json
                                         │
 COO clicks "Load to InVentry"  ─▶  /api/hr/blip/load  hr_blip_inventry.py
      blip_latest.json ──▶ C:\InVentryImports\brighthr_onsite.csv  (atomic)
                                         │
      InVentry CSV Automation Service sweeps it ──▶ on-site register / fire roll
```

`POST /api/hr/blip/sync` does both in one call.

The CSV is the **full current on-site list**: in the file = on site, absent
from the file = signed out. No separate employee-ID mapping is needed — InVentry
matches on the same name + email the roster import already uses.

### Two sources for the same on-site list

| `source=` | File | Notes |
|---|---|---|
| `latest` (default) | `…\snapshots\blip_latest.json` | Full snapshot, **includes email** — the best match key for InVentry |
| `output` | `K:\IT\HRSystemsOutput\blip_onsite_<UTC>.json` | The file the portal **Files view** exposes — the "site signed in" page. Newest wins. |
| *a path* | any of the above | For a one-off file |

`hr_blip.py` deliberately **strips email** from the portal-exposed file (names
only, for PII). Loading with `source=output` therefore recovers each email from
the roster snapshot (`latest.json`) by name. A name appearing twice is left
blank rather than guessed — a wrong email on a fire roll is worse than a missing
one — and anyone still without an email is written **name-only** and counted in
`name_only`, since leaving them off the roll entirely is the more dangerous
failure.

The portal button uses `latest` because it keeps emails without a name lookup.

### ⚠ Confirm with InVentry before going live

The button and the endpoints default to **dry run** (`HR_LOAD_DRY_RUN = true` in
the portal; `?dry_run=true` on the API), which writes the CSV next to the
snapshot instead of into the watched folder. Before flipping it, confirm with
InVentry support:

1. Does the CSV Automation Service accept a **presence/attendance** import, or
   only a staff roster?
2. Does it treat the file as **full current state** (absent = signed out)?
3. What **column headers** does it expect? Ours are in
   `hr_blip_inventry.ONSITE_FIELDS`.
4. Should presence use a **separate watched folder** from the roster import?

### Presence guards (different from the roster guards)

The roster guard protects against wiping the front-desk list. Presence has the
opposite risk: publishing an on-site list that is *missing* people who are in
the building. So the load refuses to publish when:

- the Blip run is **degraded** — some per-employee queries failed, so the list
  may be short (`BLIP_MAX_FAIL_PCT`);
- the snapshot is **stale** — older than `BLIP_MAX_STALE_MINUTES` (default 15);
  a stale roll call is worse than no update;
- **zero on site with query failures** — a broken token looks exactly like an
  empty building. Zero from a *clean* run is published, since an empty site at
  3am is real.

`--force` overrides all three. Everything is written atomically, so InVentry
never sweeps a half-written file.

---

## ⚠ Verify before production (BrightHR's API is early-stage)

1. **Auth grant.** `client_credentials` tokens carry **no user context**; BrightHR
   returns **403** on user-context endpoints. If `/pull` 403s, set `BH_AUTH_MODE=pat`
   in `.env` and paste a **Personal Access Token** (`BH_PAT`).
2. **Endpoint.** Set `BH_EMPLOYEE_URL` to the real employee endpoint from BrightHR's docs.
3. **Scopes.** If required, set `BH_SCOPE`.
4. **Fields.** `hr_brighthr.normalise_employee()` hedges camelCase/snake_case, but
   confirm against one **sandbox** response (`BH_ENV=sandbox`) before going live.
5. **Paging.** Adjust the paging keys in `fetch_employees()` to BrightHR's actual scheme.

---

## Run it

On demand (the COO button) hits the backend:

```
POST /api/hr/sync         # roster: pull + load    (header: X-SDI-Key: <key>)
POST /api/hr/pull         # roster: pull + store only
POST /api/hr/load         # roster: load latest snapshot only
GET  /api/hr/status       # last pull + load + presence-load summary

POST /api/hr/blip         # presence: who is clocked in right now
GET  /api/hr/blip/latest  # presence: last snapshot, no BrightHR call
POST /api/hr/blip/load    # presence: on-site list -> InVentry
                          #   ?dry_run=true   write beside the snapshot, not the watched folder
                          #   ?source=output  load the JSON the portal Files view exposes
                          #   ?force=true     override the presence guards
POST /api/hr/blip/sync    # presence: blip + load in one call (same query params)
```

Or scheduled, via Windows Task Scheduler (same code, no button):

```powershell
# nightly at 01:00 — pull, then load a few minutes later
python C:\path\hr_pull.py
python C:\path\hr_load_inventry.py
```

`hr_pull.py` exits non-zero on failure, so Task Scheduler records it.

---

## Wire the button into the portal

In the BrightHR service view, add a button that calls the backend:

```html
<button id="hr-sync" class="run">Run ingestion</button>
<pre id="hr-out" class="console show"></pre>
<script>
document.getElementById('hr-sync').onclick = async () => {
  const out = document.getElementById('hr-out');
  out.textContent = 'Running…';
  try {
    const r = await fetch('https://<your-backend-host>:8071/api/hr/sync', {
      method: 'POST', headers: { 'X-SDI-Key': '<same key as backend .env>' }
    });
    const d = await r.json();
    out.textContent =
      `Pulled ${d.pull.pulled}, active ${d.pull.active}\n` +
      `Wrote ${d.load.written ?? '-'} to InVentry (${d.load.status})`;
  } catch (e) { out.textContent = 'Error: ' + e; }
};
</script>
```

---

## Safety guards (built in)

- **Atomic writes** — snapshot and InVentry CSV are written to a temp file then
  `os.replace()`d, so a reader never catches a half-written file.
- **Zero/low-record guard** — `HR_MIN_RECORDS`: the load refuses to overwrite
  InVentry with an empty roster; the pull won't advance "latest good" on a zero pull.
- **Drop guard** — `HR_MAX_DROP_PCT`: a sharp fall in active staff vs the last good
  pull is flagged for review rather than pushed through blindly.
- **Secrets** — all credentials live in `.env`, never in code. (This file was
  previously committed to the repo despite this note; it was removed from
  tracking on 14 Aug 2026 and the credentials in it need rotating.)
- **PII** — names/emails only; logs record counts, not people. Keep `HR_SNAPSHOT_DIR`
  and the InVentry folder locked down (NTFS perms) and in your UK GDPR records.

> Scope note: stages 1–2 sync the **active staff roster** into InVentry. Live
> "who's on site" attendance (BrightHR **Blip**) is stage 3 above — built, tested
> and wired to the portal button, running in dry run until InVentry confirm the
> presence import.
