"""READ-ONLY. Answers: does the engine already capture the assembly hierarchy from the
GA pages, or not? Reads 1282's extracted data + dumps the relevant parsing code so we can
see the real logic (not guess). No drawings re-parsed, no Tim data.

Four questions:
  A. What do the GA/assembly pages actually contain? (the child BOM tables — page 10/11/20)
  B. Does ANY part currently carry a parent/child link, bom_tree, or assembly membership?
  C. WHERE is the 'assembly' page_role set, and does a parent link follow it?
  D. Dump the GA-parsing code (bom_tree / drawing_job_merge / file_scan) so we see the logic.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _ga_hierarchy_probe.py
Then: notepad C:\ClaudeVision\src\ga_probe_dump.txt   (code dumps go there, UTF-8)
"""
import json, io, re
from pathlib import Path

OUT = io.open(r"C:\ClaudeVision\src\ga_probe_dump.txt", "w", encoding="utf-8")
def w(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    OUT.write(line + "\n")

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))
parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []

w("=" * 78)
w("A. GA / assembly page content — do we have the child BOM tables?")
w("=" * 78)
# pages live in a few possible places; scan for anything with 'assembly' role + item/qty tables
pages = data.get("pages") or data.get("page_texts") or []
if pages:
    for pg in pages:
        role = str(pg.get("role") or pg.get("page_role") or "")
        txt = str(pg.get("text") or pg.get("content") or "")
        if "assembly" in role.lower() or re.search(r'ITEM\s+DWG|DWG\s*NO.*DESCRIPTION|PartNo\s+Description', txt, re.I):
            w(f"  [page role={role}] first 400 chars of BOM-ish text:")
            w("   ", txt[:400].replace("\n"," "))
            w("")
else:
    w("  (no 'pages' array in JSON — GA text may only be in the .txt output, not JSON)")

w("=" * 78)
w("B. Does ANY part carry parent/child/assembly-membership fields?")
w("=" * 78)
link_keys = set()
for p in parts:
    for k in p.keys():
        if any(t in k.lower() for t in ("parent","child","assembl","bom_tree","member","weldment","belongs","tree","group")):
            link_keys.add(k)
if link_keys:
    w(f"  Found possible linkage keys on parts: {sorted(link_keys)}")
    for p in parts[:40]:
        vals = {k: p.get(k) for k in link_keys if p.get(k) not in (None,"",[],{})}
        if vals:
            w(f"    {p.get('part_number'):14} {vals}")
else:
    w("  NO parent/child/assembly-membership keys on ANY part.")
    w("  -> hierarchy is NOT captured on the part records themselves.")

# Is there a top-level bom tree anywhere in the JSON?
w("\n  Top-level JSON keys containing tree/bom/assembly:")
for k in data.keys():
    if any(t in k.lower() for t in ("tree","bom","assembl","hierarch","weldment")):
        v = data[k]
        w(f"    '{k}': {type(v).__name__}  " + (f"(len {len(v)})" if hasattr(v,'__len__') else str(v)[:80]))

w("=" * 78)
w("C. Where is page_role 'assembly' set, and does a parent follow? (grep source)")
w("=" * 78)
SRC = Path(r"C:\ClaudeVision\src")
for fn in ("file_scan.py","drawing_job_merge.py","bom_tree.py","estimator.py","json_normaliser.py"):
    fp = SRC / fn
    if not fp.exists():
        w(f"  {fn}: NOT FOUND")
        continue
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = [(i+1,l) for i,l in enumerate(lines)
            if re.search(r"assembly|parent|weldment|bom_tree|child|page_role", l, re.I)]
    w(f"  --- {fn}: {len(hits)} relevant line(s) ---")
    for ln,l in hits[:25]:
        w(f"    {ln:5}: {l.strip()[:110]}")

w("=" * 78)
w("D. Full dump of bom_tree.py + drawing_job_merge.py GA-handling (to ga_probe_dump.txt)")
w("=" * 78)
for fn in ("bom_tree.py","drawing_job_merge.py"):
    fp = SRC / fn
    if fp.exists():
        w(f"\n########## {fn} (full) ##########")
        OUT.write("\n".join(fp.read_text(encoding='utf-8', errors='replace').splitlines()) + "\n")
    else:
        w(f"  {fn}: NOT FOUND")

OUT.close()
print("\n[done] Code dumps written to C:\\ClaudeVision\\src\\ga_probe_dump.txt — open & paste that.")
