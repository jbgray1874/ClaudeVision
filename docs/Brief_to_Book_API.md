# Brief to Book — queuing an estimate from another site

For the developer of an internal site that wants to send a typed brief to SDI Estimating
Intelligence and show the resulting costing workbook. Written 6 October 2026 (D-401).

## Where the service is

The service runs on the SDI Intelligence server, `http://<SDI Intelligence server>:8071`, with
the estimating runner beside it. (Until 2 November 2026 it ran on James's laptop at port 8072;
the endpoints and payloads are the same.) Ask James for the hostname and for your site's key.

## Authentication

Every request carries the header `X-SDI-Key: <your key>`. Your site has its own key
(`SDI_PARTNER_KEYS` on the service), never the portal's.

A site's key does exactly what this document describes and nothing else (10 November 2026):
`POST /api/estimate/brief` (and `/api/estimate/llm`), and `GET` on its own runs, their summary
and their files. Every other estimating endpoint answers `403`, and a run another site (or the
portal) queued answers `404`, as if it did not exist. The file browser and the database stay
closed to it.

The service answers cross-origin requests only from origins listed in `SDI_ALLOWED_ORIGINS`.
Give James your site's origin (scheme, host, port) so it is added. If your site calls the
service from its server rather than from the browser, CORS does not apply.

## 1. Queue a run from a brief

```
POST /api/estimate/brief
Content-Type: application/json
X-SDI-Key: <your key>

{
  "client": "M&S",
  "reference": "0359962",
  "units": 20,
  "quantity_breaks": [50, 100],
  "brief": "20 off half-A4 landscape ticket holders. 1.2 mm mild steel, 212 x 150 face with a 120 x 170 base, powder coated RAL 7021 black grey. 400 micron printed card insert 210 x 148.5. Four clear self-adhesive bumpers on the base.",
  "email_to": "tim.wilkes@wearesdi.com; dave.wright@wearesdi.com",
  "delivery_postcode": "LE19 1WP"
}
```

Fields: `client` and `reference` name the folder the job is filed under (letters, digits, dashes
and spaces survive; anything else is dropped). Use the new enquiry's own number: the run clears
that reference's working folder, so a past job's number would overwrite its staging. `units` is
the quantity the estimate is run at; `quantity_breaks` are the other quantities to price on the
same workbook (optional, up to twelve). `brief` is 40 to 4,000 characters; one construction, not
alternatives. A brief outside that is refused with a `400` that says why, never cut. `email_to`
is optional: absent, the book is filed and not sent. `delivery_postcode` is optional: where it
goes, filed as the run's delivery declaration.

Every fact the brief states outranks the model's guess, so a brief with labelled lines costs
firmer than prose. The portal's app joins its boxes into the brief like this:

```
A floor-standing gondola end with three shelves and a printed header.
Overall size: 1800 mm high x 1330 mm wide x 450 mm deep.
Materials and thicknesses: 1.2 mm mild steel; 18 mm MDF shelves.
Finish and colour: Powder coated RAL 9005.
Print and graphics: Printed header 1330 x 300, 3 mm foamex.
Fixings and assembly: Flat-packed, four levelling feet.
Lighting: None.
Load: 15 kg a shelf.
Packing: Individually boxed, palletised.
```

Response, immediately:

```
{ "run_id": "3f1c9a2b7d4e", "output_path": "\\\\sdi-dc01\\...\\M&S\\0359962\\2026-10-06_1407_20off",
  "drawing_folder": "...", "waiting_behind": null, "enquiry_brief": "filed" }
```

`enquiry_brief` must read `filed`. Any other value means the brief did not reach the job folder
and the run will read nothing; treat it as a failure and show the message.

Errors: `400` with a `detail` sentence (empty, too short or too long a brief, bad quantity, bad
e-mail address); `401` wrong key; `409` the same client and reference is already running (the
message names the run to wait for); `503` no runner is connected, so nothing can run the job.

## 2. Follow the run

```
GET /api/estimate/{run_id}
X-SDI-Key: <your key>
```

Returns the run: `status` is `queued`, `running`, `done` or `error`; `log` is the run's own
lines (show the last few); `seconds` is elapsed; `deliverables` is filled when `status` is
`done`, one entry per file with `name` and `path`. Poll every five seconds. A brief-only run
takes a few minutes; a run that waits behind another job on the one runner takes as long as that
job. If the service restarts, the run id is forgotten (`404`): the files, if filed, are on the
share at `output_path`.

```
GET /api/estimate/{run_id}/summary
X-SDI-Key: <your key>
```

The run reduced to what a page shows: `stage` (`queued`, `starting`, `reading`, `checking` ...
`done`) with `stages` and their elapsed seconds while it runs; once done, `unit_cost_gbp` (the
provisional figure a unit), `caution` (the sentence to show beside it), and `summary_html`,
`workbook_xlsx` and `report_html` as download paths.

## 3. Fetch the book

```
GET /api/estimate/{run_id}/deliverables/{name}
X-SDI-Key: <your key>
```

`name` is one of the names in `deliverables`. The workbook is the `.xlsx`, the report the
`_report.html`, the covering note the `.html` with `covering` in its name. The service serves only
the files the runner filed for that run; a name it did not file is `404`, and a run that is not
`done` is `409`.

Show the workbook as a download and the report inline. Read the AI Explanation tab first: it
lists what the brief fixed, what the model assumed, and what an estimator must replace.

## What the book is, and is not

- It is a provisional costing for an estimator. It is never a quotation and must not be shown
  to a customer. The customer quote is withheld until an estimator releases it on the
  estimating page.
- Every size the brief states is stamped `enquiry_brief` on the record; every size it leaves
  open is an assumption named on the sheet for confirmation. The model never states a price:
  prices come from SDI's own catalogue, price history and research, each line naming its source.
- A brief that offers alternatives ("plywood or steel") is costed on the first and the rest
  are listed as options not costed. Send one construction per run.
- One runner runs one job at a time. A queue is a queue.

## In the portal

The same run is available as an app at `/app/brief-estimate.html` (the app portal, signed in),
which posts to the same endpoint and shows the same stage, figure and files, and e-mails the
book to whoever ran it.

## Worked example in JavaScript

```js
const BASE = "http://<SDI Intelligence server>:8071", KEY = "…";
const h = {"Content-Type": "application/json", "X-SDI-Key": KEY};
const q = await fetch(`${BASE}/api/estimate/brief`, {method: "POST", headers: h, body: JSON.stringify(payload)});
const {run_id, enquiry_brief} = await q.json();
if (enquiry_brief !== "filed") throw new Error("brief not filed");
let run;
do {
  await new Promise(r => setTimeout(r, 5000));
  run = await (await fetch(`${BASE}/api/estimate/${run_id}`, {headers: h})).json();
} while (run.status === "queued" || run.status === "running");
const book = run.deliverables.find(d => d.name.endsWith(".xlsx"));
const url = `${BASE}/api/estimate/${run_id}/deliverables/${encodeURIComponent(book.name)}`;
```
