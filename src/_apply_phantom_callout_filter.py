#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_phantom_callout_filter.py — remove detail-view callout phantoms (B-03,
D-M4) from the parts list before costing.

WHAT THESE ARE: balloon/detail-view references ('B-03' = Detail B item 03,
'D-M4' = Detail M4) that the extractor picks up as parts. They have NO real
content and falsely match junk UDEF entries (e.g. ATN £671,765, correctly
blocked) but still get a small computed cost and clutter the BOM.

SIGNATURE (verified against all 18 parts on 12120 — see probe):
  description is empty/None
  AND page_roles == ['detail']            (not bought_in / bom_only / assembly)
  AND no geometry (geometry_source falsy AND not flat_pattern_detected)
  AND no dxf_source_file
  AND part_number does NOT start with the job's dominant part-number prefix
Real parts/assemblies (01M..08M, 101 'STAND WELD ASSY', SA01 'STAND ASSY', 103)
each have a description AND the standard prefix, so they fail the signature.
Bought-in (BI-*, PACKAGING, DELIVERY) have page_roles ['bought_in'], not
['detail']. A genuine part would have to lose BOTH its description AND its
standard part number to be caught — two independent failures — so false
positives are very unlikely.

The existing _is_false_part_number filter (document_builder.py:1750) matches by
NAME PATTERN (thread/fastener specs) and does NOT catch B-03/D-M4. This adds a
SIGNATURE check at the same choke point, so phantoms are removed from the parts
list before estimation → excluded from steel + bought-in + labour on all paths.

INSTRUMENTED: logs "[PHANTOM-FILTER] Removed detail-callout phantoms: [...]" so
the run PROVES the filter fired (not assumed).

Two exact-string edits to document_builder.py:
  1. insert the helper + job-prefix deriver just above _is_false_part_number
  2. extend the filter at line 1750 to also drop detail-callout phantoms + log

Self-tests. .bak. Idempotent. Verifies write.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_phantom_callout_filter.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("document_builder.py")

# ── Edit 1: insert helpers just above the existing _is_false_part_number def ──
ANCHOR1 = (
    "def _is_false_part_number(pn: str) -> bool:\n"
    "    \"\"\"Thread callouts and fastener specs mistaken as SDI part numbers.\"\"\"\n"
)

HELPERS = (
    "def _dominant_part_prefix(parts: list) -> str:\n"
    "    \"\"\"Most common '<prefix>-' among parts that have real geometry or a DXF.\n"
    "    Used to spot foreign-format detail callouts without hard-coding a job code.\"\"\"\n"
    "    from collections import Counter\n"
    "    counts: Counter = Counter()\n"
    "    for p in parts:\n"
    "        pn = str(p.get(\"part_number\") or \"\")\n"
    "        has_geom = bool(p.get(\"geometry_source\")) or bool(p.get(\"flat_pattern_detected\")) or bool(p.get(\"dxf_source_file\"))\n"
    "        if has_geom and \"-\" in pn:\n"
    "            counts[pn.rsplit(\"-\", 1)[0]] += 1\n"
    "    if not counts:\n"
    "        # fall back: most common prefix among ALL hyphenated part numbers\n"
    "        for p in parts:\n"
    "            pn = str(p.get(\"part_number\") or \"\")\n"
    "            if \"-\" in pn:\n"
    "                counts[pn.rsplit(\"-\", 1)[0]] += 1\n"
    "    return counts.most_common(1)[0][0] if counts else \"\"\n"
    "\n"
    "\n"
    "def _is_detail_callout_phantom(part: dict, dominant_prefix: str) -> bool:\n"
    "    \"\"\"A content-free detail-view balloon reference (e.g. 'B-03', 'D-M4')\n"
    "    mistaken for a part. Removes it from ALL costing. Requires the FULL empty\n"
    "    signature AND a foreign part-number so real assemblies (which have a\n"
    "    description AND the standard prefix) are never caught.\"\"\"\n"
    "    pn = str(part.get(\"part_number\") or \"\")\n"
    "    if not pn:\n"
    "        return False\n"
    "    desc = part.get(\"description\")\n"
    "    if desc is not None and str(desc).strip():\n"
    "        return False  # real BOM items have a description\n"
    "    roles = part.get(\"page_roles\") or []\n"
    "    if roles != [\"detail\"]:\n"
    "        return False  # only pure detail-view callouts (not bought_in/assembly/bom_only)\n"
    "    if part.get(\"geometry_source\") or part.get(\"flat_pattern_detected\") or part.get(\"dxf_source_file\"):\n"
    "        return False  # any real geometry/DXF => not a phantom\n"
    "    if part.get(\"normalized_thickness_mm\") is not None:\n"
    "        return False\n"
    "    # foreign part-number format (does not share the job's dominant prefix)\n"
    "    if dominant_prefix and (pn == dominant_prefix or pn.startswith(dominant_prefix + \"-\") or pn.rsplit(\"-\", 1)[0] == dominant_prefix):\n"
    "        return False  # matches the job prefix => a real part that merely lost its desc\n"
    "    return True\n"
    "\n"
    "\n"
    "def _is_false_part_number(pn: str) -> bool:\n"
    "    \"\"\"Thread callouts and fastener specs mistaken as SDI part numbers.\"\"\"\n"
)

# ── Edit 2: extend the filter at line 1750 (drop phantoms too, with a log) ──
ANCHOR2 = (
    "    filtered = [p for p in parts if not _is_false_part_number(str(p.get(\"part_number\") or \"\"))]\n"
)

FILTER2 = (
    "    _dom_prefix = _dominant_part_prefix(parts)\n"
    "    _phantoms = [str(p.get(\"part_number\")) for p in parts if _is_detail_callout_phantom(p, _dom_prefix)]\n"
    "    if _phantoms:\n"
    "        import logging as _lg\n"
    "        _lg.getLogger(__name__).info(\"[PHANTOM-FILTER] Removed detail-callout phantoms: %s\", _phantoms)\n"
    "        print(\"[PHANTOM-FILTER] Removed detail-callout phantoms:\", _phantoms, flush=True)\n"
    "    filtered = [\n"
    "        p for p in parts\n"
    "        if not _is_false_part_number(str(p.get(\"part_number\") or \"\"))\n"
    "        and not _is_detail_callout_phantom(p, _dom_prefix)\n"
    "    ]\n"
)


def _selftest():
    # Mirror of _is_detail_callout_phantom + prefix logic.
    def dom_prefix(parts):
        from collections import Counter
        c = Counter()
        for p in parts:
            pn = str(p.get("part_number") or "")
            if (p.get("geometry_source") or p.get("flat_pattern_detected") or p.get("dxf_source_file")) and "-" in pn:
                c[pn.rsplit("-", 1)[0]] += 1
        if not c:
            for p in parts:
                pn = str(p.get("part_number") or "")
                if "-" in pn:
                    c[pn.rsplit("-", 1)[0]] += 1
        return c.most_common(1)[0][0] if c else ""

    def is_phantom(part, dp):
        pn = str(part.get("part_number") or "")
        if not pn:
            return False
        desc = part.get("description")
        if desc is not None and str(desc).strip():
            return False
        roles = part.get("page_roles") or []
        if roles != ["detail"]:
            return False
        if part.get("geometry_source") or part.get("flat_pattern_detected") or part.get("dxf_source_file"):
            return False
        if part.get("normalized_thickness_mm") is not None:
            return False
        if dp and (pn == dp or pn.startswith(dp + "-") or pn.rsplit("-", 1)[0] == dp):
            return False
        return True

    # The real 12120 part set.
    parts = [
        {"part_number": "12120-01-01M", "description": "MOUNTING BRACKET", "page_roles": ["detail"], "geometry_source": "dxf", "flat_pattern_detected": True, "dxf_source_file": "x.DXF", "normalized_thickness_mm": 1.5},
        {"part_number": "12120-01-03M", "description": "STAND BASE PLATE", "page_roles": ["detail"], "geometry_source": "dxf_flat_pattern", "flat_pattern_detected": True, "dxf_source_file": "x.DXF", "normalized_thickness_mm": 1.5},
        {"part_number": "12120-01-101", "description": "STAND WELD ASSY", "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
        {"part_number": "12120-01-SA01", "description": "STAND ASSY", "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
        {"part_number": "12120-01-103", "description": "SCREEN MOUNTING BRACKET", "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
        {"part_number": "BI-THREADEDPEMSTUD", "description": "Threaded Pem Stud", "page_roles": ["bought_in"]},
        {"part_number": "BI-SCREENCABLE", "description": "Screen Cable", "page_roles": ["bought_in"]},
        {"part_number": "B-03", "description": None, "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
        {"part_number": "D-M4", "description": None, "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
        # extra safety: a real part that LOST its description but keeps the prefix -> must be KEPT
        {"part_number": "12120-01-99M", "description": None, "page_roles": ["detail"], "geometry_source": None, "flat_pattern_detected": False, "dxf_source_file": None, "normalized_thickness_mm": None},
    ]
    dp = dom_prefix(parts)
    expect_removed = {"B-03", "D-M4"}
    got_removed = {str(p.get("part_number")) for p in parts if is_phantom(p, dp)}
    print(f"Self-test: dominant_prefix={dp!r}")
    ok = True
    for p in parts:
        pn = str(p.get("part_number"))
        removed = is_phantom(p, dp)
        want = pn in expect_removed
        flag = "" if removed == want else "  <-- UNEXPECTED"
        if flag:
            ok = False
        print(f"  {('REMOVE' if removed else 'keep  ')}  {pn:<22} desc={p.get('description')!r}{flag}")
    print(f"  => removed={sorted(got_removed)} (want {sorted(expect_removed)})")
    if dp != "12120-01":
        print(f"  NOTE: expected dominant prefix '12120-01', got {dp!r}")
    return ok and got_removed == expect_removed


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    if not _selftest():
        raise SystemExit("Self-test FAILED — not patching.")
    print("  Self-test PASSED: only B-03/D-M4 removed; 101/SA01/103/03M/BI-* and a\n"
          "  desc-less-but-prefixed real part all KEPT.\n")

    src = TARGET.read_text(encoding="utf-8")
    if "_is_detail_callout_phantom" in src:
        print("Already patched. Nothing to do.")
        return

    for label, anchor in (("helper-anchor", ANCHOR1), ("filter-anchor", ANCHOR2)):
        c = src.count(anchor)
        if c != 1:
            raise SystemExit(f"{label} found {c}x (expected 1) — stopping. Paste the surrounding lines to re-target.")

    bak = TARGET.with_suffix(".py.bak_phantomfilter")
    shutil.copy2(TARGET, bak)
    src2 = src.replace(ANCHOR1, HELPERS).replace(ANCHOR2, FILTER2)
    TARGET.write_text(src2, encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    if "_is_detail_callout_phantom" in back and "[PHANTOM-FILTER]" in back:
        print(f"PATCHED document_builder.py (backup: {bak.name}).")
        print("Re-run 12120. Expect:")
        print("  - stdout: [PHANTOM-FILTER] Removed detail-callout phantoms: ['B-03', 'D-M4']")
        print("  - BOM: B-03 GONE (was £2.22). D-M4 already wasn't in the BOM; now")
        print("    formally filtered too.")
        print("  - 101 STAND WELD ASSY + SA01 STAND ASSY STILL present (real assemblies).")
        print("  - Material total drops by ~£2.22 (B-03 removed).")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change.")


if __name__ == "__main__":
    main()
