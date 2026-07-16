#!/usr/bin/env python3
r"""
_probe_material_provenance.py  —  READ-ONLY.

Material-labelling bug on 12532: drawings clearly state MATERIAL in the title block
(MILD STEEL [CR4], DISPLAY BOARD, HIGH IMPACT ACRYLIC), but the engine outputs:
  - steel parts (02-02M etc.)  -> "Card"           (WRONG; drawing says MILD STEEL [CR4])
  - display boards (VINYL-*)   -> "MILD STEEL"      (WRONG; drawing says DISPLAY BOARD)
  - acrylic riser (03-04A)     -> "HIGH IMPACT ACRYLIC"  (CORRECT — reads title block!)

The acrylic being RIGHT proves the title-block reader CAN work. So something overrides
steel with "Card" and stamps a MILD STEEL default on bought-ins. There are three
possible sources (deterministic parser / LLM / original parsing). This probe dumps
EVERY material-related field and any 'source'/'provenance' marker for representative
parts, so we can see which stage set the value and whether a correct read was
overwritten.

Compares:
  02-02M  (steel, wrong -> Card)
  VINYL-668X200 (board, wrong -> Mild Steel default)
  03-04A  (acrylic, RIGHT -> High Impact Acrylic)   <- the control that works

Dumps for each: normalized_material, material_estimate.material, any raw material text,
material_source / provenance / confidence, and searches the whole part dict for keys
containing 'material', 'mat', 'source', 'llm', 'grok', 'parser', 'detected'.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_material_provenance.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json


def find_part(data, pn):
    """Return the most-hydrated record for a part number, from anywhere in the tree."""
    best = None
    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            if str(o.get("part_number")) == pn:
                if best is None or len(o.keys()) > len(best.keys()):
                    best = o
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    return best


def mat_keys(o, path="pe"):
    """Find every key path mentioning material / source / provenance / detected."""
    hits = []
    NEEDLES = ("material", "mat_", "_mat", "source", "provenance", "detected",
               "llm", "grok", "parser", "normalized", "raw_material", "stock")
    if isinstance(o, dict):
        for k, v in o.items():
            kl = k.lower()
            if any(n in kl for n in NEEDLES):
                disp = v if not isinstance(v, (dict, list)) else f"<{type(v).__name__} len={len(v)}>"
                hits.append((f"{path}.{k}", disp))
            hits += mat_keys(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]):
            hits += mat_keys(v, f"{path}[{i}]")
    return hits


def dump(data, pn, label):
    pe = find_part(data, pn)
    print(f"\n{'='*80}\n{label}: {pn}")
    if not pe:
        print("  NOT FOUND"); return
    print(f"  description        : {pe.get('description')!r}")
    print(f"  normalized_material: {pe.get('normalized_material')!r}")
    print(f"  materials(list)    : {pe.get('materials')!r}")
    me = pe.get("material_estimate") or {}
    print(f"  material_estimate.material: {me.get('material')!r}")
    print(f"  material_estimate.stock_form: {me.get('stock_form')!r}")
    print(f"  page_roles         : {pe.get('page_roles')!r}")
    print("  -- all material/source-related fields --")
    for p, v in mat_keys(pe):
        print(f"     {p} = {v!r}")


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    print("MATERIAL PROVENANCE PROBE — why steel=Card, board=MildSteel, acrylic=correct")
    dump(data, "12532-02-02M", "STEEL (wrong: Card)")
    dump(data, "VINYL-668X200", "BOARD (wrong: Mild Steel default)")
    dump(data, "12532-03-04A", "ACRYLIC (CORRECT — the control)")
    print("\n" + "="*80)
    print("READ: compare the acrylic (correct) against steel (wrong). If the acrylic has")
    print("a material_source='title_block' and the steel has material_source='llm'/'default'")
    print("or a raw title-block value that got overwritten, that names the culprit stage.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_material_provenance.py <json>"); sys.exit(1)
    main(sys.argv[1])
