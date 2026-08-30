#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_dxf_bend_override.py  — make the DXF flat-pattern bend_count authoritative.

WHY: feature_synthesis.infer_bend_count currently derives bends from text signals
(angles / fold values / fold-count-textual) and a dashed-long-axis-line heuristic,
and only falls back to the DXF's real bend count LAST. On a genuine flat-pattern
DXF, a dashed centre line or a shared "fold" note can therefore fire a phantom fold
even though the flat pattern (what the press brake actually bends from) shows 0 bends.
Seen on 12120: 03M/04M/05M folded despite the DXF showing 0 bends.

FIX: when a part has a genuine flat-pattern DXF (flat_pattern_detected AND
geometry_source == "dxf_flat_pattern"), RETURN the DXF's own bend count
(geometry_rollup["estimated_bend_line_count"], set from flat["bend_count"] by
drawing_job_merge) and skip the proxies. Parts with NO flat-pattern DXF fall
through to the existing proxy logic UNCHANGED.

ONE exact-string edit at the TOP of infer_bend_count. Self-tests the exact 12120
cases before writing. Makes a .bak. Idempotent. Verifies the write landed.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_dxf_bend_override.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("feature_synthesis.py")

# Anchor: the first three lines of infer_bend_count's body (from the live grep).
OLD = (
    "def infer_bend_count(part: Dict[str, Any], geometry_confidence: float) -> int:\n"
    "    angle_count = len(part.get(\"angles_deg\", []))\n"
    "    fold_value_count = len(part.get(\"fold_values_mm\", []))\n"
    "    fold_text_count = part.get(\"fold_count_textual\", 0)\n"
)

NEW = (
    "def infer_bend_count(part: Dict[str, Any], geometry_confidence: float) -> int:\n"
    "    # DXF flat-pattern is what the press brake actually bends from — it is ground\n"
    "    # truth for bend count. When a genuine flat-pattern DXF is present, its bend\n"
    "    # count is authoritative and WINS over the text / dashed-line proxies below\n"
    "    # (which can mistake a dashed centre line or a shared 'fold' note for a real\n"
    "    # bend). A DXF-confirmed 0 must mean 0 folds — not fall through to proxies.\n"
    "    if part.get(\"flat_pattern_detected\") and part.get(\"geometry_source\") == \"dxf_flat_pattern\":\n"
    "        _gr = part.get(\"geometry_rollup\") or {}\n"
    "        return int(_gr.get(\"estimated_bend_line_count\", 0) or 0)\n"
    "    angle_count = len(part.get(\"angles_deg\", []))\n"
    "    fold_value_count = len(part.get(\"fold_values_mm\", []))\n"
    "    fold_text_count = part.get(\"fold_count_textual\", 0)\n"
)


def _selftest():
    """Prove the new logic gives the right answer on the 12120 cases + no-DXF safety."""
    def new_infer(part):
        # mirror of the patched top-of-function behaviour
        if part.get("flat_pattern_detected") and part.get("geometry_source") == "dxf_flat_pattern":
            gr = part.get("geometry_rollup") or {}
            return int(gr.get("estimated_bend_line_count", 0) or 0)
        # proxy fallback (simplified, for the test only)
        text_signal = max(len(part.get("angles_deg", [])),
                          len(part.get("fold_values_mm", [])),
                          part.get("fold_count_textual", 0))
        if text_signal:
            return text_signal
        gr = part.get("geometry_rollup") or {}
        if gr.get("dashed_long_axis_lines"):
            return 1
        return int(gr.get("estimated_bend_line_count", 0) or 0)

    cases = [
        # (name, part, expected)
        ("03M flat DXF, dashed centre line, 0 real bends",
         {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
          "geometry_rollup": {"estimated_bend_line_count": 0, "dashed_long_axis_lines": 1}}, 0),
        ("04M flat DXF, a corner angle, 0 real bends",
         {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
          "angles_deg": [90], "geometry_rollup": {"estimated_bend_line_count": 0}}, 0),
        ("05M flat DXF, 0 real bends",
         {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
          "geometry_rollup": {"estimated_bend_line_count": 0}}, 0),
        ("01M flat DXF, 2 real bends",
         {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
          "geometry_rollup": {"estimated_bend_line_count": 2}}, 2),
        ("08M flat DXF, 1 real bend",
         {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
          "geometry_rollup": {"estimated_bend_line_count": 1}}, 1),
        ("no-DXF part with a fold note -> proxy still folds (unchanged)",
         {"fold_count_textual": 1, "geometry_rollup": {}}, 1),
        ("no-DXF part with dashed lines -> proxy still folds (unchanged)",
         {"geometry_rollup": {"dashed_long_axis_lines": 1}}, 1),
        ("dxf (not flat_pattern) part with fold note -> proxy path (unchanged)",
         {"geometry_source": "dxf", "fold_count_textual": 2, "geometry_rollup": {}}, 2),
    ]
    print("Self-test (patched infer_bend_count logic):")
    ok = True
    for name, part, exp in cases:
        got = new_infer(part)
        flag = "" if got == exp else "  <-- UNEXPECTED"
        if flag:
            ok = False
        print(f"  {('OK ' if got==exp else 'BAD')}  bend={got} (want {exp})  {name}{flag}")
    return ok


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    if not _selftest():
        raise SystemExit("Self-test FAILED — not patching.")
    print("  Self-test PASSED: flat DXFs use the real DXF bend count (03M/04M/05M->0,\n"
          "  01M->2, 08M->1); no-DXF parts keep the proxy fallback.\n")

    src = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake actually bends from" in src:
        print("Already patched. Nothing to do.")
        return
    n = src.count(OLD)
    if n == 0:
        raise SystemExit(
            "Anchor not found — the live infer_bend_count differs from expected.\n"
            "Paste the first ~5 lines of infer_bend_count so I can re-target.")
    if n > 1:
        raise SystemExit(f"Anchor found {n}x (expected 1) — stopping to avoid a wrong edit.")

    bak = TARGET.with_suffix(".py.bak_dxfbend")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake actually bends from" in back:
        print(f"PATCHED feature_synthesis.py (backup: {bak.name}).")
        print("Re-run 12120. Expect: 03M/04M/05M NO LONGER folded; 01M/08M still folded;")
        print("the phantom Fold rows for the flat parts gone; fold labour drops accordingly.")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change.")


if __name__ == "__main__":
    main()
