r"""READ-ONLY. The report's drawing-analysis makes claims that will inform the Design team, so they
must be TRUE. Verify three against the real 1282 JSON:
  1) 'Parts without a DXF: 1448-01, 2621-01C, 3886-01' — are these GENUINELY DXF-less, or does
     dxf_augmentation.parts_without_dxf list something else? Show the raw field + cross-check against
     dxf_augmentation.matched (do these parts appear as matched elsewhere?).
  2) 'Contaminated/low-confidence fields: 47' — what ARE these 47? Break down manual_review_items by
     severity (error vs warning vs info) so the report can distinguish real contamination from minor
     notes. Show a sample.
  3) 'Geometry reliability: 0.97' — is document_geometry_reliability a NUMBER or a label? Show it raw.
No edits — verify the claims are accurate before this informs Design."""
import json
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))

print("="*66); print("1 — parts_without_dxf: genuine, or matched elsewhere?"); print("="*66)
dxf=S.get("dxf_augmentation",{}) or {}
pwd=dxf.get("parts_without_dxf") or []
print(f"  parts_without_dxf ({len(pwd)}): {[p.get('part_number') if isinstance(p,dict) else p for p in pwd]}")
matched=dxf.get("matched") or []
matched_parts=set()
for m in matched:
    if isinstance(m,dict):
        pn=m.get("part_number") or m.get("part") or m.get("matched_part")
        if pn: matched_parts.add(str(pn))
print(f"  matched parts ({len(matched_parts)}): {sorted(matched_parts)[:15]}")
# do the 'without_dxf' parts appear in matched?
for p in pwd:
    pn=str(p.get('part_number') if isinstance(p,dict) else p)
    in_matched = pn in matched_parts
    print(f"    {pn}: in matched list? {in_matched}  {'<-- CONTRADICTION' if in_matched else ''}")
    # show the full record for context
    if isinstance(p,dict):
        print(f"        record: {json.dumps(p)[:120]}")

print("\n"+"="*66); print("2 — the 47 'contaminated fields' broken down by severity"); print("="*66)
mri=S.get("manual_review_items") or []
from collections import Counter
sev_count=Counter(); field_count=Counter(); samples=[]
for item in mri:
    if not isinstance(item,dict): continue
    for iss in (item.get("issues") or []):
        if isinstance(iss,dict):
            sev=iss.get("severity","?"); fld=iss.get("field","?")
            sev_count[sev]+=1; field_count[fld]+=1
            if len(samples)<8:
                samples.append((item.get("page_number"),sev,fld,str(iss.get("message") or iss.get("note") or "")[:50]))
print(f"  total issues across manual_review_items: {sum(sev_count.values())}")
print(f"  by severity: {dict(sev_count)}")
print(f"  by field: {dict(field_count.most_common(8))}")
print("  samples:")
for pg,sev,fld,msg in samples:
    print(f"    p{pg} [{sev}] {fld}: {msg}")

print("\n"+"="*66); print("3 — document_geometry_reliability: number or label?"); print("="*66)
geo=S.get("geometry_summary",{}) or {}
gr=geo.get("document_geometry_reliability")
oc=geo.get("overall_confidence")
print(f"  document_geometry_reliability = {gr!r}  (type {type(gr).__name__})")
print(f"  overall_confidence            = {oc!r}  (type {type(oc).__name__})")
print("  -> if reliability is a float ~0.97, the label 'reliability: 0.97' is confusing next to")
print("     'confidence 0.98'. Report should show it more clearly (e.g. as a % or with a band).")
