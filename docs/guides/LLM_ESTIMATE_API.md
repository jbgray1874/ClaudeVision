# LLM Estimate API — one call with a prompt and an image

*For Muhammad's portal (D-526). The endpoint runs on James's laptop today and moves to
SDI-APP01 later — **only the base URL changes**, nothing in your code.*

## What it is, and what it is not

You send a **prompt** (the enquiry brief: what the product is, its size, materials,
anything the image cannot show) and an **image** (PNG/JPG/WEBP, or a PDF sheet). The
service queues an **LLM-only concept read** — the same run the SDI estimating page queues —
and files a full set of deliverables: the SDI estimate workbook (.xlsx), a self-contained
**covering-note HTML that is the summarised estimate**, and the full report.

Two things to show your users honestly, every time:
- The figure is a **measurement of the vision model, not an estimate** — it prices the work
  it can see and is silently short of what it cannot. The workbook says DRAFT. Do not quote it.
- The **customer quotation** deliverable is withheld by the service until an SDI estimator
  releases it. Your download of it will return 403 until then — that is correct behaviour.

## Base URL and key

| Where | Base URL |
|---|---|
| Today (James's laptop, same network) | `http://<laptop-ip>:<port>` — James sends you the exact address |
| Later (SDI-APP01) | `http://10.0.0.5:8071` |

Keep the base URL as one setting in your code (it is `$BASE` / `base` below). Check it
answers before anything else: `GET {base}/api/health` with the key header returns the
service's status and the code version it is running.

Every request needs the header `X-SDI-Key: <key James gives you>`.
If your portal calls from **browser JavaScript**, the page's origin must be added to the
service's `SDI_ALLOWED_ORIGINS` (ask James); calling from **your backend** needs no CORS.

## 1. Queue the estimate

`POST {base}/api/estimate/llm` — multipart/form-data:

| field | required | meaning |
|---|---|---|
| `prompt` | yes | the enquiry brief, free text — stated facts outrank what the image suggests |
| `image` | yes | PNG / JPG / WEBP / PDF, up to 40 MB |
| `client` | no | customer name (drives terms + history), default `SDI` |
| `reference` | no | your enquiry/drawing number — names the folder and the workbook; default is a timestamp |
| `quantities` | no | e.g. `1, 25, 50, 100` — costed at the first, quantity-break columns for the rest; default `1` |
| `delivery_postcode` | no | where the order would be delivered; rides the delivery line for the per-mile calculator |

```bash
curl -H "X-SDI-Key: $KEY" \
  -F 'prompt=M&S tote trolley, mild steel 25x25 box frame ~1035x830x880, 16mm melamine top, 4x 100mm braked castors, 49 kg stated' \
  -F 'image=@trolley.png' -F 'client=M&S' -F 'reference=0356456' \
  -F 'quantities=1, 25, 50, 100' \
  "$BASE/api/estimate/llm"
```

```js
const fd = new FormData();
fd.append("prompt", promptText);
fd.append("image", fileInput.files[0]);
fd.append("client", "M&S");
fd.append("quantities", "1, 25, 50");
const r = await fetch(base + "/api/estimate/llm",
                      {method: "POST", headers: {"X-SDI-Key": KEY}, body: fd});
const {run_id, poll, summary} = await r.json();
```

Returns `{run_id, poll, summary, note, ...}`. A `503` means no estimating runner is
connected — the run machine is off; try again when it is up.

## 2. Poll until done

`GET {base}/api/estimate/{run_id}` → `{status: "queued" | "running" | "done" | "error", ...}`.
Poll every 15–30 s. A run takes minutes, not seconds — the model reads every page.

## 3. Read the summary and render it

`GET {base}/api/estimate/{run_id}/summary` →

```json
{
  "status": "done",
  "unit_cost_gbp": 123.45,
  "provisional": true,
  "summary_html": "/api/estimate/<id>/deliverables/<...covering_email.html>",
  "workbook_xlsx": "/api/estimate/<id>/deliverables/<...>.xlsx",
  "report_html":   "/api/estimate/<id>/deliverables/<...report.html>",
  "deliverables":  [{"name": "...", "download": "/api/estimate/<id>/deliverables/..."}],
  "caution": "..."
}
```

- **The summarised estimate** = fetch `summary_html` (with the key header) and embed it in
  your page (an iframe `srcdoc`, or a sanitised container). It is self-contained HTML:
  the figure, what needs an estimator's eye, and the workings, written for a reader.
- **The SDI estimate s/sheet** = link `workbook_xlsx` as the download.
- Always show `caution` and the `provisional` state beside the figure.

## 4. Download rules

Downloads are by run id + the deliverable's **name** only — the service never serves a path
you typed, and the customer quotation returns **403 until an SDI estimator releases it**.
Run ids live in the service's memory: after a service restart, old ids return 404 (the
files are still filed on the SDI share — ask James if one is needed back).

## Good prompts (this decides the quality)

State: what it is, overall size, materials and gauges, counts of bought items ("4 x
castors — the drawing's bracket numbers are callouts, not quantities"), the stated weight
if the sheet gives one, finish ("powder coat assumed, colour neutral"), and the order
quantities. Facts you state outrank what the model thinks it sees.
