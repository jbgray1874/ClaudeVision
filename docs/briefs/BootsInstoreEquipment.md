# Boots In-store Equipment Design Standards (BFDG v6, June 2026) — reference document

**File:** `chatgptdropoff/BootInstoreEquipmentDesignStandardsBFDGv6June2026LowRes.pdf` (101 pages,
read in full 11 Oct 2026). **This is a STANDARDS MANUAL, never a product**: it defines the
requirements any fixture supplied to Boots must meet. On a portal run it rides as a ticked
REFERENCE document (D-474) beside the product's own pack and brief; its example fixtures,
test rigs, doors, chairs, screens and electrical systems are never costed.

## What the manual is

Eight sections: 1 About the standards (definitions — an **FSDU is "a temporary structure…
not physically or mechanically connected… to a permanent fixture"**); 2 Standards (BS/EN
list, environmental policy, design approval); 3 Safety (risk assessment, stability, edges,
mechanisms, glass, fixings, O&M); 4 Design guidance (process, deliverables, prototypes and
trials, drawings/CAD, ESC, Sustain®, O&M manuals, design requirements, structure, materials,
electrical); 5 BTC test certification (BTC001–BTC021); 6 Manufacture (first-off, packaging,
instruction drawings, QR labels, QC); 7 Implementation (housekeeping, installation,
delivery); 8 Appendices (BTC certificate, drawing-pack and O&M examples, H&S, electrical
TBGE1, environmental policies).

**Pages 84–86 (Appendix A) are drawing-pack examples, "for reference only" in the manual's
own words** — they state the level of drawing detail Boots expects, not products to make.

## Requirements → costing treatment (per-order PROJECT lines unless stated)

| Requirement (where) | Treatment on the estimate |
|---|---|
| Design approval at every stage; IR Upload Portal; ISE Compliance Certificate per design (2.3, p11) | Project cost — documentation/approvals allowance |
| Design process deliverables: preliminary + prototype development design, **prototype & trial**, trial learnings, tender pack (4.1.13–4.1.17) | Project cost — design development + prototype allowances |
| Technical drawing pack to Appendix A standard; 3D manufacturing CAD; CAD blocks (plan/side/front, 1:1 metric, hidden-line) (4.3.1–4.3.2, 4.4.2) | Project cost — drawings/CAD deliverables allowance |
| **Sustain®** (POPAI) environmental result with every design submission, packaging carbon included (4.3.3, **p43**; 6.3) | Project cost — **a provisional assessment allowance RETAINED**, with the CLASSIFICATION CONFLICT recorded: the manual defines an FSDU as temporary and routes temporary fixtures via In-store Marketing, while the K-Wellness brief specifies a PERMANENT metal FSDU — never silently exempted; Boots confirms which regime applies |
| **BTC testing** — vendor evaluates applicable tests with due diligence; minimum: relevant BTC passed with a compliance certificate per equipment piece, video + photo records by a qualified person (5.0.1, p62). SELECT the applicable tests, never all: BTC004/005 cover the STANDARD 760mm shelf, BTC006/007 the CUSTOM sizes — a shelved FSDU with 500/350mm trays takes topple BTC001, tilt BTC002, bump BTC003 and the custom-size deflection pair BTC006/007. **Source inconsistency on p66, flagged never resolved silently:** the prose states "1.5kg per 100mm²" while the worked example computes 1.5kg per 100×100mm square (a 300×200 shelf loads 9kg, not 900kg) — the worked example is the evident intent; confirm with Boots | Project cost — testing allowance, the selected tests named |
| **O&M manual** for all fixtures: intro, H&S, tool-free illustrated assembly, end-of-life/recycling, cleaning regime (4.4.1, p44; Appendix B examples) | Project cost — documentation allowance |
| First-off production sample, same factory/materials/CAD (6.2, p76) | Project cost — first-off allowance (or absorbed in prototype; never both) |
| Packaging fit for purpose, recyclable, single-material where possible, drop/transit tested if fragile (6.3, p76) | Carried by the commercial PACKAGING line — never duplicated |
| **QR label on every component**: ISO/IEC 18004, plain text `BOOTS_CODE=…\|COMPONENT=…\|SUPPLIER=…\|DATE=DD-MM-YYYY\|LOCATION=…`, printed **20×20mm**, discreet placement; a too-small component goes to the D&D team (the stated exception process) (6.5, p76–77) | Per-unit production requirement — label PRODUCTION, APPLICATION and VERIFICATION per component, not the sticker price alone |
| QC: batch setup, SAMPLED inspection (100% is stated as not physically possible) plus unit checks, quarantine, records + photos, QC labels; delivery POD (6.6–6.9, 7.3) | Priced on that actual basis — batch setup per order + sampled/unit checks — never a full inspection charged on every unit |

## Constraining standards — these SHAPE the product (never minted as parts)

- **All components rounded, chamfered or deburred** — no sharp edges, corners especially
  (3.1, 4.6). Safe-edge deburring/edge finishing is the requirement; **dressing every weld
  flush is NOT implied** — weld dressing is priced per the construction and finish asked
  for, separately.
- **Tubular components capped or closed** (3.1).
- **Stability**: resistant to topple under foreseeable force, children climbing considered;
  BTC001/002 govern (3.1, 3.3.3, 4.6.1).
- **'Medium Hazard' fire rating** sits with BS 7176, the UPHOLSTERED non-domestic seating
  standard (2.1) — it is not a blanket requirement on a steel FSDU's materials; apply it
  where upholstery/composites exist. Materials free of toxics/VOCs so far as possible (4.7).
- **Glass minimised; acrylic first option**; any glass toughened/tempered/laminated,
  EN 12600 Type B/C, no metal-to-glass contact (≥0.5mm separation) (4.7.1). K-Wellness: no
  glass — states compliance, costs nothing.
- **Plinth/base visually discernible from the floor** (Equality Act, 4.5.4) — affects base
  finish/graphic contrast, not a new part.
- **Flat-pack must be considered where appropriate**; design for disassembly and recycling
  (2.2, 4.5.5) — affects construction choice and packaging.
- **In-store assembly must be tool-free** (O&M 4.4.1) — the K-Wellness hooked trays make
  SHELF FITTING tool-free, which does not prove the WHOLE unit's in-store assembly is:
  confirm the delivered assembly state (fully assembled vs flat-pack) before relying on it.
- **Electrical (TBGE1, ESC certification)**: only where the fixture contains electrics —
  K-Wellness has none; explicitly not applicable.
- Gondola/perimeter bay standard width 760mm (4.5.1) — context for standard shelving, not
  a constraint on an FSDU's own footprint.

## For the K-Wellness all-in book

Stage `KWellnessFSDU.pdf` + this manual, tick the manual as reference, K-Wellness brief in
the box. Expected `applicable_requirements`: design development/prototype, drawings/CAD
pack, BTC testing (topple/tilt/bump/shelf deflection), O&M manual, Sustain® (confirm — see
temporary-fixture note), first-off sample, QR component labels (per-unit), QC/inspection.
Expected NOT applicable: electrical/ESC, glass, seating/table tests (BTC008–BTC021 largely),
mirrors. Reference fixtures from this manual: never on the bill — the facts file's
forbidden names stand.
