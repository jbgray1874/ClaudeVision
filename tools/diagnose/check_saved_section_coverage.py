"""Read-only probe of a FULL saved job record against the section-schedule contract (D-576):
never a new drawing, model or price read.

    python tools/diagnose/check_saved_section_coverage.py output/json/<stem>.json --recompile-repaired

Prints the audit of the saved record as it stands, the repair the contract would make, and
with --cost-repaired the real offline material estimate of the repaired records;
--recompile-repaired re-estimates them, recompiles the route with the real compiler and runs
the workbook-input hand-off, whose result it prints. Material proof, not an Excel proof.
Nothing is written unless --out names a file, and never the source record.
Probe as proposed in the Codex review package of 21 Oct 2026, kept here.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument("record", type=Path)
p.add_argument("--engine", type=Path, default=Path(__file__).resolve().parents[2],
               help="the engine checkout (default: this one)")
p.add_argument("--cost-repaired", action="store_true")
p.add_argument("--recompile-repaired", action="store_true",
               help="Re-estimate changed parts offline, recompile with real engine, exercise patched workbook gate")
p.add_argument("--out", type=Path, help="Write diagnostic proof JSON here, never to the source record")
a = p.parse_args()
os.environ["SDI_OFFLINE"] = "1"
sys.path[:0] = [str(a.engine / "src")]
import section_coverage_contract as c
s = json.loads(a.record.read_text(encoding="utf8"))
if s.get("schema") == "sdi.job_record_slice.v1":
    p.error("Use the FULL saved JSON: the diagnostic slice omits members and truncates page text.")
estimates = copy.deepcopy((s.get("estimate_summary") or {}).get("canonical_part_estimates")
                          or (s.get("estimate_summary") or {}).get("part_estimates") or [])
if not estimates:
    p.error("The record holds no part estimates to audit.")
proof = {"record": str(a.record), "before": c.audit(s, estimates),
         "excel_verified": False, "live_prices_verified": False}
print("BEFORE", json.dumps(proof["before"], indent=2))
changed = c.prepare(s)
proof["repaired_parts"] = changed
print("REPAIRED", changed)
for rec in c.parts_of(s):
    if rec.get("section_coverage_repair"):
        print(rec["part_number"], json.dumps(rec["section_coverage_repair"]))
if a.cost_repaired or a.recompile_repaired:
    import estimator
    for rec in c.parts_of(s):
        if rec.get("part_number") not in changed:
            continue
        material = estimator.estimate_material(rec)
        proof.setdefault("material", {})[rec["part_number"]] = {
            "unit_material_gbp": material.get("unit_material_cost_gbp"),
            "cost_method": material.get("cost_method"),
            "stock": material.get("stock_estimate")}
        print("REAL OFFLINE MATERIAL", rec["part_number"], json.dumps(material, default=str))
        for est in estimates:
            if est.get("part_number") == rec["part_number"]:
                est["material_estimate"] = material
    print("AFTER MATERIAL ONLY", json.dumps(c.audit(s, estimates), indent=2))
    print("Unchanged saved route deliberately retained: a missing saw must still fail until recompiled.")
if a.recompile_repaired:
    import route_compiler
    import wb_populate
    existing = s["estimate_summary"]["part_estimates"]
    for rec in c.parts_of(s):
        if rec.get("part_number") in changed:
            replacement = estimator.estimate_part(rec, job_quantity=1)
            existing[:] = [replacement if e.get("part_number") == rec["part_number"] else e for e in existing]
    route_compiler.refresh_canonical_route_after_reconciliation(s)
    canonical = wb_populate.canonicalise_part_estimates_for_workbook(s, existing)
    proof["final_contract"] = s.get("section_coverage_result")
    print("REAL COMPILER + WORKBOOK INPUT HAND-OFF", json.dumps(s.get("section_coverage_result"), indent=2))
    for e in canonical:
        if e.get("part_number") in changed:
            m = e.get("material_estimate") or {}
            print("REPAIRED CANONICAL LINE", e.get("part_number"), "qty", e.get("quantity"),
                  "length", (m.get("stock_estimate") or {}).get("section_length_mm"),
                  "unit material", m.get("unit_material_cost_gbp"))
            proof.setdefault("final_lines", []).append({"part": e.get("part_number"),
                "quantity": e.get("quantity"), "unit_material_gbp": m.get("unit_material_cost_gbp"),
                "section_length_mm": (m.get("stock_estimate") or {}).get("section_length_mm")})
if a.out:
    if a.out.resolve() == a.record.resolve():
        p.error("Diagnostic output must not overwrite the source record")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(proof, indent=2), encoding="utf8")
print("No source, workbook, cache or live engine file was modified.")
