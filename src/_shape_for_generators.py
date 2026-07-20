r"""READ-ONLY. Dump the parity bundle + engine summary structure so BOTH report generators
(internal parity navy report + client quote) are built against REAL fields. Prints every key,
list shapes with row0 sample, and hunts specifically for the fields each report needs:
  - parity report: totals (engine/manual material+labour+unit), money-cell rows, BOM recon
    (matched/manual_only/ai_only), labour route rows, flag list, qty (engine vs manual)
  - client quote: unit price/sell, qty, order value, material, finish, OPERATION LIST
    (for 'what's included'), GA image/pdf path"""
import json, os, re

def dump(label, path, maxd=3):
    if not os.path.exists(path):
        print(f"\n{label}: NOT FOUND -> {path}"); return None
    J = json.load(open(path, encoding="utf-8"))
    print("\n"+"="*74); print(f"{label}"); print(path); print("="*74)
    def shape(o, d=0):
        pad="  "*d
        if d>maxd: return
        if isinstance(o,dict):
            for k,v in o.items():
                if isinstance(v,(dict,list)):
                    print(f"{pad}{k}: {type(v).__name__}[{len(v)}]")
                    if isinstance(v,list) and v and isinstance(v[0],dict):
                        print(f"{pad}  row0 keys: {list(v[0].keys())}")
                        for kk,vv in list(v[0].items())[:10]:
                            print(f"{pad}    {kk} = {str(vv)[:52]}")
                    elif isinstance(v,dict):
                        shape(v,d+1)
                else:
                    print(f"{pad}{k} = {str(v)[:72]}")
    shape(J); return J

B = dump("PARITY BUNDLE", r"C:\ClaudeVision\output\csv\1282_parity_bundle.json")
S = dump("ENGINE SUMMARY", r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json", maxd=2)

# field hunt across BOTH
for label, J in (("BUNDLE", B), ("SUMMARY", S)):
    if not J: continue
    print("\n"+"="*74); print(f"FIELD HUNT :: {label}"); print("="*74)
    flat = json.dumps(J)
    groups = {
      "totals/price": ["unit_cost","sell","material_cost","labour_cost","total","order_value","margin","rebate"],
      "qty":          ["quantity","qty"],
      "recon":        ["matched","manual_only","ai_only","reconcil","match_rate"],
      "money_cells":  ["money_cell","json_numeric","workbook_cached","status"],
      "labour_route": ["labour_route","operation","op_code","hours","route"],
      "material/fin": ["material","finish","coating","powder"],
      "ops_included": ["operation","op_name","process","route"],
      "ga_image":     ["ga","image","png","pdf","render","preview","drawing_path","source_file"],
      "flags":        ["flag","warning","assumption"],
    }
    for g, toks in groups.items():
        hits=set()
        for t in toks:
            for m in re.findall(rf'"([^"]*{t}[^"]*)"\s*:', flat, re.I):
                hits.add(m)
        if hits:
            print(f"  {g:<14}: {sorted(hits)[:10]}")
