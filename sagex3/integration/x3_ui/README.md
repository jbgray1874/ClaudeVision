# Sage X3 UI automation (`x3_ui.py`)

This exports data sets from the Sage X3 web screens automatically, as a user would: it opens a screen, sets the filters, presses Search and Export, and saves the file. It's for use **until** Acuity give API / batch-server access (SCRUM-329). After that, the same data sets come from the API, and the files the Live Orders engine reads keep the same names.

- **Read-only by design.** It opens enquiries and export screens and downloads files. Any step aimed at Save, Create, Delete, Post or Validate is refused, and imports aren't automated.
- **It runs on James's PC,** signed in as him. The cloud session can't reach X3, so it can't be run or tested there against X3. It was tested on 19 Nov against a mock screen: fill, untick, search, wait, download, and the Save guard.

## Set up once (PowerShell, in this folder)

```
pip install playwright
python -m playwright install chromium
python x3_ui.py login
```

`login` opens a browser. Sign in to X3 yourself (Sage ID / MFA if asked), then press Enter in PowerShell. The session is saved in `%USERPROFILE%\.sdi\x3_session.json`. **It is your login:** never in git, and never emailed. Delete it to sign out. If X3 later asks you to sign in again, run `login` again.

**Check the address pattern first:** open any screen in X3 (e.g. Order lines) and compare the browser's address bar with `function_url` in `datasets.json`. If it differs, paste the real pattern, with `{folder}` and `{code}` in place of the folder and function code.

## Capture each screen once

```
python x3_ui.py record CONSCSP
```

The X3 screen opens with Playwright's inspector. Click **Pick locator**, then click each thing in turn:
- the filter boxes you set (dates, ticks);
- **Search**;
- the **export** button (Excel / CSV export on the right-hand panel).

The inspector shows each selector. Put them in that data set's `steps` in `datasets.json`, in the order you'd do them (see `_example_steps`).

Selector forms:
- `label=Start date`: a box by its label (the most robust);
- `text=CSV export`: a button or link by its text;
- `role=button:Search`: by role and name;
- or the CSS selector the inspector gives.

Dates can be relative: `{today}`, `{today-90}`, `{today+180}`, `{first_of_month}`, written in `date_format` (dd/mm/yy).

## Run

```
python x3_ui.py list                   # what's configured, and what still needs capturing
python x3_ui.py export                 # every data set marked "enabled"
python x3_ui.py export so_lines boms   # just these
python x3_ui.py export --show          # watch it work
```

Files go to `%USERPROFILE%\SDI_X3_exports\<date>\<name>.csv|xlsx`, with `run_log.json` (OK / failed, file, size). Any step that fails leaves a screenshot, `<name>_FAILED.png`. The run carries on with the other data sets.

**Scheduled:** in Windows Task Scheduler, create a daily task with:
- Action: `python`
- Arguments: `C:\SDI_X3\x3_ui.py export`
- Start in: `C:\SDI_X3`

## The data sets (`datasets.json`)

| Group | Data sets | X3 screen |
|---|---|---|
| Live Orders | `so_lines` (CONSCSP), `po_lines` (CONSCPO), `works_orders`, `wo_materials`, `wo_operations`, `stock` | Enquiries. The works-order and stock function codes are **to confirm** on the site |
| Master data | `products`, `boms`, `routes`, `customers`, `suppliers` | **Exports** (Usage → Imports/exports → Exports), with the standard template, exported **to the client** so the browser downloads it |
| Reports | `stock_moves` (CONSSMJ), `deliveries` (CONSCSF), `receipts` (CONSCPS) | Enquiries (off by default) |

A data set with no `steps` is skipped until it's captured.

## Next

1. On the training site: confirm the address pattern, capture `so_lines` and `po_lines` first, run them, and send the files to Claude.
2. **The X3 source adapter:** from the real exported layouts, a small module maps the X3 files onto the grids `build_live_orders.py` reads today (SOH / POH / SMR / WOR). Then the board and dashboard run on X3 data with no other change.
3. When Acuity give API access, the same data sets switch to the API. The rest of the chain stays the same.

## Good practice

- Keep it gentle: there's a pause between data sets, and one run at a time.
- Use the training site until agreed. In production, read-only screens only.
- If Sage X3 is updated and a screen changes, a step fails with a screenshot. Re-capture that screen.
