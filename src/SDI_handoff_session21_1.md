# SDI Intelligence (ClaudeVision) — Session Handoff

**For:** the next chat (open a fresh conversation in the SDI project and reference/paste this).
**Written:** 06 Jul 2026, after the 1282 parity-vs-Tim analysis, the routing/hierarchy probes, AND the credibility-gate fix (now deployed + verified).
**Working style:** peer co-engineering (JG = James Gray, lead dev; Claude = co-engineer). Probe-first, one change at a time, verify against job 1282 before stacking. No mocking.

> **LATEST CLOSEOUT (this session's final work): credibility-gate bug FIXED + VERIFIED.**
> `_part_cost_credibility` in `estimator.py` now exempts bought-in parts (via `page_roles == bought_in`) from the `no_part_dxf` penalty. Verified on a fresh 1282 run: status `insufficient_data → ok`, `suppress_headline_total True → False`, `credible_cost_ratio 0.4257 → 0.8315`, `Estimated document total: 194.79` now prints (headline no longer suppressed). The 4 genuine fabricated DXF-gaps (1448-01, 1455-C-101, 2621-01C, 3886-01) stay honestly flagged; bought-ins correctly dropped out of `unreliable_parts`. Byte-identical on ALL parts except `BI-MAINSCABLE` (£1.49→£1.59) — the pre-existing mains-cable non-determinism, NOT the patch (reconciles exactly to the 10p document-total change). Fingerprint: `Select-String estimator.py -Pattern "Bought-in parts structurally"`.
>
> **Tell-Tony framing:** this makes the *reporting* honest, not the estimate more accurate. 1282 now quotes because its credible cost genuinely clears 50% once bought-ins stop being penalised for lacking DXFs they can never have. The £27.91 of real fabricated DXF-gaps stays flagged per-part.

---

## 0. The one-paragraph situation

The engine now produces clean output on job 1282 — main WB Sell Price ~£195.60–195.82, both supplementary sheets (Decision Report + AI Provenance) fixed and consistent. We ran the **first real parity comparison against Tim's manual 1282 estimate** and characterised the gap precisely. We then investigated the labour/routing model and, via read-only probes, established what is genuinely drawing-derivable vs what would be hardcoding Tim's answers. The next concrete piece of work is **assembly-level P.Coat grouping** (the hierarchy substantially already exists), plus a **credibility-gate probe** that was mid-flight when the chat got too long. Nothing is at risk — it's all on JG's machine and in outputs.

---

## 1. Core architecture (unchanged, locked)

- Engine reads PDF + DXF engineering drawings → parts/materials/geometry → prices → **POPULATES the estimators' real Blank Estimating Workbook (WB) template**. The WB's own formulas do the maths. Engine supplies INPUTS; WB owns the arithmetic. This is the strongest architectural decision — do not reimplement WB formulas in Python.
- **NO MOCKING:** every number must be genuinely derived from the drawing or the DB, or honestly flagged. Nothing copied from Tim's manual sheet that the engine couldn't re-derive on the next drawing.
- **Regression anchor: job 1282** (Milwaukee 500mm Wall Bay). Every change is checked against it before moving on.
- **WB as single source of truth for maths; label-anchoring over hardcoded cell addresses** (scan for the "Sell Price" label, write a live cross-sheet formula).

---

## 2. Environment / deploy loop (CRITICAL — the next chat needs this to function)

- Claude **cannot** edit JG's machine. Claude produces drop-in files to `/mnt/user-data/outputs/`. JG downloads → copies into `C:\ClaudeVision\src\` → verifies fingerprint via `Select-String` → runs.
- **Deploy pattern:**
  ```
  Copy-Item "<downloads path>\<file>.py" "C:\ClaudeVision\src\<file>.py" -Force
  Select-String -Path C:\ClaudeVision\src\<file>.py -Pattern "<fingerprint>"   # must print before running
  ```
- **Run probes/main from `C:\ClaudeVision\src`** (running from the Downloads path fails "No such file"). Copy in first, then run.
- **MUST use venv python:** `C:\ClaudeVision\.venv\Scripts\python.exe` (system Python310 lacks pdfplumber and defaults to cp1252 → emoji prints CRASH). **Dump probe output to a UTF-8 file** (`io.open(path, "w", encoding="utf-8")`) and paste from there — this pattern is used repeatedly.
- **Multi-line here-strings / multi-line `python -c` FAIL** in JG's PowerShell. Use downloaded scripts with NEW filenames.
- **main.py run command (folder-as-job, 1282):**
  ```
  C:\ClaudeVision\.venv\Scripts\python.exe -u main.py --search-root "\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job
  ```
- **Template UNC:** `\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx` (double-space). Worksheet inside = "Estimate". Sell Price value cell = **M143**.
- **Output:** `C:\ClaudeVision\output\estimates\1282 - Milwaukee Wall Bay_<timestamp>.xlsx`; JSON at `C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json`.
- **DB:** SQL Server SDILive @ 10.0.0.200, pyodbc, ODBC Driver 18, UID AIBot / password from SDI_DB_PASSWORD in src/.env (never in source). Engine reads `dbo.*` (NOT `AIEstimating.*`).
- **LLM:** xAI / Grok, config `xai_model = "grok-4.3"`. Determinism overrides (temperature/seed/reasoning_effort) applied.
- **`/mnt/project/` snapshot is STALE** — trust RUN OUTPUT and DUMP real src files before editing. Files confirmed real this session via probes: `job_decision_report.py`, `estimation_report.py`, `bom_tree.py`, `drawing_job_merge.py`. Still not fully seen: the estimator's P.Coat/labour costing section, the credibility-gate function.
- **JG cannot reach the K: drive from Claude** — Tim's manual estimates live on K: and must be pasted by JG.

---

## 3. DONE & VERIFIED this session

### Both supplementary sheets fixed (deployed, confirmed in real runs)
- **`job_decision_report.py`** — Decision Report sheet. Two fixes:
  1. `_is_bought_in(part)` guard so bought-ins (BI-/FIXING/VINYL/PACKAGING/DELIVERY, `bought_in` page_role, recogniser source, BOUGHT_IN material) render as "Bought-in / catalogue component — no fabrication material" instead of the pn-suffix heuristic misfiring (was labelling BI-LEDLINKLIGHT "-T → MDF/Timber", BI-50CMLOOM "-M → Mild Steel").
  2. `_find_wb_sell_price_ref(wb)` scans the "Estimate" sheet for the "Sell Price" LABEL and writes a live cross-sheet formula `='Estimate'!M143` — survives layout shifts, no hardcoded addresses. Fingerprint `_find_wb_sell_price_ref` at lines 91 & 320.
- **`estimation_report.py`** — AI Provenance sheet (`add_provenance_sheet`). IMPORTS `_is_bought_in` + `_find_wb_sell_price_ref` from `job_decision_report` (single source of truth, with local fallback defs). Same fixes + suppresses spurious review flags on bought-ins. Fingerprint at lines 39/56/341. **Verified:** Provenance shows "SELL PRICE (from Estimate sheet)" with the live formula, all bought-ins labelled cleanly.
- **Note on £195.60 vs £195.82 across tabs:** NOT a bug — different runs (mains-cable price drift). Within ONE file both tabs reference the same cell (`='Estimate'!M143`) so they agree.

### Electrical recogniser (from earlier sessions, still confirmed)
- `bought_in_recogniser.py` + `prose_recogniser_layer2` (fully deterministic, no LLM) catch all 9 electricals: loom, LED link, downlights, junction box, mains cable, earth strap, adhesive cable, dome rivet, foam tape. **Loom £24.15 = Tim's £24.15 exactly.** Determinism proven; LLM not load-bearing for electricals.

---

## 4. PARITY COMPARISON vs TIM'S MANUAL 1282 (the session's key analytical output)

Tim's manual estimate (pasted by JG; path `K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls`).

|              | Engine   | Tim      |
|--------------|----------|----------|
| Quantity     | 180      | 100      |
| **Unit Cost**| £195.82  | £168.68  |
| Material     | £117.33  | £90.60   |
| Labour       | £64.57   | £55.92   |
| Total hours  | 137.42   | 69.28    |

**Both are PER-UNIT costs.** The quantity difference (180 vs 100) does NOT excuse the gap — at higher qty the engine's amortisation should make its unit cost *lower*, not higher. So the ~£27/unit (16%) gap is genuine and the engine **over-estimates**. (To compare cleanly next time, re-run the engine at **qty 100** to remove amortisation noise.)

### Root cause: the LABOUR / ROUTING model
Engine labour hours are ~2× Tim's (137 vs 69). Concentrated in:
- **P/C (powder coat): engine 10.5h vs Tim 2.8h** — engine coats each part individually; Tim coats grouped assemblies ("HEADER COMPLETE", "FOOT ASSEMBLY").
- **PACM (assembly): engine 34.95h vs Tim 9.89h** — engine has generic per-part handling; Tim has real job steps (PREP/FIT ELECTRICS, MAKE BOXES, MAKE INFILLS 1–4, KIT/PALLETIZE, SHRINK WRAP).
- **FOLD 44h vs 26h**; **PUNC engine 5.3h vs Tim 12.4h** (engine UNDER on punch).

**STRUCTURAL ROOT (the key insight):** the engine routes **parts in isolation** (each part cut+fold+coat+handle); Tim routes the **job as a process** (fabricate → weld into assemblies → coat ASSEMBLIES → kit/pack). The engine does not model the ASSEMBLY HIERARCHY for labour/coat. This single difference explains the P/C over-count, the missing spot-welds, and the generic-vs-specific assembly labour.

### Concrete errors (independent of quantity)
- **Spigot 1448-02 gauge:** engine 1.2mm vs Tim 3.0mm. DXF filename literally says "1448-02_3mm MS". Engine read the wrong gauge.
- **Lens 1455-C-005:** engine ACRYLIC vs drawing "MATERIAL: HIPS" (page 16). Part shows `Materials: None` → defaults acrylic. Tim treats it as SUBPLAS72 bought-in plastic (£1.07), not fabricated. The DXF filename ("1455-C-005_1mm HIPS_revC.DXF") and `drawing_job_merge.py`'s `_DXF_MATERIAL_TOKENS` DO have a HIPS token that should win — worth checking why it isn't applying here.
- **Packaging/delivery:** engine leaves £0-flagged ("estimator to price"); Tim prices BOX82 £10.48 / pallet £2.50 / delivery £2.86.
- **Fixings Tim has that engine misses:** FIXING49/51 threaded inserts, FIXING1101 adhesive clip (~£16 of items total across packaging/delivery/fixings).

### The win
- Loom price near-exact (engine £24.15 = Tim £24.15). Electricals itemised where Tim bundles them into "PREP/FIT ELECTRICS" labour — this is *why* the engine runs higher on electricals, not an error per se.

---

## 5. ROUTING VERDICT — what is drawing-derivable (probe-proven)

Ran `_routing_signal_probe.py` and `_ga_hierarchy_probe.py` (both read-only, read the engine's OWN extracted JSON — no Tim data). Conclusions:

| Routing issue | Verdict | Reason |
|---|---|---|
| **Punch-vs-laser** | **PARTIAL — build only "dense hole field → punch"** | Hole geometry does NOT cleanly separate Tim's punch parts from his laser parts (1448-02 has 0 holes but Tim punches; 1455-C-001 has 4 holes but Tim lasers). A hole-count threshold would OVERFIT Tim. The 386-hole panel (1449) already routes to punch correctly — keep that, don't invent a threshold. |
| **Assembly-level P.Coat** | **BUILD IT — hierarchy substantially exists** | See §6. Drawing-derivable from the GA/assembly pages (BOM tables on pages 10, 11, 20). This is the highest-value change. |
| **Roll** | **DO NOT BUILD — flag instead** | ZERO roll indicators on ANY part in the extracted data. 1455-C-002 (which Tim rolls) shows FOLD callouts, no roll. Not drawing-derivable → flag "estimator to confirm", never hardcode Tim's choice. |
| **Spotweld** | **DO NOT BUILD — flag instead** | Only generic "WELD" tokens, no SPOT. Drawing doesn't distinguish weld type → flag, don't guess spot-vs-CO2. |

**Both roll and spotweld would have been mocking traps — JG's instinct to distrust drawing-un-recreatable fixes caught them.**

---

## 6. NEXT PIECE OF WORK: assembly-level P.Coat grouping

### Why it's smaller/safer than it first looked (probe-proven)
The assembly hierarchy machinery **already substantially exists**:
- **`bom_tree.py`** — `resolve_effective_quantities(bom_rows, main_ga=None)` builds the assembly tree, groups rows by `source_pdf`, identifies the main GA, computes per-family multipliers (parent/child). Returns `{"effective", "multipliers", "main_ga", "flags"}`. Keyed by numeric family (`_family()` → e.g. `1455`). Also `apply_effective_quantities()` and `merge_table_bom_rows()`.
- **`drawing_job_merge.py` `_stamp_assembly_parents(parts)`** — stamps `is_assembly_parent=True` on any part whose PN is a strict prefix of ≥2 others (general, additive, drawing-derived — no per-job logic). Runs before re-estimate.
- **`estimator.py` lines 1346–1389** — already consumes `is_assembly_parent` / weldment tokens: suppresses parent material, carries material via children, costs the parent **labour-only**. Comment says "convention matches Tim." Uses config `WELDMENT_PARENT_DESC_TOKENS` + `WELDMENT_PARENT_PN_SUFFIXES` (`-WA\d*$`, `-SA\d*$`).
- Top-level JSON has `assembly_summary` (len 4) including `assembly_relations`. `file_scan.py` `_infer_page_role` sets `primary_role="assembly"` (lines 333–450); `assembly_summary` built at line 1018–1021.

So the hierarchy exists for **material** (parent suppressed, children carry it) and for **quantities** (tree multipliers). **What does NOT exist:** P.Coat is attached per-part in the estimator, and nothing consults the assembly tree to GROUP coating. **The change = connect the existing tree to the P.Coat step.** It is NOT "build hierarchy from scratch."

### The critical design subtlety (the code revealed this — don't miss it)
The tree is keyed by **numeric family** (`1455`, `3886`), but **Tim coats by physical weld-group, not by family:**
- Tim's "HEADER COMPLETE" P.Coat = 1455-C-101 weldment (children 001/002/003/004) coated as ONE unit → maps to family `1455` ✓
- Tim's "FOOT ASSEMBLY" P.Coat = welded footbases 3886-02/03 coated together — **BUT 3886-01 (the leg) is a SEPARATE powder-coated tube.** So family `3886` is NOT one coat unit.

**Therefore "coat by numeric family" is WRONG — it would lump 3886-01 with the footbase assembly.** The correct grouping is "parts that **weld into one assembly** get coated together" (narrower than family). Derivable from the weld relationship + assembly parent, but NOT simply the family key.

### Immediate next step (probe first, as always)
Two things still unseen — must read before designing the edit:
1. **The estimator's P.Coat attachment/costing code** — where `powder_coating` is added to a part and where its hours are computed (the actual edit site). Grep showed 1346–1389 and 2184–2191 but not this.
2. **What `assembly_summary.assembly_relations` (len-4 dict) contains** — does it already hold the weld/coat groupings, or does that need deriving?

Write a read-only probe to dump those, THEN design the assembly-coat grouping (by weld-group, not family), build on 1282, verify against Tim's "HEADER COMPLETE" / "FOOT ASSEMBLY" grouped P.Coat lines.

### Guardrails (non-negotiable)
- **Hold 1282's DXF-derived numbers BYTE-IDENTICAL** before/after the change (cut lengths, weights, hole counts, blank areas, materials). Only P.Coat grouping/hours should move. If any DXF-sourced figure shifts, the change reached somewhere it shouldn't — back it out. This is already the codebase house-style ("keeps every existing single-parent job (1282 etc.) byte-identical").
- Build on 1282 (Tim's benchmark available). Use NEW drawings only to test GENERALISATION afterwards — do NOT build on a drawing with no Tim benchmark.

---

## 7. OPEN PROBE — credibility gate (was mid-flight when chat ended)

`_credibility_gate_probe.py` was **just created and handed to JG to run** — result not yet seen. It answers a bug-vs-policy question:

- The gate currently suppresses the headline: **"INSUFFICIENT DATA — credible 43% · DXF on 71% of 14 fabricated parts · DO NOT QUOTE."** It gates on **DXF presence**.
- **Suspicion to confirm:** are bought-in electricals/fixings/packaging (which CORRECTLY never have a DXF) sitting in the DXF-coverage **denominator**? If so they structurally drag the ratio below 50% and no legitimate fix can cross it → that's a **DENOMINATOR BUG**, not a policy knob (fix = exclude bought-ins from the ratio, no parameter needed).
- If the "14 fabricated" already excludes bought-ins, the denominator is clean → it's a genuine **POLICY** question (then parametrise the threshold *deliberately* — as config, not as a mode switch).
- The probe greps the gate code, reconstructs 1282's ratio from JSON to see which parts are counted, and dumps the gate function(s) to `credibility_gate_dump.txt`.

**Next chat: get JG to run `_credibility_gate_probe.py`, paste console + `credibility_gate_dump.txt`, and decide bug-vs-policy from the evidence.**

### On the "parametrise so main knows the route" question (JG asked)
Honest conclusion reached: **don't parametrise as a route/mode switch.**
- Assembly-P.Coat should NOT be conditional — it reads PDF GA pages (present on ~every job), runs always, does nothing when there's no assembly. Not a "PDF-only" feature.
- The credibility gate is where config *might* belong — but as configurable thresholds set deliberately, NOT a "PDF-only mode." And only IF the probe shows it's policy, not a denominator bug.

### PDF-only clarification (important — don't conflate)
Assembly-P.Coat is DXF-*independent* (grouping comes from PDF GA pages), which is a nice property — but it does **NOT** move the credibility gate and does **NOT** unlock PDF-only quoting. The real PDF-only levers are separate: (a) improving PDF geometry extraction so it's credible without DXFs, and/or (b) the credibility-gate policy (should electricals, which never have DXFs, drag the ratio?). Keep these separate from the assembly-P.Coat work.

---

## 8. OPEN THREADS — accurate post-closeout state (re-scoped this session)

Priority order reflects where things actually stand after today's work. Several items shifted — check the notes.

**🔴 TOP PRIORITY — Electrical price determinism (mains cable / junction box / earth strap).**
The 3 config-rate electricals drift run-to-run (mains cable seen at £0.42 → £1.69 → £1.89 → £1.59). **Newly sharpened by today's gate fix:** the credibility gate no longer suppresses the whole total, so this drift is now the *last visible source of run-to-run non-determinism on the regression anchor* — it's the one thing making two runs of 1282 not byte-identical. That undermines the "1282 is a stable anchor" premise, so it should be prioritised over the cleanliness items below. Root: priced by "Config rate card" default with non-deterministic behaviour; needs a deterministic rate or a stable source.

**🔵 BIG STRUCTURAL PIECE — Assembly-level P.Coat grouping** (see §6 — design ready, hierarchy substantially exists). Highest-value for closing the labour-model gap vs Tim, but needs the estimator P.Coat-costing probe first, and it's a proper piece of work (its own session). Build by weld-group NOT numeric family; hold DXF numbers byte-identical.

**🟡 Fix A — upstream `normalized_material="BOUGHT_IN"` stamp — OPEN but DOWNGRADED.**
The "single source of truth" fix: stamp bought-in-ness onto `normalized_material` at each recognition path (4 creation points set `page_roles=["bought_in"]` but only 1 sets the material; `file_scan.py`'s unconditional `normalise_material_for_part()` then defaults the rest to `MILD_STEEL`). **Deliberately deferred with its own consumer audit** — many things read `normalized_material`, so stamping `BOUGHT_IN` risks a costing consumer mishandling it. **Downgraded to cleanliness:** today's gate fix used `page_roles` instead, so the gate no longer *needs* this. Now purely "bought-ins shouldn't carry MILD_STEEL in raw data." Real but not urgent.

**🟡 Lens 1455-C-005 HIPS vs ACRYLIC — OPEN, but likely small.**
Still reads ACRYLIC; drawing (page 16) and DXF filename (`1455-C-005_1mm HIPS_revC.DXF`) both say HIPS. **Note:** `drawing_job_merge.py`'s `_DXF_MATERIAL_TOKENS` already HAS a HIPS token that should win. So the fix is likely "find why the existing HIPS token isn't applying to this part," NOT "build HIPS detection." Probe before assuming new work. Tim also treats it as SUBPLAS bought-in plastic (£1.07), not fabricated.

**❓ Per-bay ×2 multiplier (FIXING/VINYL rows) — CHECK STATE, may be partly/fully done.**
Today's runs show `[bom_tree]` IS applying ×2 (1448-01, 3886-01 etc. "qty 1 → 2 (GA tree)"), and `bom_tree.py`'s bought-in-inheritance explicitly handles "FIXING125 on the 3886 drawing ×2 → inherits ×2 → 4." So this may already be done. **Verify the specific FIXING/VINYL rows that were wrong are now correct before treating as open work.**

**🟢 Lower / cosmetic:**
- **`ZERO_COST_STEEL` flags misfiring** on costed steel parts (£3–13) on Provenance. From the learning engine (`_learning_flag`), NOT the report files. Cosmetic but visible.
- **Downlight £26 at match score 0.125** (weak bundle match). Could add a min-score floor (~0.3) so it flags-unpriced. **Note:** now inside the "credible" bucket post-gate-fix, so the gate no longer guards it.
- **`document_total £194.69 vs extended-sum £165.56` denominator discrepancy** — flagged during the gate probes; the credible_cost_ratio divides by the extended-cost sum, not the printed document_total. Worth a look; didn't affect the gate fix (operated on numerator).

**✅ CLOSED this session (do NOT re-queue):**
- **Credibility gate bug** — fixed + verified (see top banner).
- **AI Provenance sheet fix** — DONE earlier this session (`estimation_report.py`, fingerprint `_find_wb_sell_price_ref` at lines 39/56/341). If a stale `/mnt/project/` copy shows it as open, confirm with `Select-String -Path C:\ClaudeVision\src\estimation_report.py -Pattern "_find_wb_sell_price_ref"`.
- **Decision Report fix** — DONE + verified (`job_decision_report.py`, `_is_bought_in` at 9 call sites).

**Sheet-steel routing note (confirmed sound this session):** flat steel → sheet steel block, tube → standard materials (1448-01, 3886-01 as SLOTTEDTUBE01/02), acrylic/HIPS → other-sheet, bought-ins → own block. Correct separation by material type; good generalisation signal.

**Verifier blind-spot note (for future byte-identical checks):** `_credibility_fix_verify.py` compares two *separate pipeline runs*, so a known-noisy price (the 3 config-rate electricals) drifting between runs trips the byte-identical check with a "FAIL" that isn't a real regression. Fix for next time: either whitelist the 3 known-noisy electricals, or compare patch-vs-no-patch on the *same* run's inputs. Today's "FAIL" was exactly this — only `BI-MAINSCABLE` moved, reconciling to the penny.

---

## 9. Working discipline (locked — these kept us out of trouble)

- **PROBE/READ real src before editing.** Vindicated hard this session — the GA probe found `bom_tree.py` substantially exists; charging in would have rebuilt/conflicted with existing machinery.
- **DRAWING-DERIVABILITY is the no-mocking test for routing:** build only what the engine can re-derive on the next drawing; flag (don't invent) what isn't in the drawing. Caught the punch-vs-laser overfit and the roll/spotweld traps.
- **Edit → run → parity → confirm, ONE change at a time.** Job 1282 is the regression anchor.
- **Confirm-before-stacking:** verify each deployed fix in a real run before building the next.
- **Build calibration on 1282 (Tim's benchmark), not new drawings.** Use new drawings to test generalisation.
- **Diagnostic-probe-first:** read-only probes with NEW filenames, dump to UTF-8 file, paste from there (cp1252 crashes on emoji).
- **Traceability:** every price traceable to a real source (historical line, catalogue entry, explicit config rate). Phantom fallback prices are a defect category.

---

## 10. Deliverables this session (in `/mnt/user-data/outputs/`)

**Deployed & confirmed:** `job_decision_report.py`, `estimation_report.py`.
**Read-only probes:** `_routing_signal_probe.py`, `_ga_hierarchy_probe.py`, `_credibility_gate_probe.py` (last one: result pending).
**Next deliverable to build:** assembly-level P.Coat grouping — after probing the estimator's P.Coat-costing code + `assembly_relations`. Group by weld-group (not numeric family). Build on 1282, verify vs Tim's grouped P.Coat lines, hold DXF numbers byte-identical.

---

## 11. First moves for the next chat

The credibility gate is DONE (top banner). Pick up from here:

1. **Electrical determinism (🔴 top priority)** — make the 3 config-rate electricals (mains cable, junction box, earth strap) deterministic. This is now the last drift source on the regression anchor. Probe how `pricing_service.py` / config-rate prices these, find the non-determinism, apply a stable rate. Verify two consecutive 1282 runs are byte-identical.
2. **Confirm the "possibly-done" items** so they don't get re-worked: `Select-String estimation_report.py -Pattern "_find_wb_sell_price_ref"` (Provenance sheet — should be done); check the FIXING/VINYL per-bay ×2 rows are now correct (bom_tree may already handle it).
3. **Assembly-P.Coat (🔵 big piece)** — probe the estimator's **P.Coat costing code + `assembly_relations`**, design assembly-coat grouping (by weld-group NOT numeric family — 3886-01 leg coats separately from the footbase assembly), build on 1282, verify vs Tim's "HEADER COMPLETE"/"FOOT ASSEMBLY" coat lines, **hold 1282 DXF numbers byte-identical**.
4. **Lens HIPS (🟡, likely small)** — probe why the existing `_DXF_MATERIAL_TOKENS` HIPS token isn't applying to 1455-C-005 before assuming new work.
5. Optionally re-run 1282 at **qty 100** for a like-for-like parity number vs Tim's £168.68.

**Deliverables added this session (in `/mnt/user-data/outputs/`):** `_boughtin_tag_probe.py`, `_cost_credibility_probe.py`, `_gate_fix_verify.py`, `_raw_gate_dump.py`, `_patch_landed_probe.py`, `_verify_patch_target.py`, `_apply_boughtin_exemption_patch.py` (the applier that landed the fix). Deployed + confirmed: the `_part_cost_credibility` bought-in exemption in `estimator.py`.

---

## 12. LATER SESSION 21 (continued) — generalisation runs, packaging/delivery, BOM-widen failure + recovery

### 12.1 Generalisation testing began (observe-first, don't fix-each)
- **Strategic pivot:** 1282 is now the REGRESSION ANCHOR, not the dev target. Moved to running NEW drawings to test generalisation. Cadence agreed: **~2 jobs/day averaged** (bank buffer on easy days for hard ones); **run + catalogue** most days, **batch-fix only when a pattern is confirmed across several jobs** (a fix vs 1 example is a guess). **Findability is the real rate-limiter** — front-load a queue of James-Ryan-classified jobs that have LOCATABLE standalone manual sheets. Keep a consistent per-job log (job, benchmark £, engine £, %gap, findings) to turn volume into "systemic vs one-off".

### 12.2 Job 1298 Drill Holder (TTI) — FIRST generalisation run — STRONG result
- Folder: `...Live Enquiry\1298DrillHolder` (has PDF revF, DXF 1298-01 MS 1.2mm, + a STEP file the engine harmlessly ignores).
- **Engine £3.37 (qty 100) vs Tim's manual £3.10 (qty 400) ≈ +9% on a brand-new job.** Material is DXF-exact (arguably MORE precise than Tim's rounded figures). Part number 1298-01 is a two-group code (vs 1282's three-group) but DXF matched via tolerant fallback — NO config fix needed.
- **Findings catalogued (diagnosed via read-only probes, NOT yet fixed):**
  1. **`hole_machining` → GUIL bug** (~£0.29 spurious). Emitted from holes (extractor_patterns.py ~1085), but NOT in wb_populate OP_NAME_MAP, so it falls through to Guillotine. FIX DIRECTION: for METAL parts, suppress hole_machining as a separate op — holes fold into laser (Tim's convention; his op-list has no metal hole/drill op, only "Drill (Acrylic)"). **CONFIRMED 1282-SAFE**: all 30 1282 parts have has_hole_op=False (1282 already absorbs holes into laser, incl. 1449's 386 holes). Ready to write. **This is the one obviously-wrong line an estimator would flag — fix before sending 1298 to Dave/James.**
  2. **Order quantity is not a proper input.** Engine has 3 disconnected quantities (drawing BOM part-qty, WB default D6, real order). Real order (Tim's 400) is an ENQUIRY fact, not on the drawing. LOG: add a `--quantity` per-job flag (preferred over the sticky ENV var). Not fixed.
  3. **Powder-coat £0 is CORRECT (no-mock).** All 3 PDF pages defer finish ("SEE INDIVIDUAL DRAWINGS" / "REFER TO ORDER"). Finish is an ORDER-level fact Tim has, not on the drawing. Engine correctly costs £0 (has full P.Coat machinery ready). Inventing it would be MOCKING. Only honest improvement: surface the deferred-finish flag more loudly. **Frame this as a SELLING POINT to estimators** ("engine won't invent a finish the drawing doesn't specify") — but frame it, or it looks like a miss.
- **BIG INSIGHT:** the £3.37 vs £3.10 gap ≈ enquiry-level items (£0.80 powder + £0.13 fastener) + the hole_machining bug (£0.29). The drawing-derived CORE (£0.38 bracket, laser/fold) is SOUND. The engine's honest CEILING from drawings-alone = fabricated-part cost + clear flags for what the ORDER must supply.

### 12.3 Packaging/Delivery rows — fix works in principle, but exposed a capacity limit
- **Decision:** estimators want Packaging + Delivery as two always-present rows, priced £0 (blank, for the estimator to fill — NOT invented defaults).
- **Applied** (`_apply_packaging_delivery_rows.py`, fingerprint "write as blank-price" at wb_populate.py:313): they were in JSON (page_roles bought_in) but DROP_CODES dropped them; now routed into bom_parts at £0.
- **Works cleanly on 1298** (few BOM parts). **On 1282 it overflowed** — 1282 already had 15 BOM parts (the block limit), +2 = 17 → the two £0 rows fell off the end. All PRICED items survived; total unharmed. So on 1282 the fix was correct-but-no-op (overflowed off). This motivated the BOM widen ↓.

### 12.4 BOM WIDEN — FAILED, then RECOVERED. **READ THIS BEFORE RE-ATTEMPTING.**
**What was tried:** widen the BOM block from 15 rows (11-25) to fit 17. Two changes: (a) template re-saved with more BOM rows (11-31), (b) wb_populate cell-map `last_row` bumped 25→31.

**What broke:** every subsequent run → `[wb_populate] failed ('MergedCell' object attribute 'value' is read-only) — falling back to xlsx_output`. This produced the MALFORMED `_json_`-named fallback sheet (dicts-in-cells in "Total Value", "SDIAIVision" preparer, "Handle"/"Powder Coat" old labour model, total drifting to £223.02). **This fallback is the OLD `ai_spreadsheet_generator`/`xlsx_output` path** (config.py:826 template `EmptyEstimating/Blank Estimate Sheet 2026.xlsx`), NOT a separate feature — wb_populate CRASHES and silently falls back to it.

**ROOT CAUSE (diagnosed via `_merged_cell_diag.py`, read-only — lists all 110 merged ranges + the cell-map):**
- The BOM columns themselves were fine (writes col C = top-left of each C:G merge; cols H-L outside merges).
- **The real cause: widening the BOM by pushing `last_row` to 31 made the BOM block OVERLAP the next block.** The template lays sections out CONTIGUOUSLY: BOM 11-25, "Wire" heading row 26, Wire data from row 28, Steel 38-48, Other-sheet 51-58, Labour 63+. Inserting BOM rows SHIFTED every section below DOWN, but only the BOM's `last_row` was updated in code. So wb_populate's cell-map (Wire@28, Steel@38, Labour@63…) desynced from the template's new positions, and the engine wrote BOM data into rows that were now merged for the Wire section → MergedCell crash.

**RECOVERY (done, end of session):**
- Deleted the added template rows → template back to original layout ("Wire" heading row 26, Wire data row 28).
- Reverted code: `_revert_bom_lastrow.py` set BOM `last_row` 31→25 (fingerprint `"first_row": 11, "last_row": 25`, confirmed at wb_populate.py:60).
- Re-run 1282 to confirm `[wb_populate] Populated template saved` (NOT "failed MergedCell"). **[STATUS AT SESSION END: revert applied + fingerprint confirmed; final confirming run was in progress — verify the "Populated template saved" line first thing next session.]**

**THE LESSON (bank this):** Widening the BOM block is NOT a one-line `last_row` bump. Inserting rows in the template shifts EVERY block below it (Wire, Steel, Other-sheet, Labour), desyncing wb_populate's ENTIRE cell-map. The PROPER widen = (1) insert rows in the template, (2) clear any merged cells in the write columns of the new rows, (3) update EVERY block's `first_row`/`last_row` in wb_populate to match the shifted layout, (4) verify each block writes to the right rows. A careful, systematic, fresh-eyes task — NOT end-of-day. Until then, BOM stays at 15 rows and 1282's packaging/delivery overflow off (sheet correct, just missing those 2 blank rows).

### 12.5 🔴 wb_populate SILENT FALLBACK is dangerous
When wb_populate throws, it silently falls back to the malformed `ai_spreadsheet_generator`/`xlsx_output` path, producing a BROKEN sheet (dicts-in-cells) rather than an obvious stop. This is how a template problem nearly produced a bad sheet. **Next session: make the fallback LOUD (raise/halt on wb_populate failure) or disable the malformed generator entirely, so a template issue can NEVER quietly ship a bad sheet to an estimator.** Two spreadsheet paths exist and produce different-looking output; only the wb_populate one (spaces in filename) is good; the `_json_`-named one is the broken fallback — never send it to anyone.

### 12.6 Validation signal
Dave Wright (head estimator) expressed being IMPRESSED with the 1282 sheet — first estimator validation. Worth asking what specifically stood out. **Plan to send a SECOND drawing (1298) to Dave & James** — but FIRST: fix hole_machining→laser (remove the one obviously-wrong line), and be ready to frame the powder-£0 as honest no-mock. NEVER send the malformed `_json_` fallback sheet.

### 12.7 First moves next session (revised)
1. **Confirm recovery:** re-run 1282, verify `[wb_populate] Populated template saved` (spaces-named file, clean structure — no dicts-in-cells). Expect the "BOM overflow 17/15" flag — that's EXPECTED (packaging/delivery overflow off; sheet correct).
2. **Make wb_populate fallback LOUD** (§12.5) — safety fix so a crash can't ship a malformed sheet.
3. **Fix hole_machining→laser for metal parts** (§12.2.1 — diagnosed, located, 1282-safe) so 1298 has no obviously-wrong line before it goes to estimators.
4. **Send 1298 to Dave & James** with the powder-£0 no-mock framing.
5. **Then** (bigger, fresh-eyes): properly widen the BOM block (§12.4 — insert rows + re-map ALL blocks + clear merges), then re-land packaging/delivery so they fit on 1282.
6. Electrical determinism (§11.1) still stands as the top pre-existing thread.

### 12.8 🔴 REQUIREMENT: BOM block must scale for large jobs — do it by LABEL-ANCHORING
The 15-row BOM limit is not acceptable long-term — 1282 already overflows and larger jobs will be worse. The widen MUST happen; today's failure was the METHOD, not the goal.

**Two ways to do it, in order of preference:**

**(A) DURABLE FIX — label-anchor the block boundaries (RECOMMENDED).** Instead of hardcoded `first_row`/`last_row` per block in wb_populate's cell-map, make wb_populate SCAN the template for each section's HEADING label ("Bill of Materials" / "Wire" / "Sheet Steel" / "Other Sheet Material" / "Labour") and derive each block's start row dynamically — exactly the pattern `_find_wb_sell_price_ref` already uses to anchor on "Sell Price". Then the template can be widened freely (insert any number of BOM rows) with ZERO code changes — the code finds where each section is by its heading. This PERMANENTLY kills the "code and template disagree about row numbers" failure class that broke today's widen. Matches James's validated label-anchoring instinct. More work up front; correct.

**(B) PRAGMATIC FIX — insert rows + re-map every block.** If doing it the hardcoded way for now:
  1. In the template, select the row below the last BOM row (Wire heading, ~row 26) and **Insert N rows** (Excel pushes Wire/Steel/Other/Labour down by N and auto-adjusts their formulas/SUMs/cross-refs).
  2. Copy the BOM row formulas (`=LOOKUP...` price, `=(J*K)*(1+L)` total) down into the N new rows; **clear/avoid merged cells** in the engine's write columns (merges were today's crash — inserted rows inherit merges from the row above).
  3. In wb_populate's cell-map, add N to the BOM `last_row` AND add N to BOTH `first_row` and `last_row` of EVERY block below the insertion point (wire, steel, other_sheet, labour). This is the step that was missed today — only BOM was updated, so everything desynced.
  4. Verify block-by-block on 1282: each section's data must land in its own rows (no bleed across).

Prefer (A). It's the real answer for variable-size jobs and removes an entire class of fragility.

### 12.9 hole_machining metal fix — PARTIAL (extractor guarded, but op survives via another path)
**Goal:** metal parts should NOT emit a separate hole_machining/drilling op — metal holes are laser-cut (fold into laser), matching Tim (no metal hole op; only "Drill (Acrylic)") and 1282 (all metal, no hole ops). On 1298 (MILD STEEL Drill Holder) hole_machining falls through to Guillotine → spurious £0.29 line + `⚠ not in OP_NAME_MAP` warning.

**Applied (necessary but INSUFFICIENT):** `_apply_metal_hole_op_fix.py` guarded the emission in `extractor_patterns.py:1087` → `if hole_cue and not is_sheet_steel:`. Fingerprint confirmed. BUT re-running 1298 STILL shows `Operations: hole_machining, laser_cutting, folding, handling, drilling` and the GUIL £0.29 line persists (total still £3.37, warning still printed). So hole_machining is ALSO arriving via a DIFFERENT path — likely the DXF/geometry op-assembly or the `drilling`/`DRILL → hole_machining` normalisation (`json_normaliser.py:83 "DRILL": "hole_machining"`; `operation_normaliser.py` maps DRIL into hole_machining).

**CORRECT FIX LOCATION (diagnosed, ready for next session):** `document_builder.py` — this is where a part's final `operations`/`textual_operations` are assembled and CLEANED per-material. It ALREADY has the pattern:
  - lines ~893-916: wire parts strip sheet-metal ops (incl. hole_machining) and swap wire route.
  - lines ~926+: "Fix C" strips fabrication ops from NON-metal parts (MDF/timber/acrylic).
There is NO equivalent rule stripping hole_machining from METAL parts. **Add one:** for sheet-steel/metal parts, remove `hole_machining` (and check `drilling`) from the ops set — holes fold into laser. Mirror the existing Fix C / wire-strip pattern (~15 lines, known location). Keep the extractor guard (it's correct, just not sufficient alone).
**Verify:** 1282 byte-identical (already no metal hole ops), 1298 loses the GUIL line AND the `drilling` op, total ~£3.08. Also confirm no OTHER metal part anywhere regresses.
**NOTE — acrylic must keep drilling:** the strip is METAL-ONLY. Tim's "Drill (Acrylic)" is a real op; non-metal parts keep hole_machining/drilling.

**STATUS:** partial fix deployed (extractor guard, harmless), full fix diagnosed + located, NOT yet applied. 1298 NOT yet sendable to Dave/James until the GUIL line is gone.

### 12.10 hole_machining ROOT CAUSE FOUND (via _hole_op_stage_trace.py) — 3 prior fixes were on the WRONG field/branch
**The trace of 1298-01's persisted JSON revealed the truth:**
```
operations             = []                                          <- EMPTY
textual_operations     = ['hole_machining','laser_cutting','folding','handling']   <- STALE, still has it
mfg_interp.routing     = ['laser_cutting','folding','handling']      <- CORRECT (no hole_machining!)
```

**What this means:**
1. `manufacturing_interpretation.routing` is ALREADY CORRECT — the interpretation layer (`_interpret_part`) correctly drops hole_machining for this metal part (holes fold into laser). So the engine already "knows" the right route.
2. `textual_operations` still carries a STALE hole_machining. wb_populate reads `textual_operations` (the raw list), NOT the clean `routing` — so the stale op reaches the sheet -> GUIL £0.29 line.
3. `operations` is `[]` (empty) — so Fix D's strip of `operations` was a no-op, and Fix D is NOT firing on this part at all (else textual_operations would be stripped too). Its condition (`_is_metal_mat or inherited_steel and not _is_non_metal_mat`) is not matching 1298-01 at runtime — reason unconfirmed (check mat_upper_joined / _is_non_metal_mat values for this part).

**THREE PRIOR FIXES WERE INEFFECTIVE (revert or fix condition next session):**
- `extractor_patterns.py:1087` `if hole_cue and not is_sheet_steel` — harmless but didn't solve it.
- `document_builder.py` Fix D (~1008-1028, "Fix D: METAL parts") — NEVER FIRES on 1298-01 (condition mismatch). Currently dead/ineffective. Revert or fix its condition.
- These edits are cruft until the real fix lands. Clean them up.

**THE REAL FIX (two clean options — pick next session, REGRESSION-TEST on 1282):**
- **Option B (likely correct, but higher blast radius):** make wb_populate read the authoritative interpreted route (`manufacturing_interpretation.routing`, or `operations` once populated) instead of raw `textual_operations`. `routing` is ALREADY correct here. BUT this changes op-sourcing for EVERY part on EVERY job — must full-regression 1282 (labour must stay £72.38 / total £203.99) before trusting. NOT an end-of-day change.
- **Option A (narrower):** fix WHY Fix D's condition doesn't match 1298-01 (probe mat_upper_joined/_is_non_metal_mat at that point), so it strips textual_operations for metal parts. Lower blast radius but leaves the deeper "wb_populate reads the stale field" issue for another day.

**Recommendation:** Option B is architecturally right (routing is the source of truth, matching the "WB/interpretation is authoritative" principle), but do it fresh with a full 1282 regression. Meanwhile 1298 is NOT sendable with the GUIL line — either fix next session or manually delete that one line if a sheet is needed urgently.

**STATUS:** root cause fully understood; no working fix deployed; 3 ineffective edits to revert; real fix scoped for next session with regression plan.
