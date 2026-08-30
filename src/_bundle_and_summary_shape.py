r"""READ-ONLY. Dump BOTH the parity bundle AND the engine summary JSON structure, so the two
report generators (internal parity + client quotation) are built against REAL fields. For the
CLIENT quote we specifically need: unit cost / sell price / margin / rebate, material+finish,
operation list (for 'what's included'), qty, order value, and any GA image path/reference."""
import json, os

def dump(label, path, maxd=3):
    if not os.path.exists(path):
        print(f"\n{label}: NOT FOUND at {path}"); return None
    J = json.load(open(path, encoding="utf-8"))
    print("\n"+"="*72); print(f"{label}: {path}"); print("="*72)
    def shape(o, depth=0):
        pad="  "*depth
        if depth>maxd: return
        if isinstance(o, dict):
            for k,v in o.items():
                if isinstance(v,(dict,list)):
                    n=len(v); print(f"{pad}{k}: {type(v).__name__}[{n}]")
                    if isinstance(v,list) and v and isinstance(v[0],dict):
                        print(f"{pad}  row0 keys: {list(v[0].keys())}")
                        for kk,vv in list(v[0].items())[:8]:
                            print(f"{pad}    {kk} = {str(vv)[:55]}")
                    elif isinstance(v,dict):
                        shape(v,depth+1)
                else:
                    print(f"{pad}{k} = {str(v)[:70]}")
    shape(J)
    return J

# 1) parity bundle
dump("PARITY BUNDLE", r"C:\ClaudeVision\output\csv\1282_parity_bundle.json")

# 2) engine summary JSON — where the estimate_summary + priced parts + finishes live
J = dump("ENGINE SUMMARY", r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json", maxd=2)

# 3) targeted: hunt for client-quote fields in the summary
if J:
    print("\n"+"="*72); print("CLIENT-QUOTE FIELD HUNT (summary)"); print("="*72)
    import re
    flat = json.dumps(J)
    for key in ("unit_cost","sell_price","sell","margin","rebate","total_unit","order_value",
                "material","finish","operation","op_code","route","quantity","qty",
                "ga_image","drawing_image","render","png","image_path","preview"):
        # find keys containing this token
        hits = re.findall(rf'"([^"]*{key}[^"]*)"\s*:', flat, re.I)
        uniq = sorted(set(hits))[:6]
        if uniq: print(f"  ~{key:<14}: {uniq}")

    # estimate_summary block if present
    es = J.get("estimate_summary") or {}
    if es:
        print("\n  estimate_summary keys:", list(es.keys()))
        for k in ("unit_cost","sell_price","material_cost","labour_cost","total","quantity","margin","rebate"):
            if k in es: print(f"    {k} = {es[k]}")
