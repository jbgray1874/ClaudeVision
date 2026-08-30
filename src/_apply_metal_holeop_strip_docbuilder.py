"""FULL FIX for the metal hole_machining/drilling op (the extractor guard alone was
insufficient — the op also arrives via the DXF/normalisation path). This strips
hole_machining + drilling from METAL parts in document_builder.py, where a part's ops
are finalised & cleaned per-material.

Mirrors the EXISTING 'Fix C' non-metal op-strip (lines ~988-1006): filter the ops set,
then re-run _interpret_part to recompute routing/costs. Here: METAL parts only, strip
ONLY hole_machining + drilling (metal holes are laser-cut). Acrylic/plastic keep drilling.

WHY metal-only + these two ops:
  - Tim's sheets have NO metal hole op (only "Drill (Acrylic)").
  - 1282 (all metal) already carries no hole ops -> will stay byte-identical.
  - 1298 (MILD STEEL) currently gets hole_machining -> GUIL £0.29 + "not in OP_NAME_MAP".

SAFE: exact-string match-or-refuse. Inserts a new block right AFTER the non-metal Fix C
block, anchored on that block's distinctive closing lines. If the anchor isn't found
verbatim in live src, it refuses and tells you to dump the live block.

BEFORE APPLYING, confirm the anchor exists in live src:
  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "Fix C: clean fabrication ops from non-metal" -Context 0,20

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_metal_holeop_strip_docbuilder.py

AFTER: re-run 1282 (expect byte-identical / same total) AND 1298 (expect NO hole_machining,
NO drilling, NO GUIL line; total ~£3.08; the "not in OP_NAME_MAP" warning gone).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\document_builder.py")

# Anchor: the END of the non-metal Fix C ops-strip block. We match its distinctive
# lines and re-insert them PLUS our new metal block right after. Keep whitespace exact.
ANCHOR = '''        if _is_non_metal_mat and not inherited_steel:
            _fab_ops = {
                "laser_cutting",
                "folding",
                "welding",
                "hole_machining",
                "tapping",
                "countersinking",
                "dress_welds",
                "powder_coating",
                "diamond_polish",
                "robomac",
                "roll",
                "guillotine",
            }
            _kept = [op for op in (part.get("textual_operations") or []) if op not in _fab_ops]
            if _kept != part.get("textual_operations", []):
                part["textual_operations"] = _kept
                _interpret_part(part)'''

METAL_BLOCK = '''

        # Fix D: METAL parts do not get a separate hole/drill op — metal holes are
        # laser-cut (they fold into the laser profile). Matches shop practice, Tim's
        # sheets (no metal hole op; only "Drill (Acrylic)"), and job 1282 (all metal,
        # no hole ops). The extractor guard alone is insufficient because hole_machining
        # also arrives via the DXF/normalisation path, so strip it here at finalisation.
        # ACRYLIC/plastic keep drilling (handled by the non-metal branch above).
        _is_metal_mat = any(
            kw in mat_upper_joined
            for kw in ("MILD STEEL", "STEEL", "CR4", "ZINTEC", "GALVAN",
                       "ALUMIN", "STAINLESS", "S355", "SPCC", "MS")
        )
        if (_is_metal_mat or inherited_steel) and not _is_non_metal_mat:
            _metal_hole_ops = {"hole_machining", "drilling"}
            _kept_m = [op for op in (part.get("textual_operations") or []) if op not in _metal_hole_ops]
            if _kept_m != part.get("textual_operations", []):
                part["textual_operations"] = _kept_m
                _interpret_part(part)'''

src = TARGET.read_text(encoding="utf-8")

if "Fix D: METAL parts do not get a separate hole/drill op" in src:
    print("ALREADY APPLIED — Fix D metal hole-op strip already present.")
    raise SystemExit(0)

if ANCHOR not in src:
    print("NOT APPLIED — the non-metal Fix C block anchor was not found verbatim in live src.")
    print("Live document_builder.py differs from the snapshot. Dump the block and paste back:")
    print(r'  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "_is_non_metal_mat and not inherited_steel" -Context 0,22')
    raise SystemExit(1)

if src.count(ANCHOR) > 1:
    print(f"NOT APPLIED — anchor appears {src.count(ANCHOR)} times, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(ANCHOR, ANCHOR + METAL_BLOCK), encoding="utf-8")
print("APPLIED — Fix D: metal parts now strip hole_machining + drilling at finalisation.")
print("Fingerprint: Select-String document_builder.py -Pattern 'Fix D: METAL parts'")
print("Next: re-run 1282 (expect same total ~£195-204) AND 1298 (expect NO hole_machining/")
print("drilling/GUIL line; total ~£3.08; 'not in OP_NAME_MAP' warning gone).")
