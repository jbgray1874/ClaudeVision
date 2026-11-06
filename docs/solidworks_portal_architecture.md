# SDI Intelligence — SolidWorks + Portal Architecture (build plan)

**Status:** active build plan (supersedes the proposal in `solidworks_integration_design.md`).
**Goal:** the highest-accuracy estimate the drawings can support, driven from as little
human input as possible — ultimately `estimate(drawing_number, client, parity?)` on the
intranet Portal, with everything else resolved.

This doc records the decisions taken while proving the native path on job **12120**.

---

## 1. Three capabilities, three tools (do not conflate)

| Capability | Tool | Notes |
|---|---|---|
| **Deep extraction (accuracy)** — bends, holes, flat-pattern extent, **surface area**, mass, weldment cut list, BOM tree | **Full SolidWorks COM API** | Only the full API *computes* geometry. Needs a seat. This is the accuracy engine (`tools/solidworks/sw_native_analyse.py`). |
| **File lookup** — (client + drawing number) → the files | **Folder resolver + master index** now; **PDM API** later | NOT Document Manager. See §3. |
| **Headless batch at scale** — read *stored* metadata / BOM / cut lists on a server with no seat | **Document Manager API** | Free key, no running SW. **Cannot compute geometry.** Optimisation for later. |

**Document Manager does NOT locate files** — it reads a file you point it at. Its real
value for the Portal is *building the lookup index* cheaply (headless property crawl →
`drawing_number → file_path`), which is what SDI's existing `build_master_index` app on
`\\sdi-dc01\CAD` appears to do.

---

## 2. Extraction stack — accuracy order (feed the estimator in this precedence)

```
.sldasm  -> part numbers + qty + material + config       (BOM: strongest)
.sldprt  -> material, thickness, mass, sheet-metal feats  (routes: strongest)
.slddrw  -> released BOM table + notes (WELD/POWDER/fold)
.dxf     -> flat-pattern cut length / holes / fold lines  (existing path — keep)
.pdf     -> free-text notes / Path C bought-in hardware   (existing dual-path — keep)
.iges    -> geometry only; NEVER a BOM source, last resort
```

**Reconciliation** (`native ∪ DXF ∪ PDF → one job JSON`):
- Qty + material from the **assembly / drawing BOM** beats PDF guesses.
- Geometry metrics (cut length, holes) from **DXF** beat PDF; the full API's computed
  flat-pattern/holes beat DXF where present.
- Ops = model feature signals ∪ drawing notes ∪ estimator rules (punch-vs-laser, powder,
  dress). Bought-in still via notes/catalogue (Path C) — the model often only has a name.

---

## 3. File resolution — (client + drawing number) → files

```
Portal:  estimate(drawing_number, client, parity_workbook?)
             │
             ▼
   resolve_job(drawing_number, client)
     1. PDM API (IEdmVault5) if the vault is live  -> authoritative path + released rev
     2. else master index (DocMgr-built)           -> drawing_number -> file_path
     3. else folder convention on the CAD share:
        \\sdi-dc01\CAD\Design\Customers <era>\<client>\<jobno> - <desc>\<jobno>-Technical
             │
             ▼
   ingest_drawings(job_folder)   (source-agnostic; see §4)
```

The `Customers <era>` roots drift (e.g. "Customers April 08 Onwards") — the resolver must
**search + confirm**, never assume one fixed path.

---

## 4. Ingestion filter — "ignore archived / duplicate drawings"

Deterministic, config-driven, no guessing. Implemented in the native analyser's
`find_sw_files` and to be mirrored for PDF/DXF discovery:

1. **Archive-folder exclusion** — skip any path segment in
   `{archive, old versions, superseded, obsolete, wip, "do not use", backup}` (kills
   `12120-Archive\`), plus `OLD VERSION` / `Test` filenames.
2. **Job-number match** — a drawing belongs to the job only if its part-number prefix
   equals the job number (drops the stray `12128` screen).
3. **Latest-rev-per-part** — parse `_Rev<X>` (or model rev), group by part number, keep
   the highest (RevG over B/D/F). Filenames are a clean `<partno>_<material>_Rev<X>`.

Prefer native `.SLDPRT/.SLDASM` when present; else fall back to PDF/DXF and honestly flag
the weldment/assembly gaps.

---

## 5. Integration into the engine

```
sw_native_analyse -> _sw_native_extract.json
        ▼
src/source_connectors/solidworks.py   (normalises to the estimator's part-record shape,
        │                              tagged source="solidworks_api", reliability 1.0)
        ▼
existing dual-path reconcile (bom_pipeline / merge_boms) — Layer 0, native wins;
no native model -> current PDF/DXF path runs untouched.
```

No parallel silo: the native extract folds into the *same* reconcile that already merges
Path A (deterministic) + Path B (vision), as the highest-reliability layer.

---

## 6. What 12120 proved

- The native models exist in `…\12120-Technical\` (parts 01M–08M, assemblies 101/102/103/
  SA01/GA, drawings GA + Both-Screens, hardware Keyhole-PEM / Thumbscrew / Grip-Knob / SKC).
- **`12120-01-103` is a `.SLDASM` (weldment)** — the weld our PDF/DXF path missed (103 read
  at 22% confidence, no flat DXF). Native source states it directly. Same for 101 (STAND
  WELD ASSY) and SA01.
- `12120-01-GA.SLDASM` yields a **17-line BOM tree**; 103 → 6 children; 101 → 8.
- **Binding lesson:** this pywin32 late-binding exposes no-arg getters (GetTitle,
  GetPathName, FirstFeature, GetModelDoc2, CreateMassProperty, …) as *properties*, not
  methods — route them through `_get0()`. Arg-taking calls resolve as methods normally.

---

## 7. Phased rollout

- **Phase 1 (now):** full-COM native extractor (`sw_native_analyse.py`) + reconcile into
  the engine via `source_connectors/solidworks.py`. Prove on 12120 vs Tim's sheet.
- **Phase 2:** resolver + ingestion filter (`job_ingest.py`) so a run needs only a folder
  (then drawing-number + client). Latest-rev / archive / job-match rules from §4.
- **Phase 3:** DocMgr master-index (headless, no seat) for lookup at scale; wire the
  Portal entry point `estimate(drawing_number, client, parity?)`.
- **Phase 4:** PDM API as the authoritative resolver + provenance (released rev, where-used)
  once the vault is live.

Regression anchor throughout: **12120 and 1282** — each phase must not move their numbers
except where it demonstrably corrects a known gap (e.g. the 103 weld).
