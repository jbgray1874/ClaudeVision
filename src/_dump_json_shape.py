r"""READ-ONLY. My path guesses missed operations + header fields. Stop guessing — dump the REAL
structure so I map the client-quote generator to what's actually in the JSON.
Shows: top-level keys; estimate_summary keys; estimate_workbook_inputs keys; ONE full part record
(all keys + a sample of nested route/operation structure); and where a job number / customer /
title might live. No edits."""
import json
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))

def keys(d): return sorted(d.keys()) if isinstance(d,dict) else f"<{type(d).__name__}>"

print("="*66); print("TOP-LEVEL keys"); print("="*66)
print(" ", keys(S))

es=S.get("estimate_summary",{})
print("\n"+"="*66); print("estimate_summary keys"); print("="*66)
print(" ", keys(es))

ewi=es.get("estimate_workbook_inputs",{})
print("\n"+"="*66); print("estimate_workbook_inputs keys"); print("="*66)
print(" ", keys(ewi))
# dump its values too (small)
for k,v in (ewi.items() if isinstance(ewi,dict) else []):
    if not isinstance(v,(dict,list)):
        print(f"    {k} = {v}")

# find the parts list (whatever it's called)
print("\n"+"="*66); print("part-list container (find the right key + one full record)"); print("="*66)
part_key=None
for k in ("part_estimates","parts","part_records","estimates","line_items","bom"):
    v=es.get(k) or S.get(k)
    if isinstance(v,list) and v:
        part_key=k; parts=v; break
if part_key:
    print(f"  parts under: {part_key}  (count={len(parts)})")
    p0=parts[0]
    print(f"  ONE PART record keys:\n    {keys(p0)}")
    print("  scalar values on that part:")
    for k,v in p0.items():
        if not isinstance(v,(dict,list)):
            print(f"    {k} = {v}")
    # nested dicts on the part — show their keys (route/process/operation lives here)
    print("  nested containers on that part:")
    for k,v in p0.items():
        if isinstance(v,dict):
            print(f"    {k}: {keys(v)}")
        elif isinstance(v,list) and v:
            print(f"    {k}: list[{len(v)}], first item keys = {keys(v[0]) if isinstance(v[0],dict) else type(v[0]).__name__}")
else:
    print("  NO part list found under common keys — top-level had:", keys(S))

# hunt for job number / customer / title anywhere shallow
print("\n"+"="*66); print("hunt for job_number / customer / title / rev (shallow scan)"); print("="*66)
def scan(d, prefix="", depth=0):
    if depth>2 or not isinstance(d,dict): return
    for k,v in d.items():
        kl=k.lower()
        if any(t in kl for t in ("job","customer","client","title","revision","rev","enquiry","brand","product","description")):
            if not isinstance(v,(dict,list)):
                print(f"    {prefix}{k} = {v}")
        if isinstance(v,dict):
            scan(v, prefix+k+".", depth+1)
scan(S)
