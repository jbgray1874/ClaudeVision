import json, glob, os
f = max(glob.glob(r"C:\ClaudeVision\output\json\*Milwaukee*.json"), key=os.path.getmtime)
d = json.load(open(f, encoding="utf-8"))
print("FILE:", os.path.basename(f))

print("\n--- loom parts AFTER reconciliation ---")
parts = d.get("manufacturing_writeup", {}).get("parts") or []
for p in parts:
    desc = str(p.get("description", "")).upper()
    if "LOOM" in desc or "ELECTRIC" in desc or p.get("part_number") in ("BI-50CMLOOM", "ELECTRICS 50CM"):
        print(repr(p.get("part_number")), "| src=", repr(p.get("source")),
              "| roles=", p.get("page_roles"), "| flags=", p.get("review_flags"))

print("\n--- bom_rows qty for the x2 parts ---")
rows = d.get("document_analysis", {}).get("bom_rows", [])
want = ("1448-01", "3886-01", "1448-GA", "3886-GA", "1448-02", "3886-02", "3886-03")
for r in rows:
    if r.get("part_number") in want:
        print(f'{r.get("part_number"):<14} qty={r.get("quantity")} parent={r.get("bom_parent")} src={r.get("bom_source")}')
