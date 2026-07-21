r"""READ-ONLY. Map the client-quote template fields to summary-JSON sources, so the generator
populates the we.are.sdi layout from any job. Check what the 1282 summary JSON carries for:
  - product/job name, job number, rev, quantity, date
  - unit price (the REAL Excel-computed one we just fixed), order value
  - material, finish, colour (for Specification)
  - operations (for 'What's included' — need plain-language mapping)
  - GA image (primary PDF / page image path to embed)
  - customer (for 'Prepared for' — is customer in the JSON?)
No edits — establishing the field map before building."""
import json
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
es=S.get("estimate_summary",{})

def show(label, *paths):
    for p in paths:
        cur=S
        for k in p.split("."):
            cur=cur.get(k) if isinstance(cur,dict) else None
            if cur is None: break
        if cur is not None and not isinstance(cur,(dict,list)):
            print(f"  {label:<22} <- {p} = {cur}"); return
        if isinstance(cur,list) and cur and not isinstance(cur[0],(dict,list)):
            print(f"  {label:<22} <- {p} = {cur[:4]}"); return
    print(f"  {label:<22} <- NOT FOUND ({', '.join(paths)})")

print("="*66); print("HEADER / BAND fields"); print("="*66)
show("job_number","estimate_summary.job_number","job_number","estimate_summary.estimate_workbook_inputs.job_number")
show("product/desc name","estimate_summary.job_title","job_title","estimate_summary.description","description")
show("rev","estimate_summary.revision","revision","estimate_summary.rev")
show("quantity","estimate_summary.estimate_workbook_inputs.assumed_job_quantity","order_quantity")
show("customer","estimate_summary.customer","customer","estimate_summary.customer_name","estimate_summary.estimate_workbook_inputs.customer")
show("date","estimate_summary.scan_date","scan_date")

print("\n"+"="*66); print("PRICE fields (the fixed Excel-computed numbers)"); print("="*66)
wep=es.get("workbook_equivalent_pricing",{})
print("  unit_cost (WEP m105) =", wep.get("m105_total_unit_cost_gbp"))
print("  document_total       =", es.get("document_total_estimated_cost_gbp") or S.get("document_total_estimated_cost_gbp"))
show("order_value?","estimate_summary.order_value_gbp","order_value_gbp")

print("\n"+"="*66); print("SPECIFICATION fields (material / finish / colour)"); print("="*66)
# aggregate materials + finishes across parts
parts=es.get("part_estimates") or []
mats=sorted({str(p.get("normalized_material") or p.get("material") or "").strip() for p in parts if p.get("normalized_material") or p.get("material")})
fins=sorted({str(p.get("normalized_finish") or p.get("finish") or "").strip() for p in parts if p.get("normalized_finish") or p.get("finish")})
cols=sorted({str(p.get("colour") or p.get("color") or p.get("ral") or "").strip() for p in parts if p.get("colour") or p.get("color") or p.get("ral")})
print("  materials present:", mats[:6])
print("  finishes present :", fins[:6])
print("  colours present  :", cols[:6])

print("\n"+"="*66); print("OPERATIONS (for 'What's included' plain-language)"); print("="*66)
ops=sorted({str(p.get("canonical_operation") or "").strip() for p in parts for _ in [0]} | 
           {op for p in parts for op in (p.get("operations") or [])})
# better: pull from process routes
route_ops=set()
for p in parts:
    for seg in (p.get("process_estimate",{}).get("segments") or p.get("route") or []):
        if isinstance(seg,dict):
            route_ops.add(str(seg.get("operation") or seg.get("canonical_operation") or "").strip())
print("  distinct operations (routes):", sorted(o for o in route_ops if o)[:15])

print("\n"+"="*66); print("GA IMAGE (to embed)"); print("="*66)
show("primary_pdf","estimate_summary.primary_pdf.path","primary_pdf.path","estimate_summary.primary_pdf_path")
show("page_images_dir","estimate_summary.page_images_dir","page_images_dir")
# any GA page?
for pg in (S.get("pages") or [])[:20]:
    role=(pg.get("page_role",{}) or {}).get("primary_role","")
    if "ga" in str(role).lower() or "general" in str(role).lower():
        print(f"  GA page found: page {pg.get('page_number')} role={role} img={pg.get('page_image_path') or pg.get('image_path')}")
        break
