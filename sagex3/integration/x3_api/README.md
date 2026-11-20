# Sage X3 API: read-only (`x3_api.py`), plus the test-company estimate loader (`x3_load.py`, section 4)

This reads the Live Orders data sets straight from X3 through Sage's API, with no browser and no Sage ID check. It replaces the screen automation (`x3_ui.py`) once it works on our site. Written 20 Nov 2026.

- **Read-only:**
  - GraphQL mutations are refused, REST is GET only, and nothing writes to X3;
  - the connected application's user should also have enquiry-only rights, so X3 enforces it too.
- **Training site first** (sdi-displays-trn, folder SDIMIG). Production only after it's proven, and with the same read-only set-up.
- **Tested on 20 Nov** against a mock X3 that checks the signed token and the endpoint header. The test ran:
  - probe, schema, draft, paging, line explode and the mutation guard;
  - then the adapter, the engine and the portal endpoint.

  **Not yet tested against the real site:** Sage's developer pages block automated reading, so the exact URL and token form are found on the site by `probe`, not assumed.

## 1. Create the connected application (X3, once, about 5 minutes)

**Administration → Administration → Authentication → Connected applications → New connected application** (where you were today):

| Field | Enter |
|---|---|
| Name / Description | `SDI Live Orders read-only` |
| Token validity / lifetime | `600` (seconds) |
| Expiration | about 3 months ahead (renew it later) |
| GraphQL / Sage X3 Services (if there's a tick box) | ticked |
| User / allowed users (if asked) | the X3 user it runs as: see the note below |
| Endpoint (if asked) | the training endpoint for folder **SDIMIG** |

**Save.** X3 then shows the **client ID** and the **secret**:
- **the secret is shown once only;**
- copy it straight into `python x3_api.py setup` (step 2), which hides what you type;
- never put it in chat, email, a screenshot or a file in git;
- if it's lost, regenerate it on the same record.

**The endpoint name:** Administration → Endpoints, the line whose folder is SDIMIG. `setup` asks for it.

**The X3 user it runs as:**
- **Best:** a user with an enquiry-only function profile.
- **For a first test on the training site,** your own login works. The client can't write anyway, but the token would carry your rights. Swap to a read-only user before production.

## 2. On your PC (PowerShell, in this folder)

```
python x3_api.py setup      # site, folder, endpoint, client ID, X3 user, secret (hidden) -> %USERPROFILE%\.sdi\x3_api.json
python x3_api.py probe      # finds the URL / token form X3 accepts, and saves it
python x3_api.py schema     # lists what the API offers; * marks works orders, stock, orders, products, BOMs, routes
python x3_api.py draft      # writes api_datasets.draft.json from the schema
```

**Send Claude the output of `probe` and `schema`.** Neither shows the secret. If `probe` finds no form, it lists what X3 answered to each try, and that's enough to fix it.

Then check `api_datasets.draft.json`, set `"enabled": true` on the ones to pull, and save it as `api_datasets.json`:

```
python x3_api.py pull       # -> %USERPROFILE%\SDI_X3_exports\<date>\works_orders.csv/.json, so_lines ..., api_log.json
```

The file names are the same as the screen exports, so the rest of the chain doesn't care where they came from.

**REST instead of GraphQL:** a data set can name `"class"` and `"representation"` (X3 classes such as `SORDER` and `ITMMASTER`) in place of `"path"`. One-off REST query:

```
python x3_api.py rest ITMMASTER ITMMASTER --count 5
```

## 3. Then Live Orders runs on X3 data

```
cd ..\..\production\live_orders
python run_x3.py --pull api --products <ZSDIITM.xlsx or products.csv> --boms <BOM .txt> --routes <route .txt>
```

The steps:
1. pull;
2. adapter (`x3_source.py`, column map `x3_columns.json`);
3. engine;
4. write `%USERPROFILE%\SDI_X3_runs\latest.json` and `status.json`.

The portal endpoint `/api/live-orders/latest` serves that file.

**Check the column map once,** with the first real pull:

```
python x3_source.py %USERPROFILE%\SDI_X3_exports\<date> --check
```

It shows which X3 column fed each Live Orders field. Fix anything marked **NOT FOUND** in `x3_columns.json`.

## 4. Loading estimates into X3: `x3_load.py` (the write half; 20 Nov 2026)

James, 20 Nov: "We also need to be able to save estimates to Sage X3, not just load up files." `x3_load.py` sends an Estimate → X3 run's product, BOM and route (the same rows as its three load files) as GraphQL **create** mutations. The portal's Estimate → X3 page runs it (Check, then Load). `x3_api.py` stays read-only.

**Safety, in the code:**
- **test company only**: the training site and endpoint `X3ERPV12_SDIMIG`, nothing else. Production live data is never changed. Live needs a code change and sign-off;
- **create only**: the one mutation it can build is `create`, and it reads X3 first and skips anything that exists (a product with that code, any BOM or route for that part). Nothing existing is changed or deleted;
- no retries on a write; stops at the first refusal; every load logged (`x3_load.json` in the run, `x3_load_history.jsonl`); the secret is never printed or logged.

**Set-up (once, on the machine that runs the portal; PowerShell as administrator on SDI-APP01):**
1. In X3 (training): a **second connected application**, e.g. `SDI Estimate loader (test)`, like step 1, for endpoint X3ERPV12_SDIMIG. Its X3 user needs **create rights on products, BOMs and routings** (your own login works for the first test, as for the read-only one).
2. Whether X3 offers create mutations for product / BOM / routing at all depends on the API set-up. If `mutations` (step 4) lists none, they're switched on in X3 as admin: Development → X3 Builder → API / GraphQL operations (`GESAPIOPE`), "mutations based on X3 class" for the product (ITMMASTER), BOM and routing classes. No Acuity needed.
3. ```
   cd C:\SDI_X3\repo\sagex3\integration\x3_api
   $env:X3_LOAD_CONFIG = "C:\ProgramData\SDI\x3_load.json"
   python x3_load.py setup        # site, endpoint (copied from x3_api.json), the new client ID, user, secret (hidden)
   python x3_load.py mutations    # READ-ONLY: what X3 lets us create, and how each load-file field maps onto it
   ```
4. **Send Claude the `mutations` output** (no secret in it). It shows, for the product, BOM and route: the X3 create used, each field (ITMREF → code …), the enum values, anything not mapped, and any field X3 requires that our files don't have. The candidate names are in `MAP`; anything that doesn't map is fixed there, not guessed.
5. On a PC instead of the server: leave out the `$env:` line (default `%USERPROFILE%\.sdi\x3_load.json`).

**Use:** the portal page (Check, then Load). Or by hand, on a run folder:
```
python x3_load.py plan <run folder>                                   # dry run
python x3_load.py load <run folder> --apply --confirm <part code>     # creates what X3 hasn't got
```
**Before the first real load:** read the plan's notes. X3 local-menu numbers in the files (use status 2, time unit 2, WO mode 4 …) are sent as X3's enum value at that position, and the plan shows each one ("USESTA 2 -> availableToUse") to confirm.

**Tested (20 Nov) against a fake X3** (schema with create mutations; 27 checks): guard refuses the live site and other endpoints; nothing sent without the schema, a READY run and the typed part code; product → BOM → route in order; existing records skipped; a refusal stops the rest; existence that can't be checked = STOP; no create offered = STOP with the how-to; update / delete can't be built; no secret in any log. **Not yet run against the real X3**: the mutation names and input fields come from X3's schema at step 4.

## Private files (never in git or email)

- `%USERPROFILE%\.sdi\x3_api.json`: holds the secret.
- `%USERPROFILE%\.sdi\x3_schema.json`: the schema. Not secret, but no need to share it.
- `x3_load.json` (`X3_LOAD_CONFIG`; on the server `C:\ProgramData\SDI\x3_load.json`, locked down by the server script): the WRITE application's secret.

**To revoke:** delete the connected application in X3. Every token stops working.
