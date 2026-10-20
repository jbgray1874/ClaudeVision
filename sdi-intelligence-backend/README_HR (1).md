# BrightHR → InVentry pipeline (HR ingestion)

Two stages, with a snapshot on local disk in between, all wired into the intranet.

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
| `hr_load_inventry.py` | **Stage 2** — snapshot → InVentry CSV |
| `hr_routes.py` | Backend endpoints (`/api/hr/...`) |

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
POST /api/hr/sync     # pull + load            (header: X-SDI-Key: <key>)
POST /api/hr/pull     # pull + store only
POST /api/hr/load     # load latest snapshot only
GET  /api/hr/status   # last pull + load summary
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
- **Secrets** — all credentials live in `.env` (git-ignored), never in code.
- **PII** — names/emails only; logs record counts, not people. Keep `HR_SNAPSHOT_DIR`
  and the InVentry folder locked down (NTFS perms) and in your UK GDPR records.

> Scope note: this syncs the **active staff roster** into InVentry. Live "who's on
> site" attendance (BrightHR **Blip**) is a separate data source and a separate
> endpoint — easy to add later once this is solid.
