#!/usr/bin/env python3
r"""
_apply_desc_none_fix.py

Fixes the "12439-01-13  None" leak in the workbook material sections. The description cell is
built as:
    desc = f"{pe.get('part_number','')}  {pe.get('description','')}"
The ',''' default only applies when the KEY is absent. Here the 'description' key EXISTS with
value None, so f-string formats the literal "None" into the cell. A part with a part number but
no description text shows "<pn>  None".

This appears at BOTH material-section sites (Sheet Steel ~460 and Other Sheet Material ~501).

FIX: a small helper _part_desc(pe) that:
  - uses the real description text when present and non-empty
  - otherwise builds a meaningful fallback from material + blank dimensions
    e.g. "12439-01-13  305 x 170 x 1.2mm Acrylic"
  - never prints "None"

Both call sites switch to the helper. General — every board/steel/acrylic part with an empty
description benefits, on every job.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_desc_none_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\xlsx_output.py"
SENTINEL = "_part_desc_nonefix"


def sub(src, old, new, label, count=1):
    n = src.count(old)
    if n != count:
        sys.exit(f"ABORT [{label}]: expected {count} match(es), found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label} ({n} site(s))")
    return src.replace(old, new)


# The helper. Inserted just before the first use. Defined at module scope via a marker anchor:
# we hang it off the SECTION 1 header comment which is stable.
HELPER_ANCHOR = '''    # ── SECTION 1: Standard Materials (BOM) ───────────────────────────────'''

HELPER_NEW = '''    def _part_desc(pe):  # _part_desc_nonefix (2026-07-15)
        """Description cell text: real description if present, else a material+dimension
        fallback. Never prints the literal 'None' (the old f-string leaked None when the
        'description' key existed but was empty)."""
        _pn = str(pe.get("part_number") or "").strip()
        _d = pe.get("description")
        _d = str(_d).strip() if _d is not None else ""
        if _d and _d.lower() != "none":
            return (_pn + "  " + _d).strip()
        # fallback: material + blank dimensions
        _me = pe.get("material_estimate") or {}
        _ng = pe.get("normalized_geometry") or {}
        _mat = str(pe.get("normalized_material") or _me.get("material") or "").replace("_", " ").strip().title()
        _l = _me.get("blank_length_mm") or _ng.get("blank_length_mm")
        _w = _me.get("blank_width_mm") or _ng.get("blank_width_mm")
        _t = pe.get("normalized_thickness_mm") or _me.get("thickness_mm")
        _dims = ""
        try:
            if _l and _w and _t:
                _dims = "%g x %g x %gmm" % (float(_l), float(_w), float(_t))
            elif _l and _w:
                _dims = "%g x %g" % (float(_l), float(_w))
        except (TypeError, ValueError):
            _dims = ""
        _tail = " ".join(x for x in (_dims, _mat) if x).strip()
        return (_pn + "  " + _tail).strip() if _tail else _pn

    # ── SECTION 1: Standard Materials (BOM) ───────────────────────────────'''


OLD_DESC = '''desc = f"{pe.get('part_number','')}  {pe.get('description','')}"'''
NEW_DESC = '''desc = _part_desc(pe)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    # 1) insert the helper before SECTION 1
    src = sub(src, HELPER_ANCHOR, HELPER_NEW, "insert _part_desc helper")
    # 2) replace BOTH desc-building sites (Sheet Steel + Other Sheet Material)
    src = sub(src, OLD_DESC, NEW_DESC, "swap desc sites to _part_desc", count=2)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_descnone_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected:
    - Other Sheet Material description: '12439-01-13  305 x 170 x 1.2mm Acrylic'
      (or similar), NOT '12439-01-13  None'.
    - All numbers UNCHANGED (this only touches the description text).

Steel jobs (1282): descriptions with real text are untouched (helper returns them
as-is); any steel part with an empty description now shows material+dims instead of
'None'. Numbers unchanged.
""")


if __name__ == "__main__":
    main()
