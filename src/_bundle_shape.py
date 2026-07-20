r"""READ-ONLY. Dump the FULL structure of the parity bundle so the generic report generator
is built against the REAL fields present, not assumed ones. Shows every top-level key, the
shape of each list/dict, and sample rows — so we know exactly what data is auto-available for
any job's report (totals, money cells, reconciliation, labour route, flags)."""
import json, os

b = r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
if not os.path.exists(b):
    b = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"
J = json.load(open(b, encoding="utf-8"))

def shape(o, depth=0, maxd=3):
    pad = "  "*depth
    if depth > maxd:
        print(f"{pad}..."); return
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{pad}{k}: {type(v).__name__}[{n}]")
                if isinstance(v, list) and v:
                    print(f"{pad}  (sample row keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]).__name__})")
                    if isinstance(v[0], dict):
                        # show first row values
                        for kk, vv in list(v[0].items())[:12]:
                            print(f"{pad}    {kk} = {str(vv)[:60]}")
                elif isinstance(v, dict):
                    shape(v, depth+1, maxd)
            else:
                print(f"{pad}{k} = {str(v)[:70]}")
    elif isinstance(o, list):
        print(f"{pad}list[{len(o)}]")

print("="*70)
print("FULL BUNDLE STRUCTURE")
print("="*70)
shape(J)
