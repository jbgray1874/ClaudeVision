r"""READ-ONLY. Map the 12532 new-job report template to real summary-JSON fields, so the generic
builder pulls actual data per section. For each report section, find the JSON source:
  Header: job number, assembly desc, drawing pack counts (pages/PDFs/DXFs), quantity
  Headline figs: unit cost (WEP m105), material (m59), labour (m103), parts costed counts
  S1 glance: cost streams (steel/BOM/acrylic/powder/labour) — from part_estimates grouped
  S2 what's-right: derivable from flags absent / streams separated / fixes applied
  S3 review items: manual_review_items / low-confidence / risk_flags / provisional
  S4 drawing analysis: parts_without_dxf, validation.issues, contaminated fields, filename issues,
     part-number format variety, junk records
  S5 checklist: the review items again as a checklist
  S6 Design recs: mostly static (naming, per-part material, clean DXF, no spaces, BOM layout)
  S7 verdict: computed summary
Use the 1282 JSON as the concrete example (we have it on disk). No edits — map fields."""
import json
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{})

def show(label, val, depth=0):
    t=type(val).__name__
    if isinstance(val,dict):
        print(f"  {label}: dict[{len(val)}] keys={list(val)[:8]}")
    elif isinstance(val,list):
        print(f"  {label}: list[{len(val)}]" + (f" e.g. {str(val[0])[:60]}" if val else ""))
    else:
        print(f"  {label}: {t} = {str(val)[:70]}")

print("="*70); print("TOP-LEVEL summary keys"); print("="*70)
for k in S: show(k, S[k])

print("\n"+"="*70); print("estimate_summary keys (headline figs + parts)"); print("="*70)
for k in es: show(f"estimate_summary.{k}", es[k])

print("\n"+"="*70); print("HEADER: job / assembly / pack counts / qty"); print("="*70)
for path in ["job_output_stem","job_folder","primary_pdf"]:
    show(path, S.get(path))
show("pages", S.get("pages"))
show("estimate_summary.estimate_workbook_inputs", es.get("estimate_workbook_inputs"))
ewi=es.get("estimate_workbook_inputs",{}) or {}
show("  assumed_job_quantity", ewi.get("assumed_job_quantity"))
# count pdfs/dxfs
pages=S.get("pages") or []
print(f"  pages count: {len(pages)}")

print("\n"+"="*70); print("HEADLINE FIGURES (WEP)"); print("="*70)
wep=es.get("workbook_equivalent_pricing",{}) or {}
for k in wep: show(f"  wep.{k}", wep[k])

print("\n"+"="*70); print("S1 COST STREAMS: part_estimates grouping"); print("="*70)
pe=es.get("part_estimates") or []
print(f"  part_estimates: {len(pe)}")
if pe:
    print("  sample part keys:", list(pe[0])[:12])
    me=pe[0].get("material_estimate",{})
    print("  material_estimate keys:", list(me)[:12])
    proc=pe[0].get("process_estimate",{})
    print("  process_estimate keys:", list(proc)[:12])

print("\n"+"="*70); print("S3/S4 REVIEW + DRAWING QUALITY fields"); print("="*70)
for path in ["manual_review_items","validation","parts_without_dxf","estimate_review_signals",
             "bom_code_quality_findings","powder_coating_summary"]:
    # check both top-level and under estimate_summary
    v = S.get(path) if path in S else es.get(path)
    show(f"  {path}", v)
val=S.get("validation") or es.get("validation") or {}
if isinstance(val,dict):
    show("    validation.issues", val.get("issues"))

# risk flags across parts
allflags=set()
for p in pe:
    for f in (p.get("risk_flags") or []): allflags.add(f)
print(f"  distinct risk_flags across parts: {sorted(allflags)[:12]}")
