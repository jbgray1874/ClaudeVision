# Where SDI's build-and-price knowledge lives

One page, so the answer to "where did that figure come from" is never archaeology.
Three tiers, in the order the engine asks them. Every figure on an estimate traces to
exactly one of these, and the Supplier column on the sheet now names which
(SDI Live UDEF · Estimating spreadsheet · Estimator stated · Web listing · AI ESTIMATE).

*This file is the index the SDI Estimating Intelligence architecture page should carry.
If a register is added anywhere, it is added here in the same commit — the test
`test_the_knowledge_map_is_not_stale.py` holds the two in step.*

---

## Tier 1 — SDI Live (the systems of record)

| Source | What it holds | Access |
|---|---|---|
| `SDILive.dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING` | Part codes, descriptions, supplier names, system cost — what purchasing pays against | read-only (the ERP's own table) |
| `SDILive.dbo.bought_in_parts` | 44 rows, **0 active** — the engine's UDEF query still unions it; effectively retired | read-only |
| `SDILive.AIEstimating.BoughtInCatalogue` | Our catalogue: 84 live rows (migrated dbo.bip, workbook harvest, web-indicative, seeds) with `source` tags and effective dates | ours, written by `catalogue_loader.py` |
| `SDILive.AIEstimating.JobBoughtInMaterials` | Raw per-job provenance from harvested workbooks — one row per bought-in line per drawing | ours, written by `batch_ingest_historical.py` |
| `SDILive.AIEstimating.Supplier` / `CommercialRate` | Supplier identities; commercial per-order rates | ours |

Derived-at-run-time from Tier 1 (never stored): the plastic sheet £/m² —
`_resolve_board_sheet_rate_gbp_per_m2` computes the median across UDEF's plain-stock
lines on every run, which is why the acrylic sheet priced £48.89 on 8 Sep and £47.21 on
15 Sep: the catalogue moved and the rate moved with it.

## Tier 2 — the estimators' own documents

| Source | What it holds | State |
|---|---|---|
| Historical estimating workbooks (the estimates share) | Priced BOM lines, sheet prices, labour lines from jobs quoted and won | Harvested into `AIEstimating.*` by `batch_ingest_historical.py`. **Only 32 rows / 2 workbooks landed so far — the re-ingest over the share is the open action.** |
| The live `spreadsheet` price connector | — | Points at the **blank** template, so it contributes nothing on any job. The corpus road above is the real one. |
| `src/tim_rate_card.json` | Department hourly £ rates, from Tim's own sheet | The card wins; the config table is only the fallback when it is absent |
| Per-job answers files (`docs/7332-01_confirmed.example.json` pattern) | Job-scoped confirmed facts an estimator has ruled on | Governs that job only — a rate correction is never left here (see Laser (Acrylic), which moved to the register because "a rate correction is how the department runs, not a decision about one stand") |

## Tier 3 — `src/config.py` (one file; the named registers inside it)

**Money may not live here undated.** A price in source control cannot go stale visibly —
so config holds *facts, rates the shop stated, and fallbacks that name themselves*, and
the tests police the boundary.

| Register | What it holds | Rule |
|---|---|---|
| `SHOP_STATED` | **The central register.** Every figure the shop has stated: weld 30 / dress 20 min per weldment, brush-before-plate 40 min, plater pack + £120 freight, linebend 0.5 min/bend, acrylic laser 95 parts/hr — each with who, when, which job | Other tables read from it; changing a stated figure anywhere else changes nothing |
| `ESTIMATOR_STATED_PRICES` | Prices an estimator gave us (dated, attributed) | Always **second to the system** — used only where no priced source answers, rendered "Estimator stated", disagreement reported when both answer |
| `ROLL_GOODS_CATALOGUE` | Packaging facts only (roll lengths). **No money** — the price comes from Tier 1 or the stated register | |
| `PER_ORDER_UNIT_COUNTS` | Howard's 1/1/3/9 boxes-per-order rule, recorded | Not priced — boxing/delivery are not priced by policy |
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
