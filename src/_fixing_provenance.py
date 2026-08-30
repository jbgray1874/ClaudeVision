"""
Read-only. Shows exactly how the FIXING bought-in stubs are represented in the run JSON:
their source_pdf (if any), the raw quantity, and any effective_qty markers.
This tells us WHICH stage sets qty=2 and whether they ever carried a source drawing
that bom_tree could have used. No writes.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _fixing_provenance.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))

def walk(o, path=""):
    """Yield (path, dict) for every dict that looks like a part/row with a part_number."""
    if isinstance(o, dict):
        if any(k in o for k in ("part_number", "part_no", "code")):
            yield path, o
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")

TARGETS = {"FIXING5", "FIXING236", "FIXING125", "VINYL76"}

seen = set()
for path, d in walk(data):
    pn = str(d.get("part_number") or d.get("part_no") or d.get("code") or "").replace(" ", "").upper()
    if pn in TARGETS:
        key = (pn, path.split(".")[1] if "." in path else path)
        # print each distinct container the code appears in
        src = d.get("source_pdf") or d.get("source") or d.get("drawing") or "(none)"
        qty = d.get("quantity", d.get("qty", "?"))
        eff = d.get("effective_qty_source", "")
        roles = d.get("page_roles") or d.get("roles") or ""
        print(f"{pn:<12} @ {path[:60]:<60} qty={qty} src={str(src)[:40]} "
              f"roles={roles} eff={eff}")

print("\nInterpretation:")
print(" - If src=(none)/empty for the FIXINGs, they never had a source_pdf -> bom_tree")
print("   (which groups by source_pdf) could never see them. Fix belongs in the")
print("   bought-in recogniser / estimator, not bom_tree.")
print(" - Compare where in the JSON tree they live: a top-level bought_in list vs")
print("   inside bom_rows tells us which stage owns the quantity.")
