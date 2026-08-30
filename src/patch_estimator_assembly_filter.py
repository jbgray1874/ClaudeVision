#!/usr/bin/env python3
r"""
patch_estimator_assembly_filter.py
-----------------------------------
Adds the assembly roll-up / GA-artifact suppression to estimator.py.

What it does (and ONLY this):
  1. Inserts two helper functions + a regex (_classify_assembly_rollup et al.).
  2. Inserts a suppression block in estimate_part() so that any record with NO flat
     geometry of its own that is named as an assembly (..WA / ASM / ASSEMBLY) or carries
     a child BOM:
        - has its sheet/board MATERIAL zeroed (its children already carry it),
        - has geometry-derived fab labour stripped (laser/CNC/fold/punch/drill),
        - keeps genuine join work (weld/glue/assemble/handle/powder);
     and blank-description GA / title-block fragments are excluded from costing entirely.
  3. Excludes those roll-ups from the credibility (DXF-coverage) denominator.

It is anchored on stable strings UNRELATED to the wire-pricing fix, so it does NOT touch
lines 559/1206 or anything else in your live file. Idempotent (re-running is a no-op),
all-or-nothing (aborts cleanly if an anchor doesn't match), preserves your file's existing
line endings (CRLF), writes estimator.py.bak, and compile-checks the result.

Usage (from C:\ClaudeVision\src, in your venv):
    python patch_estimator_assembly_filter.py
or:
    python patch_estimator_assembly_filter.py path\to\estimator.py
"""
import sys, os, py_compile, json

PAIRS = json.loads(r"""[
[
"helpers",
"def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:",
"_ASSEMBLY_TOKEN_RE = re.compile(\n    r\"\\b(WA|ASM|ASSY|ASSEMBLY|WELDMENT|SUB-?ASSY|SUB ASSY)\\b\", re.IGNORECASE\n)\n\n\ndef _part_carries_sub_bom(part: Dict[str, Any]) -> bool:\n    \"\"\"True if the part's notes/operations carry a child Bill of Materials table —\n    a strong signal the record is an assembly drawing, not a single make-part.\"\"\"\n    blob = \" \".join(str(x) for x in (part.get(\"process_notes\") or []))\n    blob += \" \" + \" \".join(str(x) for x in (part.get(\"textual_operations\") or []))\n    u = blob.upper()\n    return (\"ITEM\" in u and \"DWG\" in u) or (\"DESCRIPTION QTY\" in u)\n\n\ndef _classify_assembly_rollup(part: Dict[str, Any]) -> Optional[str]:\n    \"\"\"Identify a record that must NOT carry sheet/board material or geometry-derived\n    fab labour because it is a roll-up of parts already costed individually (or a GA /\n    title-block artifact).  GEOMETRY-GUARDED: any part with its own DXF flat pattern is a\n    real make-part and is never suppressed — so a genuine one-piece part literally named\n    \"...ASSEMBLY\" that has a flat pattern is unaffected.\n\n    Returns:\n      'assembly_rollup' — named ...WA/ASM/ASSEMBLY or carrying a sub-BOM, with no own geometry\n      'ga_artifact'     — blank-description record with no geometry (GA / rev-table fragment)\n      None              — a real make-part (leaf), leave untouched\n    \"\"\"\n    if part.get(\"dxf_augmented\") or \"dxf\" in str(part.get(\"geometry_source\") or \"\").lower():\n        return None  # has its own flat geometry -> real make-part, never suppress\n    desc = (part.get(\"description\") or \"\").strip()\n    if not desc:\n        return \"ga_artifact\"\n    if _ASSEMBLY_TOKEN_RE.search(desc) or _part_carries_sub_bom(part):\n        return \"assembly_rollup\"\n    return None\n\n\ndef _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:"
],
[
"suppression_block",
"        process[\"assembly_parent_fab_suppressed\"] = True\n\n    # Acrylic route, costed the SDI way",
"        process[\"assembly_parent_fab_suppressed\"] = True\n\n    # --- Assembly roll-up / GA-artifact suppression (additive, geometry-guarded) -------\n    # A record with NO flat geometry of its own that is named as an assembly (…WA / ASM /\n    # ASSEMBLY) or carries a child BOM is a roll-up of parts ALREADY costed individually.\n    # It must not carry sheet/board MATERIAL (its children own that) nor geometry-derived\n    # fab labour — laser/CNC/fold/punch/drill (its children own those too). Genuine join\n    # work (weld/glue/assemble/handle/powder) is retained. A blank-description no-geometry\n    # record is a GA / title-block fragment and is excluded from costing entirely. Parts\n    # WITH their own DXF never reach here (guard inside the classifier), so a real one-piece\n    # part named \"…ASSEMBLY\" with a flat pattern is unaffected.\n    _rollup_kind = _classify_assembly_rollup(part)\n    if _rollup_kind:\n        _ROLLUP_FAB_STRIP = {\n            \"laser_cutting\", \"laser_cutting_acrylic\", \"folding\", \"punch\",\n            \"hole_machining\", \"guillotine\", \"plasma_cutting\", \"waterjet\",\n            \"drilling\", \"tapping\", \"countersinking\", \"cnc_routing\",\n        }\n        if _rollup_kind == \"ga_artifact\":\n            for _bucket in (\"run_times_min_per_unit\", \"setup_times_min\"):\n                if isinstance(process.get(_bucket), dict):\n                    process[_bucket].clear()\n            process[\"ga_artifact_excluded\"] = True\n        else:  # assembly_rollup\n            for _bucket in (\"run_times_min_per_unit\", \"setup_times_min\"):\n                _m = process.get(_bucket)\n                if isinstance(_m, dict):\n                    for _op in [o for o in _m if o in _ROLLUP_FAB_STRIP]:\n                        _m.pop(_op, None)\n            process[\"assembly_rollup_fab_suppressed\"] = True\n        # Zero the sheet/board material this roll-up was double-counting — its children\n        # already carry it. (material is computed above; mutate it before it is read.)\n        if isinstance(material, dict):\n            material[\"unit_material_cost_gbp\"] = 0.0\n            material[\"cost_per_part_gbp\"] = 0.0\n            material[\"extended_material_cost_gbp\"] = 0.0\n            material[\"extended_sheet_material_cost_gbp\"] = 0.0\n            material[\"material_suppressed_reason\"] = (\n                \"assembly_rollup_material_carried_by_children\"\n                if _rollup_kind == \"assembly_rollup\" else \"ga_artifact_not_a_make_part\"\n            )\n        part[\"_assembly_rollup_kind\"] = _rollup_kind\n        part.setdefault(\"risk_flags\", []).append(\n            \"ga_or_titleblock_artifact_excluded\" if _rollup_kind == \"ga_artifact\"\n            else \"assembly_rollup_material_and_fab_suppressed\"\n        )\n\n    # Acrylic route, costed the SDI way"
],
[
"data_sufficiency",
"    fabricated = [\n        p for p in source_parts\n        if str(p.get(\"normalized_material\") or \"\").upper()\n        not in {\"BOUGHT_IN\", \"PAPER\", \"PRINTED_PAPER\", \"UNKNOWN\", \"\"}\n        and str(p.get(\"part_number\") or \"\").upper() not in (\"\", \"NONE\", \"?\")\n    ]",
"    fabricated = [\n        p for p in source_parts\n        if str(p.get(\"normalized_material\") or \"\").upper()\n        not in {\"BOUGHT_IN\", \"PAPER\", \"PRINTED_PAPER\", \"UNKNOWN\", \"\"}\n        and str(p.get(\"part_number\") or \"\").upper() not in (\"\", \"NONE\", \"?\")\n        and not p.get(\"_assembly_rollup_kind\")\n    ]"
]
]""")

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "estimator.py"
    path = os.path.abspath(path)
    print("[patch] target: " + path)
    if not os.path.isfile(path):
        print("[patch] ERROR: file not found: " + path)
        print("        Run this from C:\\ClaudeVision\\src, or pass the path as an argument.")
        return 2

    # Read raw (no newline translation) so we can preserve the file's CRLF on write.
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    uses_crlf = "\r\n" in raw
    norm = raw.replace("\r\n", "\n")   # work in LF; anchors below are LF

    if "_classify_assembly_rollup" in norm:
        print("[patch] already applied (_classify_assembly_rollup present) - no change made.")
        return 0

    # Verify every anchor matches exactly once BEFORE writing anything (all-or-nothing).
    for name, old, _new in PAIRS:
        n = norm.count(old)
        if n != 1:
            print("[patch] ABORT: anchor '" + name + "' found %d time(s) (expected 1)." % n)
            print("        Your estimator.py differs from the expected base around this region.")
            print("        Nothing was written. Send me your current estimator.py and I'll rebase.")
            return 3

    patched = norm
    for name, old, new in PAIRS:
        patched = patched.replace(old, new, 1)
        print("[patch] applied: " + name)

    # Restore original line-ending style.
    out = patched.replace("\n", "\r\n") if uses_crlf else patched

    bak = path + ".bak"
    with open(bak, "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    print("[patch] backup written: " + bak)

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print("[patch] estimator.py updated (line endings preserved: %s)." % ("CRLF" if uses_crlf else "LF"))

    try:
        py_compile.compile(path, doraise=True)
        print("[patch] compile OK.")
    except py_compile.PyCompileError as e:
        print("[patch] COMPILE FAILED - restoring backup.")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(raw)
        print(e)
        return 4

    print('[patch] DONE. Re-run:  python main.py --search-root "...FlatPackTrestle" --folder-as-job')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
