#!/usr/bin/env python3
"""
patch_wire_costing.py
Run from C:\\ClaudeVision\\src:
    python patch_wire_costing.py

Fixes four gaps that prevent wire-by-length parts (e.g. FOTM 05M, 09M, 14M, 16M)
from reaching the existing wire costing path in estimator.py:

  1. _is_section_or_wire_candidate — add wire_forming + DIA pattern trigger
  2. _infer_section_length_mm      — parse length from "Xmm DIA {length}" descriptions
  3. is_wire gate                  — add wire_forming op + DIA pattern checks
  4. Gauge extraction              — read diameter from "Xmm DIA" not sheet thickness

Does NOT affect flat-steel or MDF parts. 1282 regression gate is not required
(no wire_forming ops on clean steel peg bays).
"""
import pathlib, shutil, sys

src = pathlib.Path(__file__).parent


def patch(path: pathlib.Path, label: str, anchor: str, replacement: str) -> None:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found. Run from C:\\ClaudeVision\\src")
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if anchor not in text:
        print(f"  {label}: anchor not found — already patched or file changed. Skipping.")
        return
    if replacement in text:
        print(f"  {label}: already present. Skipping.")
        return
    shutil.copy(path, path.with_suffix(".py.bak"))
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    print(f"  {label}: PATCHED")


f = src / "estimator.py"

# ── Gap 1: _is_section_or_wire_candidate ─────────────────────────────────────
# Add wire-by-length detection: if the part has wire_forming op AND its
# description contains the "Xmm DIA" wire-spec pattern, treat it as a wire
# candidate even if no section keyword matches.
patch(
    f, "estimator — _is_section_or_wire_candidate wire_forming trigger",
    anchor='    return any(token in blob for token in tokens)\n\n\ndef _resolve_labour_rate',
    replacement=(
        '    if any(token in blob for token in tokens):\n'
        '        return True\n'
        '    # Wire-by-length: wire_forming op + diameter spec in description\n'
        '    # e.g. "LENGTH QTY 1 6.00mm DIA 1874.17" on FOTM wire parts\n'
        '    _ops_lower = [str(o).lower() for o in (part.get("operations") or [])]\n'
        '    if "wire_forming" in _ops_lower:\n'
        '        if re.search(r\'\\d+\\.?\\d*\\s*mm\\s+DIA\', str(part.get("description") or ""), re.IGNORECASE):\n'
        '            return True\n'
        '    return False\n'
        '\n'
        '\ndef _resolve_labour_rate'
    ),
)

# ── Gap 2: _infer_section_length_mm ──────────────────────────────────────────
# Parse wire length from descriptions like "6.00mm DIA 1874.17" where the
# number immediately after DIA is the wire length in mm.
patch(
    f, "estimator — _infer_section_length_mm DIA pattern",
    anchor=(
        '    dims = [_safe_float(v) for v in part.get("all_dimensions_mm", [])]\n'
        '    dims = [v for v in dims if v is not None and v > 0]\n'
        '    return max(dims) if dims else None'
    ),
    replacement=(
        '    dims = [_safe_float(v) for v in part.get("all_dimensions_mm", [])]\n'
        '    dims = [v for v in dims if v is not None and v > 0]\n'
        '    # Wire-by-length: "6.00mm DIA 1874.17" — number after DIA is the length\n'
        '    _dia_m = re.search(\n'
        '        r\'\\d+\\.?\\d*\\s*mm\\s+DIA\\s+(\\d+\\.?\\d+)\',\n'
        '        str(part.get("description") or ""), re.IGNORECASE,\n'
        '    )\n'
        '    if _dia_m:\n'
        '        _candidate = float(_dia_m.group(1))\n'
        '        if 10.0 <= _candidate <= 10000.0:  # sanity: 10 mm to 10 m\n'
        '            return _candidate\n'
        '    return max(dims) if dims else None'
    ),
)

# ── Gap 3: is_wire gate ────────────────────────────────────────────────────────
# Extend the is_wire check to also fire when:
#   a) the part has a wire_forming operation, or
#   b) the description contains the "Xmm DIA" wire-spec pattern
patch(
    f, "estimator — is_wire gate expansion",
    anchor=(
        '        is_wire = any(kw in desc_upper for kw in'
        ' ("WIRE MESH", "WELDED WIRE", "WIRE FORM", "WIREWORK", "WIRE "))'
    ),
    replacement=(
        '        _wire_part_ops = [str(_o).lower() for _o in (part.get("operations") or [])]\n'
        '        is_wire = (\n'
        '            any(kw in desc_upper for kw in\n'
        '                ("WIRE MESH", "WELDED WIRE", "WIRE FORM", "WIREWORK", "WIRE "))\n'
        '            or "wire_forming" in _wire_part_ops\n'
        '            or bool(re.search(r\'\\d+\\.?\\d*\\s*MM\\s+DIA\', desc_upper))\n'
        '        )'
    ),
)

# ── Gap 4: Wire gauge extraction ───────────────────────────────────────────────
# Extract wire diameter from "6.00mm DIA" in description rather than reading
# the sheet-steel thickness field (which is meaningless for wire parts).
patch(
    f, "estimator — wire gauge from DIA description",
    anchor='            gauge_mm = _safe_thickness_mm(part) or 3.0',
    replacement=(
        '            _gauge_match = re.search(\n'
        '                r\'(\\d+\\.?\\d*)\\s*mm\\s+DIA\',\n'
        '                str(part.get("description") or ""), re.IGNORECASE,\n'
        '            )\n'
        '            gauge_mm = float(_gauge_match.group(1)) if _gauge_match else (_safe_thickness_mm(part) or 3.0)'
    ),
)

print("\nDone. Run a FOTM estimate to verify wire parts now cost via the wire path:")
print('  python main.py --search-root "K:\\Estimating\\...\\FOTM Belly Basket" --folder-as-job')
print("\nExpect: parts 05M, 09M, 10M, 14M, 16M, 19M to show cost_method: workbook_wire_formula")
print("No 1282 regression gate required — clean steel peg bays have no wire_forming ops.")
