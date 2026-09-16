# Where SDI's build-and-price knowledge lives

One page, so the answer to "where did that figure come from" is never archaeology.
Three tiers, in the order the engine asks them. Every figure on an estimate traces to
exactly one of these, and the Supplier column on the sheet now names which
(SDI Live UDEF · Estimating spreadsheet · Estimator stated · Web listing · AI ESTIMATE).

*This file is rendered on the SDI Estimating Intelligence architecture page (laptop and
server) straight from the repo. Key register names are test-pinned —
`test_the_knowledge_map_is_not_stale.py` fails the suite if a listed register leaves the
code — which keeps the NAMES honest; the prose and the counts age like any document and
carry their dates. Decisions and changes are logged in `docs/CHANGE_REGISTER.md`.*

---

## How the system learns — and how one job's lessons cannot pollute another's

Every estimator finding lands in exactly one of three homes, and the home decides its
reach:

1. **Generic engine rules** improve every relevant future estimate automatically —
   roll goods price by the length consumed; both sheet orientations are tried and the
   better valid yield taken; the requested quantity breaks land in one workbook; the
   customer's own rebate and absorption terms apply by name; catalogue pack prices
   convert to the price of one; a confirmed exact-SKU price beats a derived
   material-family median; generic labour rows name the work they contain. These carry
   no job's assumptions — they are how estimating works, proven by a test each.

2. **Gated stated methods and figures** apply only to the job family they were stated
   for, with named and dated provenance — Howard's bag-and-box packing method and his
   PACP 30/hour apply to eligible acrylic display work and decline, by name, on a steel
   fabrication or a joinery tray; Tony's board knowledge is building the joinery side
   the same way. When later evidence disagrees with a stated figure, the disagreement is
   visible against a person and a date, never against a silent constant.

3. **Per-job confirmations** (the `<drawing>_confirmed.json` answers file) travel with
   one drawing pack and govern only it — a tape length, a gauge ruling, an order
   quantity, a "delivery not required". They cannot contaminate another estimate.

Where a future drawing provides stronger evidence, that job's own drawing or CAD data
takes precedence over anything stated — source precedence arbitrates, and the displaced
reading stays on the record.

**The success criterion:** the first run of the next comparable job should begin where
the last corrected run of its predecessor finished. Estimator feedback should surface
NEW knowledge, not rediscover defects already resolved — and the change register below
is how that is held: every decision carries its test, so a change that would quietly
undo a resolved defect fails the suite before it ships.

---

## Tier 1 — SDI Live (the systems of record)

| Source | What it holds | Access |
|---|---|---|
| `SDILive.dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING` | Part codes, descriptions, supplier names, system cost — what purchasing pays against | read-only (the ERP's own table) |
| `SDILive.dbo.bought_in_parts` | 44 rows, **0 active** (as at 15 Sep 2026) — the engine's UDEF query still unions it; effectively retired | read-only |
| `SDILive.AIEstimating.BoughtInCatalogue` | Our catalogue: 84 live rows (as at 15 Sep 2026) (migrated dbo.bip, workbook harvest, web-indicative, seeds) with `source` tags and effective dates | ours, written by `catalogue_loader.py` |
| `SDILive.AIEstimating.JobBoughtInMaterials` | Raw per-job provenance from harvested workbooks — one row per bought-in line per drawing | ours, written by `batch_ingest_historical.py` |
| `SDILive.AIEstimating.Supplier` / `CommercialRate` | Supplier identities; commercial per-order rates | ours |

Derived-at-run-time from Tier 1 (never stored): the plastic sheet £/m² —
`_resolve_board_sheet_rate_gbp_per_m2` computes the median across UDEF's plain-stock
lines on every run, which is why the acrylic sheet priced £48.89 on 8 Sep and £47.21 on
15 Sep: the catalogue moved and the rate moved with it.

## Tier 2 — the estimators' own documents

| Source | What it holds | State |
|---|---|---|
| Historical estimating workbooks (the estimates share) | Priced BOM lines, sheet prices, labour lines from jobs quoted and won | Harvested into `AIEstimating.*` by `batch_ingest_historical.py`. **Only 32 rows / 2 workbooks landed as at 15 Sep 2026 — the re-ingest over the share is the open action.** |
| The live `spreadsheet` price connector | — | Points at the **blank** template, so it contributes nothing on any job. The corpus road above is the real one. |
| `src/tim_rate_card.json` | Department hourly £ rates, from Tim's own sheet | The card wins; the config table is only the fallback when it is absent |
| Per-job answers files (`docs/7332-01_confirmed.example.json` pattern) | Job-scoped confirmed facts an estimator has ruled on | Governs that job only — a rate correction is never left here (see Laser (Acrylic), which moved to the register because "a rate correction is how the department runs, not a decision about one stand") |

## Tier 3 — `src/config.py` (one file; the named registers inside it)

**Money may not live here undated.** A price in source control cannot go stale visibly —
so config holds *facts, rates the shop stated, and fallbacks that name themselves*, and
the tests police the boundary.

| Register | What it holds | Rule |
|---|---|---|
| `SHOP_STATED` | **Source-controlled shop-stated operating figures.** Every figure the shop has stated: weld 30 / dress 20 min per weldment, brush-before-plate 40 min, plater pack + £120 freight, linebend 0.5 min/bend, acrylic laser 95 parts/hr — values as plain numbers, with who/when/which-job/what-unit per figure in `SHOP_STATED_PROVENANCE` (one shared header mis-attributed the 0355255 figures to 7332-01 — caught in review, 15 Sep) | Other tables read from it; changing a stated figure anywhere else changes nothing |
| `ESTIMATOR_STATED_PRICES` | Prices an estimator gave us (dated, attributed) | Always **second to the system** — used only where no priced source answers, rendered "Estimator stated", disagreement reported when both answer |
| `ROLL_GOODS_CATALOGUE` | Packaging facts only (roll lengths). **No money** — the price comes from Tier 1 or the stated register | |
| `PACKING_METHOD` | How an order packs — PACK56 bag per unit (his priced sheet's bag; his email typed PACK13 — sheet beats email, confirmation asked), BOX481 boxes at Howard's 1/1/3/9 steps, his name and date on it. Gated to eligible acrylic display work | Holds NO money: consumable prices come live from UDEF each run; a missing rate keeps the honest zero and names the code; no extrapolation past the last stated step |
| `PER_ORDER_UNIT_COUNTS` | Per-order counts for any other code an estimator states | The break table reads it |
| `ACRYLIC_PRICE_GBP_PER_M2`, `ACRYLIC_SHEET_PRICE_GBP` | Offline fallback snapshot of the UDEF-derived rates | The live Tier-1 derivation wins when the database answers |
| `BOARD_SHEET_PRICE_GBP` | Board sheet prices at thicknesses SDI has actually bought | Interpolated between purchases, never extrapolated beyond them |
| `MATERIAL_PRICE_GBP_PER_KG`, `MATERIAL_DENSITY_KG_M3`, `SHEET_SIZES_MM` | Material physics and stock facts | |
| Operation rate fallbacks (the £/hr table) | Fallback when `tim_rate_card.json` is absent | The card is the source of truth |
| `wb_populate._THROUGHPUT_DEFAULTS` | Corpus-measured throughputs (1,982 historical jobs, line counts recorded per entry) | Stated entries are overwritten from `SHOP_STATED` at build time |
| `WELD_TIME_MODEL`, `ACRYLIC_OP_DRIVERS` | Time models; per-joint and per-bend figures **derived from** `SHOP_STATED`, never hand-copied | |
| `DIRECTIONAL_FINISH_TOKENS` | Which finishes forbid turning a blank on the sheet | Tokens, never part numbers |
| `MATERIAL_PRICE_BREAK`, `CELL_MAP` | The workbook's geometry: where the engine writes, what it never touches | |
| `PRICE_SOURCE_CONFIG` | The connector rungs: `udef_sqlserver → sqlserver → spreadsheet → access → web` | Credentials from `.env`, never in this file |

## The rules that keep the tiers honest

1. **The system is asked first.** A stated figure answers only where Tier 1 cannot, says
   so on the sheet, and both are reported when they disagree.
2. **Every price names its system** in the Supplier column — `price_provenance` owns the
   classification and the naming, so the sheet, report and quote cannot disagree.
3. **Throughputs may be logged in config; prices may not** (undated). James's rule,
   15 Sep 2026: "we can't hard code prices. we can log hourly throughput rates but we
   need to start understanding if these change and why."
4. **Job answers files govern one job.** Anything true of the shop moves to a register.
