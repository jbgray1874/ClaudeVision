# SDI Intelligence — pipeline writer inventory (read-only audit, Priority 1)

Date: 2026-09-08 · Audited at commit `416acbb` · Production code unchanged by this audit.

Every pass that WRITES one of the five fact classes on a job in flight — **ID**entities,
**QTY** quantities, **GEO**metry, **ROUTE**s/operations, **PRICE**s — in execution order,
with whether it ADDS records, REMOVES records, or MUTATES fields. The reference boundary
for "before/after the final graph" is `refresh_canonical_route_after_reconciliation`
(`file_scan.py:3303` → `route_compiler.py:1960`).

**Which estimator is live:** `file_scan.py:26` imports from `estimator.py`.
`estimator1.py` / `estimator_old.py` are dead snapshots (excluded by name in
`_area_gates.py:17`, `_stockform_trace.py:17`, `tests/test_one_writer_per_arbitrated_fact.py:69`).

---

## Stage 0 — Page scan and BOM assembly (`file_scan._finalize_scan_summary`, from :1822)

| Site | Class | Action | Trigger |
|---|---|---|---|
| `file_scan.py:1918` | ID, QTY | **REPLACES** `document_analysis["bom_rows"]` with the reconciled dual-path rows | dual-path enabled, rows present |
| `file_scan.py:1929-2043` | — | **DEAD CODE** — `if False and …` inline reconcile, superseded | never |
| `file_scan.py:355-377` | ID, QTY | merges multi-PDF BOM rows, drops the loser | multi-PDF job |
| `file_scan.py:430-495` | ID, QTY | **REMOVES** truncated-code BOM rows; `:487` direct-writes keeper quantity | stem/fuller pair |
| `file_scan.py:1531-1575` | material | document material inherited via `_apply_field(…, "bom_tree")` | doc-level material |
| `document_builder.py:2206` | ID, QTY | **REPLACES** bom_rows with fallback-parser rows | pooled BOM empty |
| `document_builder.py:2230` | ID, QTY | **ADDS** fixing/vinyl BOM rows | secondary BOM tables |
| `document_builder.py:2275-2277` | ID, QTY | **ADDS** parts from assembly bought-in extraction | BOM text names bought-ins |
| `document_builder.py:2312` | ID, QTY | **ADDS** parts for non-SDI BOM rows | valid non-SDI identifier |
| `document_builder.py:2364` | ID, QTY | **ADDS** parts for SDI rows with no geometry record (flagged incomplete) | SDI code + material suffix |
| `document_builder.py:2373-2395` | ID | **REMOVES** false part numbers, detail-callout phantoms, PN fragments | filters |

## Stage 1 — DXF augment (`drawing_job_merge.augment_summary_with_dxf:2219`)

| Site | Class | Action |
|---|---|---|
| `drawing_job_merge.py:2310` | ID, GEO | **ADDS** orphan DXF part (job-coded flat with no record) |
| `drawing_job_merge.py:1247` | ID, GEO | **ADDS** orphan child per distinct flat cluster |
| `drawing_job_merge.py:434-812` | GEO | writes `geometry_rollup` (:460), `normalized_geometry` (:481), `dxf_raw_geometry` (:672), blanks, thickness, bends |
| `drawing_job_merge.py:1797` | GEO | mirror inherits base flat (gap-fill, rank `mirror_of_measured`) |
| `drawing_job_merge.py:1657` | GEO | handed-pair stock-key settle |
| `drawing_job_merge.py:1305` | ROUTE | `assembly_children` from "A WITH B" descriptions |

## Stage 2 — Pre-estimate normalisation (`file_scan.py:2185-2380`)

Removers: junk descriptions (:2190), the draughtsman-as-part (:2188), None-PN duplicates by
description core (:2231) and by (page, cut-length) (:2244). Mutators: part-number
normalisation/nulling (:2205), assembly-weight and year-band dimension clears (:2216),
thickness from DXF filename (:2282, "inference"), material inference (:2286),
`process_notes` boilerplate strip (:2311), weight minted from page text (:2325),
`textual_operations` = `infer_operations` with the finish-aware filter (:2362).

## Stage 3 — SolidWorks native (`source_connectors/solidworks.py:1576`)

Mutates: thickness (:1868 via `_apply_field`), section stock (:1882), assembly flags
(:1938), **quantity from the native BOM (:1776)**, `is_bought_in` for imported supplier
bodies (:1822), material incl. override branch (:1840), native flat geometry incl.
`geometry_rollup.estimated_cut_length_mm` (:1951-1983). `_reject_dxf_geometry`
(:1191-1272) can **overwrite** a DXF blank with the native flat.

## Stage 4 — LLM full extract (`file_scan.py:2712-2790`)

`llm_full_extract.merge_inference:761` **ADDS whole part rows** the transcription never
listed (stamped `inference`), plus inferred route rows (:790). `llm_full_job` mutates
assembly flags (:233), material family/bought-in (:247), **quantity roll-up (:282 —
direct write)**, material/finish/weight/thickness gap-fills (:316-381), `section_stock`
(:398), and applies routes to parts (:416).

## Stage 5 — Job quantity, final phantom sweep, BOM tree (`file_scan.py:2880-3010`)

Job quantity direct-write (:2887). **Final phantom sweep (:2900-2958)** — the
authoritative drop point for None-PN artefacts. BOM-tree merge (:2966) and effective
per-bay quantities via `_apply_field(…, "bom_tree")` (:2985).

## Stage 6 — Late connectors and identity gates, pre-cost (`file_scan.py:3040-3258`)

| Site | Class | Action |
|---|---|---|
| `file_scan.py:3046` | GEO/QTY/ROUTE | native re-applied to parts created after the first SW pass |
| `file_scan.py:3076` → `solidworks.py:1548` | **ID ADD** | mints the model-named assembly parent (≥1 child must name a job part) |
| `file_scan.py:3147`, `:3224` | **ID REMOVE** | `merge_truncated_part_codes`, called twice |
| `file_scan.py:3159`, `:3170` | GEO | mirror + pair settle, second calls (the live site) |
| `file_scan.py:3190` → `route_compiler.py:1659` | ID/ROUTE/PRICE | `apply_canonical_evidence_to_parts`: quarantine (:1690), kind stamps (:1700), assembly leaf-op strip (:1722), **bought-in duplicate fold (:1740-1799)** with price-provenance carry |
| `file_scan.py:3248` | ROUTE REMOVE | `strip_leaf_operations` again |

## Stage 7 — `estimate_document` (`estimator.py:6493`) — still pre-refresh

**Adds parts:** BOM-row bought-in scan (:6498, incl. vinyl-callout recogniser with the
graphic-owner guard), **prose recogniser** (:6612 → `bought_in_recogniser.py:601`; mints
`BI-` codes at :723, prices from history at :794; the captured-row guard lives here), LLM
note-scan backstop (:6638), **PACKAGING/DELIVERY injection (:6714)**, subcontract plating
line (:6787 — also mutates `llm_full_extract["assemblies"]`).

**Removes:** `_reconcile_bought_in` (:6249) cross-layer duplicate merge;
`_is_estimable_part`/`_is_weldment_parent_part` filters (:6844/:6817); metal-hole/laser/saw
op strips (:4129-4179).

**Prices:** per-part `estimate_part` writes (quantity :4752 direct; price blocks
:4775-4879; ops :5075-5133, :4192-4384), `apply_last_resort_prices` (:6944),
`apply_subcontract_plating` (:6953), document totals (:5485, :7118).

## Stage 8 — Dual-path reconcile into part_estimates (`file_scan.py:104`, runs pre-refresh)

Quantity corrections via `_apply_field(…, "bom_tree")` (:175, :195) and an **ID ADD**:
a fastener-class dual-path row with no code mints a `part_estimates` record (:209-221,
`_is_fastener_row:128` = CLINCH/NUT/…/GLIDE).

## Stage 9 — THE BOUNDARY: `refresh_canonical_route_after_reconciliation` (`route_compiler.py:1960`)

Recompiles from the final population (:1992); quarantines interleave artefacts (:2012)
and folds wrapped-row BI fragments (:2017) on **both** lists with evidence to the summary;
**recompiles a second time from the cleaned population when anything was removed**
(:2020-2035) so the published graph carries no node for a removed record; projects the
shadow (:2036).

## Stage 10 — ★ EVERYTHING THAT WRITES AFTER THE BOUNDARY ★

### 10a. Bay rollup (`file_scan.py:3312-3372`)
- **ADDS BOM rows**: `bay_rollup.synthesize_folder_job_bom_rows:721` (codes off
  `part_estimates`), catalogue rows (:762 → :449), `inject_missing_bay_rows`
  (`part_identity.py:325`, kick-plate regex rows).
- **REMOVES rows**: weldment-parent dedupe (:703), shadowed-row dedupe (:628).
- **PRICES**: commodity pricing pass (`file_scan.py:3332` price book + system cost),
  `build_bay_estimate:815` bay lines, `_packaging_and_delivery_estimate:783`.

### 10b. `main.py` post-scan
Order-qty direct writes (:823); drawing-facts connector (:838, env-gated); assembly/pack
labour (:867) with Tim's per-drawing override (:882) and bought-in materials file (:905);
**the totals fold (:925-1013)** rewriting `workbook_equivalent_pricing`, `cost_breakdown`,
every `document_total_*` and re-saving the JSON (:1008).

### 10c. Workbook population (`wb_populate.populate_workbook:2839`)
- `canonicalise_part_estimates_for_workbook:1620` — **the last gate**: re-runs quarantine
  + fold (:1635-1641), fails closed to `identity_gate_failures` (:1650) → BLOCKING
  invariant; synthesised-code absorption (:1714); identity/qty rewrite to canonical
  (:1740); **the three-branch missing-bought-in mint (:1769-1871)** — commodity price /
  market-AI price / withheld — **gated by the removal ledgers (:1762-1768)**; publishes
  `estimate_summary["canonical_part_estimates"]` (:2888) *without* overwriting
  `part_estimates` — two populations from here on.
- `canonical_labour_groups:2024` builds labour rows from decisions; colour-group merge
  (:2242 REMOVES), `_map_operation:941` remaps, `_is_spurious_operation:1012` REMOVES,
  **MANM insert-labour injection (:4558, non-cutover only) ADDS a group**.
- `price_provenance.mark_withheld` mutates part-estimate records (:3555).

### 10d. Read-back and record (`wep_readback_from_xlsx.py:689`)
Explains unpriced rows in place (:735), stamps `final_estimate.v2` (:740), overwrites
`workbook_equivalent_pricing`/`cost_breakdown` with Excel-calculated figures (:770-800),
re-writes the JSON (:803). `costed_facts.costed_job` itself is **pure**; `main.py:1222`
persists it (and re-stamps after invariants, :1491).

### 10e. Quantity sweep, invariants, deliverables
`quantity_sweep.sweep:87` writes variant *files* (freight re-price :281, banner :312),
never `part_estimates`; `recache_workbooks` (`main.py:1393`). `invariants.py` writes only
`summary["invariants"]` (:3427). The four deliverable writers are **pure readers**
(no `summary[...] =` at all); `add_provenance_sheet` writes workbook files only.

---

## Consolidated removers

`_merge_truncated_bom_codes` (file_scan:430) · junk/author/None-PN filters
(file_scan:2188-2271) · final phantom sweep (file_scan:2900) · document_builder phantom +
fragment filters (:2373-2395) · `merge_truncated_part_codes` (drawing_job_merge:2104,
called twice) · **`quarantine_interleave_artefacts`** (route_compiler:1818; runs pre-cost,
at refresh, and at the last gate) · **`fold_bom_row_fragments`** (route_compiler:1875;
refresh + last gate) · bought-in duplicate fold (route_compiler:1740) ·
`strip_leaf_operations` (bought_in_policy:352, two call sites) · `_reconcile_bought_in`
(estimator:6249) · estimability filters (estimator:6817/6844) · op strips
(estimator:4129) · bay dedupes (bay_rollup:628/703, **post-boundary**) · colour-group
merge (wb_populate:2242, post-boundary) · `_is_spurious_operation` (wb_populate:1012,
post-boundary).

## Geometry key spellings (contract debt)

Five spellings in live use: `geometry_rollup` (~15 reader sites across 8 modules),
`normalized_geometry` (~25 sites), `dxf_raw_geometry` (4 sites), `manufacturing_features`
(estimator-only, 14 sites), bare `geometry` (file_scan fallback only). Multi-holder
readers that already reconcile: `estimator.py:2439/2450/2579`,
`wb_populate.costed_geometry_value:1208`, `invariants._blank_num:518`,
`costed_facts._BLANK_HOLDERS:848` (the only one that *reports* a conflict).

## Identity-merge / alias passes (contract debt)

Seventeen distinct mechanisms across six modules: four passes inside
`route_compiler._raw_identity_aliases:690` (BI-token-subset, prefix-related, caret
fragment, hostless consumable), `_drawing_code_aliases:514`, `_code_spellings:902`,
`_record_by_squashed_key:200`, the record-level fold (:1740), stem merge
(drawing_job_merge:2104 + part_identity guards), `part_identity` normalisers,
`estimator._reconcile_bought_in:6249` (a fourth token-set implementation),
`wb_populate` synthesised-code absorption (:1714) + `merge_canonical_estimate_records`
(:1546), `bay_rollup._same_thing:138` family, `file_scan._merge_truncated_bom_codes:430`,
`solidworks._native_match_index:1273` (four sub-indices).

## Deliverables vs the record

On the record (`costed_facts.costed_job`): job_report (:2515), client_quote (:934),
estimate_explained (:1315), covering-email gate (main:1689), estimation_report (:314).
**Still reading `part_estimates` directly**: job_report_html:144 & :1952,
client_quote_html:926 (fallback), estimation_report:277, main:1040 (console),
estimator:7172/:7229. Note `costed_facts.job_parts` resolves to
`canonical_part_estimates` when the workbook ran and falls back to `part_estimates`
otherwise — so direct readers diverge exactly on the jobs where the workbook succeeded.
