# -*- coding: utf-8 -*-
r"""READ-ONLY. Does the part record for the tube legs genuinely carry the
profile/length text ('30 x 60 x 1.50mm TUBE 1125')? We must confirm the data
is really there before building extraction — no hard-coding.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _tube_text_probe.py
"""
import json
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

# find the part records
parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or data.get("parts") or []
targets = ("1448-01", "3886-01")

for pe in parts:
    pn = str(pe.get("part_number") or "")
    if not any(pn.startswith(t) for t in targets):
        continue
    print(f"\n===== {pn}  ({pe.get('description')}) =====")
    # dump every field that could carry the profile/length text
    for key in ("description", "process_notes", "all_dimensions_mm", "overall_length_mm",
                "length_mm", "section_stock", "raw_text", "source_text", "page_text",
                "bom_description", "source_pages", "pages", "notes"):
        if key in pe:
            v = pe[key]
            s = str(v)
            print(f"  {key}: {s[:160]}")
    # search ALL string values in the record for '30' '60' '1.5' 'TUBE' '1125' '1072'
    blob = json.dumps(pe)
    print("  --- presence of genuine profile tokens in the part record JSON ---")
    for tok in ("TUBE", "30 x 60", "30 X 60", "1.50mm", "1.5mm", "1125", "1072", "x 60 x"):
        print(f"     '{tok}' present: {tok.upper() in blob.upper()}")

# also check raw page text in the scan (page 21 / page 4) — does the pipeline still hold it?
print("\n\n===== Raw page text availability (pages 4 and 21) =====")
def walk_pages(d):
    out=[]
    if isinstance(d, dict):
        if any(k in d for k in ("region_text","pdfplumber_text","normalized_text","text_preview","raw_text")):
            out.append(d)
        for v in d.values(): out += walk_pages(v)
    elif isinstance(d, list):
        for it in d: out += walk_pages(it)
    return out
pages = walk_pages(data)
hits = 0
for p in pages:
    txt = " ".join(str(p.get(k,"")) for k in ("region_text","pdfplumber_text","normalized_text","text_preview","raw_text"))
    if "TUBE" in txt.upper() and ("1125" in txt or "30 X 60" in txt.upper() or "30 x 60" in txt):
        hits += 1
        idx = txt.upper().find("TUBE")
        print(f"  FOUND tube text in a page record: ...{txt[max(0,idx-40):idx+30]}...")
        if hits >= 3: break
if hits == 0:
    print("  No page record in the JSON contains 'TUBE ... 1125' — page text may not be retained in summary JSON.")
    print("  (That doesn't mean it's unavailable in the pipeline — just not in this output file.)")
