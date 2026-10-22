# SOLIDWORKS + Document Manager / PDM Integration — Design Note

**Status:** proposal / design (not yet built)
**Purpose:** integrate native CAD data (SOLIDWORKS models + PDM vault metadata) as a
new, highest-reliability source layer for SDI Intelligence, complementing — not
replacing — the existing PDF/DXF extraction path. Goal: stronger BOMs, stronger
manufacturing routes, and tighter estimated prices.

---

## 1. Why this matters (and why it fits the NO-MOCKING principle)

Today the engine **reverse-engineers** manufacturing data out of derived artefacts:
OCR/text from PDFs, note-parsing for BOM prose, and geometry inferred from DXF paths
(hole counts, cut lengths, bends). That is lossy and error-prone by nature — see the
documented gaps: tube cut-length rollup noise, the "386 holes / path-doubling" query,
unverified DXF extraction quality, material misroutes (PET/PETG, "Led" tubes), £0
acrylic/powder because no area is known.

For **SDI's own designs**, the ground-truth structured data already exists inside the
SOLIDWORKS models. Reading the *source* instead of reconstructing it from a flattened
PDF/DXF is the most genuine source we can cite — which makes this the ideal fit for the
project's core rule:

> **NO MOCKING.** Every output derived genuinely or honestly flagged. A model property
> (material, gauge, cut length, hole count, surface area) is a *primary* source, ranked
> above any inference.

This layer therefore *strengthens* the honest-provenance story rather than diluting it.

---

## 2. The three integration surfaces

There are three distinct APIs under the "SOLIDWORKS + document manager" umbrella. They
have very different cost/capability profiles; we can adopt them independently.

### 2a. SOLIDWORKS Document Manager API  (lightweight — recommended first step)
- Standalone .NET/COM library that reads `.SLDPRT / .SLDASM / .SLDDRW` **headless**:
  no running SOLIDWORKS, **no seat licence** — only a free licence *key* from Dassault.
- Reads *stored* data: custom & configuration-specific properties (material, part no,
  description, finish, weight), the referenced-document tree (→ assembly BOM), weldment
  **cut lists**, sheet-metal info, preview bitmaps.
- **Limit:** reads what is saved in the file; cannot *recompute* geometry or mass.
- **Best for:** a server-side, always-on metadata + BOM + cut-list extractor.

### 2b. Full SOLIDWORKS API  (`ISldWorks`, COM — richest, needs a seat)
- Opens each model and **computes** everything the DocMgr can't:
  - Mass properties: mass, **surface area** (→ powder/area pricing), volume, bounding box.
  - Sheet metal: gauge, **flat-pattern cut length**, **bend count**, bend lines, K-factor.
  - Feature-level **hole data**: exact count + diameters (no DXF path-doubling).
  - Material, weldment cut list, and a clean **flat-pattern DXF export**.
- **Cost:** a dedicated Windows box with a licensed SW seat; run as a queued batch service.
- **Best for:** the parts where geometry *must* be computed (holes, flat pattern, area).

### 2c. SOLIDWORKS PDM API  (`IEdmVault5` — the "document manager")
- If SDI runs PDM, the vault is the authoritative metadata store:
  - **Data-card variables** (material, finish, supplier, cost, revision).
  - **Computed / named BOMs**, where-used.
  - Revision/state → estimate only the **released** revision.
- Gives auditable provenance for free: every value traces to a data-card field.
- **Note:** PDM **Professional** exposes the full API; PDM **Standard** is limited.

---

## 3. Capability matrix — what each surface yields the estimator

| Estimator need                    | DocMgr API | Full SW API | PDM API |
|-----------------------------------|:---------:|:-----------:|:-------:|
| Material / finish                 | ✅ (property) | ✅ | ✅ (data card) |
| Gauge / thickness                 | ✅ (if stored) | ✅ | ✅ (if carded) |
| Flat-pattern cut length           | ~ (if saved) | ✅ compute | — |
| Bend count / bend lines           | ~ | ✅ compute | — |
| Hole count + diameters            | — | ✅ compute | — |
| Surface area (powder / acrylic)   | — | ✅ compute | — |
| Weldment cut list (tube lengths)  | ✅ | ✅ | ~ |
| Assembly BOM + quantities         | ✅ (refs) | ✅ | ✅ (computed) |
| Revision / released state         | — | ~ | ✅ |
| Clean flat-pattern DXF export     | — | ✅ | — |

Legend: ✅ direct · ~ partial/if-stored · — not available.

**Reading:** DocMgr + PDM give cheap, headless metadata/BOM/cut-list; the full API is
needed for the *computed* geometry (holes, flat pattern, area) that fixes the hardest
current gaps.

---

## 4. How SDI's documented gaps get solved

| Documented gap (handoff/roadmap)                        | Native-CAD source that solves it |
|---------------------------------------------------------|----------------------------------|
| Tube cut-lengths noisy (10873mm / 9379mm GA rollup)     | Weldment **cut list** → exact per-member length + profile; also unlocks tube-cut labour |
| "1449-01C 386 holes — check path-doubling"              | **Hole features** → exact count + diameters; makes laser time genuine, not profile-only |
| Acrylic lens £0 / powder coat has no area               | **Mass-properties surface area** → real m² for area pricing |
| PET/PETG misroute; "Led" tubes misread as material      | **Model material / data-card field** → authoritative, no text-parse ambiguity |
| "DXF extraction quality unexamined"                     | **SW-exported flat pattern** → clean, consistent cut length + bounds |
| BOM qty_per_unit / bundling guesswork                   | **Assembly / PDM computed BOM** → genuine quantities, less note-scan reliance |

Manufacturing **routes** fall out of the same data: laser (profile + real holes),
fold (bend count → fold ops + set-ups), weld (weldment members/joints), tube-cut
(cut list), powder (surface area). **Prices** tighten because material cost becomes
exact (L×W×gauge, area×rate, length×£/m) and labour throughput is driven by real
geometry — closing the residual gap to the manual estimators' numbers.

---

## 5. Architecture — a new Layer 0 in the existing waterfall

The engine is already a layered stack. Native CAD slots in **on top**, as the
highest-reliability source, leaving everything below unchanged:

```
Layer 0 (NEW):  SOLIDWORKS model / PDM data     reliability 1.0   (SDI's own designs)
Layer 1:        DXF flat-pattern geometry        reliability 1.0   (customer DXF fallback)
Layer 2:        Section detection (tubes/RHS)
Layer 3:        Catalogue / UDEF pricing
Layer 4:        Deterministic prose recogniser
Layer 5:        LLM note-scan backstop
Layer 6:        Honest flag — "estimator to price"
```

- When a native model is matched → Layer 0 supplies material, gauge, cut length, holes,
  bends, surface area, weldment lengths, BOM structure.
- When only a customer PDF/DXF exists → the current Layer 1+ path runs untouched.
- Bottom layer is still "honest flag, don't guess" — the property that makes the
  finite-combination approach robust.

---

## 6. Integration mechanism (mirrors the existing stack)

Because the SW/PDM APIs are COM/.NET (Windows-only), the clean pattern is a small
**Windows-side extraction service** — a sibling to the FastAPI already running on 8071.

```
┌────────────────────┐     HTTP (localhost)      ┌──────────────────────────────┐
│ ClaudeVision (Py)  │  ───────────────────────► │ SW Extraction Service (C#)   │
│ source_connectors/ │   /extract/part           │  • Document Manager API      │
│  solidworks.py     │   /extract/assembly       │  • Full SW API (seat)        │
│                    │ ◄───────────────────────  │  • PDM API (vault)           │
└────────────────────┘   normalized JSON         └──────────────────────────────┘
```

### Proposed REST contract
- `POST /extract/part`      → `{ path | pdm_id }` → normalized **PartRecord**
- `POST /extract/assembly`  → `{ path | pdm_id }` → **BOM tree** of PartRecords + quantities
- `GET  /pdm/resolve`       → `{ project, drawing_no }` → latest released file id/path
- `GET  /health`            → service + licence-key status

### Normalized PartRecord (maps onto the existing `part_estimates` schema)
```jsonc
{
  "part_number": "1455-C-101",
  "description": "Upper Leg Weldment",
  "source": "solidworks_api",          // solidworks_docmgr | solidworks_api | pdm
  "reliability": 1.0,
  "material": "Mild Steel",            // from model / data card — never inferred
  "gauge_mm": 1.5,
  "flat_pattern": { "cut_length_mm": 1072.0, "bbox_mm": [1072.0, 60.0], "bend_count": 4 },
  "holes": [ { "dia_mm": 8.0, "count": 12 } ],
  "surface_area_m2": 0.42,             // for powder / acrylic pricing
  "cut_list": [ { "profile": "60x30x1.5 RHS", "length_mm": 1072.0, "qty": 2 } ],
  "config": "Milwaukee 500 Wall Bay",
  "revision": "7",                     // PDM released rev, if available
  "provenance": { "field": "data-card:Material", "extracted_at": "..." }
}
```

The Python connector normalizes this into the same record shape `estimator.py` and
`wb_populate.py` already consume — tagged with `source` + `reliability` so the existing
provenance sheet shows "SOLIDWORKS model" / "PDM data card" as the price/route basis.
When no model is found, the connector returns `None` and the pipeline falls back
cleanly to the current path.

### Python side — follows the existing `source_connectors/` pattern
A new module `src/source_connectors/solidworks.py` alongside the existing
`spreadsheet_prices.py`, `sqlserver_prices.py`, `web_prices.py` connectors: a thin
client that calls the service, validates the JSON, and returns normalized records (or a
clean flag on miss). No estimator logic changes required for the first cut.

---

## 7. Prerequisites / open decisions (these govern the approach)

1. **Native files:** do we hold SDI's own `.SLDPRT/.SLDASM/.SLDDRW`, or only
   customer-supplied PDF/DXF? (If only PDF/DXF, the SW API only helps where customers
   also supply models or STEP — STEP can be re-opened in SW to recompute.)
2. **PDM in use?** If so, **Standard or Professional** (drives BOM/variable API scope).
3. **Licence:** free Document Manager key is trivial; a dedicated seat for the full
   API is a real allocation decision.
4. **Host:** presumably the same Windows server as the FastAPI/SQL box.

---

## 8. Suggested phased rollout (low-risk first)

- **Phase 1 — DocMgr metadata + BOM + cut lists (headless, free key).**
  Biggest win for least cost: material/finish/part-no properties, assembly BOM,
  weldment cut lists (fixes tube lengths + tube-cut labour). Validate on job 1282,
  whose weldment (1455-C-101) and tubes are exactly the pain points.
- **Phase 2 — Full API for computed geometry.**
  Add holes, flat-pattern cut length/bends, surface area (fixes 386-hole query, acrylic
  £0, powder area). Needs the seat + queued batch service.
- **Phase 3 — PDM as the resolver + provenance source.**
  Pull the released revision by drawing number; data-card variables become the
  authoritative material/finish; every value carries a vault-field provenance.

Regression anchor throughout: **hold job 1282**. Each phase must not move the 1282
numbers except where it demonstrably corrects a known gap.

---

## 9. Risks / limits (honest)

- Full-API automation is real engineering: a licensed seat, COM robustness, a job queue,
  and careful error handling. Treat it as a service with retries, not a script.
- DocMgr only reads *saved* data — if flat patterns/cut lists weren't saved into the
  file, only the full API can produce them.
- Customer-supplied jobs without native models still rely on the existing PDF/DXF path;
  this layer is additive, not a universal replacement.
- PDM Standard's limited API may not expose everything above; confirm before Phase 3.
