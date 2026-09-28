# SDI Intelligence — App Portal

A mobile-first PWA that lists every SDI Intelligence app. Served by `app.py` at
**`/app/`** (the trailing slash matters — see below).

It is a second *front end* over the same catalogue as the intranet portal, not a
second product.

```
services.json  ─┬─→  sdi-intelligence-portal.html   (intranet, desktop, full detail)
                └─→  appportal/index.html           (phone, installable, read-only)
```

## Adding or changing an app

Edit **`../services.json`**. Both portals pick it up on next load — there is no
second place to update.

Each entry takes the fields the intranet portal already used (`id`, `name`,
`status`, `cls`, `desc`, `detail`, `sections`, `inputs`, `outputs`, `tech`,
`phase`, `invoke`, `link`, `view`) plus two new ones:

| Field      | Meaning                                                              |
|------------|----------------------------------------------------------------------|
| `category` | Grouping heading in the app portal. See `ORDER` in `index.html`.     |
| `surface`  | `both` (default), `intranet`, or `app`.                              |

`surface` is the important one. **`intranet`** means the app needs the on-prem
network — the file shares or SDILive — so it is hidden from the app portal.
`BrightHR Ingestion` is marked this way because its controls call endpoints that
touch the watched folder.

`surface` is a *presentation* filter, not a security boundary. It decides what is
listed; it does not stop anyone calling an endpoint. Real access control is the
next phase (below).

## Files

| File                      | Purpose                                              |
|---------------------------|------------------------------------------------------|
| `index.html`              | The whole app — shell, list, search, detail view.    |
| `manifest.webmanifest`    | Install metadata (name, icons, colours, standalone). |
| `sw.js`                   | Service worker: shell cached, catalogue network-first.|
| `icon-*.png`              | Home-screen icons, generated (see below).            |

Icons are drawn programmatically rather than exported from a design tool, so they
can be regenerated at any size without a dependency on Illustrator or a font
being installed. The generator lives in the commit history for this directory.

## Routing — the trailing slash

`app.py` serves the portal at `/app/` and 308-redirects `/app` → `/app/`.

This is not cosmetic. Served at `/app` (no slash), the browser resolves every
relative URL in the page against `/`, so `manifest.webmanifest`, `sw.js` and the
icons all 404 and the app silently stops being installable. If you ever move this
route, keep the trailing slash.

## Offline behaviour

The service worker caches the shell and the last catalogue response. On a phone
with no signal the app opens and shows the last catalogue that device downloaded,
with an "Offline" banner. The catalogue fetch has an 8-second timeout so a stalled
network falls through to the cache rather than hanging on "Loading…".

File-share traffic (`/api/file*`) is **never** cached — those are real company
documents and must not sit in a device cache.

## Status: what this is not, yet

This is the shell. Two things must happen before it goes anywhere near the
public internet:

1. **Identity (next).** The service authenticates with a single shared
   `X-SDI-Key`. That cannot tell you *who* did anything, which is useless for an
   audit trail and unacceptable for a portal reachable off-site. This needs
   Microsoft Entra ID SSO, per user.

2. **Exposure (after that).** Entra Application Proxy or a Cloudflare Tunnel, so
   the on-prem service is reachable without opening an inbound firewall port.
   Do not port-forward this.

Until both are done, `/app/` is intranet-only, exactly like the main portal.

### Known issue — secrets in the repository

Two items need rotating, and neither is fixed by this directory:

- `sdi-intelligence-portal.html` has a live `SDI_API_KEY` hardcoded in the page
  source, served to every browser that loads the portal.
- `.env` is tracked in git, including the database login and the BrightHR
  credentials, despite `config.py` stating it is never committed.

Adding `.env` to `.gitignore` (done) stops *future* ones being added. It does not
untrack the existing file, and the values remain in git history regardless — so
rotating the credentials is the actual fix, not deleting the file.
