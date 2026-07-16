#!/usr/bin/env python3
r"""
_probe_board_inheritance.py  —  READ-ONLY.

Display boards (VINYL-668X200 etc.) show normalized_material=MILD_STEEL, inherited from
the assembly's document-level material (material_inherited_from='document_level'). Their
OWN detail pages (23,24,25) clearly say "MATERIAL: DISPLAY BOARD". They are COSTED
correctly as display boards (£3.34 etc.), but the material LABEL is wrong.

This probe establishes, before any fix:
  1. For each display-board part: normalized_material, material_inherited_from, and any
     raw material text it carries from its OWN page (does it have 'DISPLAY BOARD'
     anywhere, or did inheritance overwrite everything?).
  2. Whether the correct material ('DISPLAY BOARD') is recoverable — from the raw
     materials list, description, or a per-part field — so a fix can use it.
  3. The pattern: which parts inherit document_level material, so a fix targeting
     bought-in boards doesn't disturb legitimate inheritance on real steel parts.

Goal: decide the fix — either (a) don't inherit doc-level material onto a part whose
own description/BOM says DISPLAY BOARD / vinyl / printed, or (b) set display-board
parts' material from their board recogniser, not the assembly default.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_board_inheritance.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json


def find_parts(data):
    best = {}
    def walk(o):
        if isinstance(o, dict):
            pn = o.get("part_number")
            if pn is not None:
                pn = str(pn)
                if pn not in best or len(o.keys()) > len(best[pn].keys()):
                    best[pn] = o
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    return best


def main(jpath):
    parts = find_parts(json.load(open(jpath, "r", encoding="utf-8")))

    print("=" * 96)
    print("BOARD MATERIAL INHERITANCE PROBE (read-only)")
    print("=" * 96)

    # display-board / vinyl parts (description or code says board/vinyl/display)
    def is_board_part(pn, pe):
        blob = (pn + " " + str(pe.get("description") or "")).upper()
        return ("VINYL" in blob or "DISPLAY BOARD" in blob or "GRAPHIC" in blob
                or str(pe.get("cost_source") or "").startswith("display_board"))

    print("\n[1] Board/graphic parts — material vs inheritance:")
    print(f"{'part':<20}{'norm_material':<16}{'inherited_from':<18}{'cost_source'}")
    print("-" * 96)
    board_pns = []
    for pn, pe in sorted(parts.items()):
        if is_board_part(pn, pe):
            board_pns.append(pn)
            nm = str(pe.get("normalized_material"))
            inh = str(pe.get("material_inherited_from"))
            cs = str(pe.get("cost_source") or pe.get("source") or "")
            print(f"{pn[:19]:<20}{nm:<16}{inh:<18}{cs}")

    # 2. can we recover 'DISPLAY BOARD'? show raw material fields for one board part
    print("\n[2] Recoverable correct material? (raw fields on a board part):")
    if board_pns:
        pe = parts[board_pns[0]]
        print(f"  sample: {board_pns[0]}")
        print(f"    description        = {pe.get('description')!r}")
        print(f"    materials (raw)    = {pe.get('materials')!r}")
        print(f"    normalized_material= {pe.get('normalized_material')!r}")
        print(f"    material_inherited_from = {pe.get('material_inherited_from')!r}")
        print(f"    cost_source        = {pe.get('cost_source')!r}")
        print(f"    page_roles         = {pe.get('page_roles')!r}")
        # any field mentioning 'board' or 'display' or 'vinyl'?
        import json as _j
        blob = _j.dumps(pe).upper()
        for kw in ("DISPLAY BOARD", "VINYL", "PRINTED"):
            print(f"    contains {kw!r}? {kw in blob}")

    # 3. which parts inherit document_level — full pattern (so fix doesn't hit real steel)
    print("\n[3] ALL parts with material_inherited_from='document_level':")
    for pn, pe in sorted(parts.items()):
        if str(pe.get("material_inherited_from")) == "document_level":
            print(f"  {pn:<18} norm_material={pe.get('normalized_material')!r} "
                  f"desc={str(pe.get('description'))[:30]!r} roles={pe.get('page_roles')}")

    print("\n" + "=" * 96)
    print("FIX DECISION:")
    print("  - if board parts carry 'DISPLAY BOARD' in raw materials/description, the fix")
    print("    can set their material from that instead of the inherited doc-level steel.")
    print("  - if ONLY bought-in/display parts inherit doc-level (real steel parts read")
    print("    their own title block), the fix can safely skip inheritance for bought-ins.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_board_inheritance.py <json>"); sys.exit(1)
    main(sys.argv[1])
