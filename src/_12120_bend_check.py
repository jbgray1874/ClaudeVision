#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_12120_bend_check.py  (READ-ONLY — reads DXFs, writes nothing)

Answers ONE question: which 12120 parts actually have bend lines?
The engine folds 8 parts; Tim folds only 4 (01M, 06M, 02M, 08M). If 03M/04M/05M
have NO bends, the engine is over-folding flat parts — a real routing error.

Uses the engine's OWN dxf_reader.extract_flat_pattern_data (same code the estimate
uses) so the bend_count matches what the engine sees.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _12120_bend_check.py ^
      "K:\Estimating\Completed\AI Estimating\Live Enquiry\12120-01-GA- DIGITAL TICKETING BRACKET"
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dxf_reader import extract_flat_pattern_data, is_dxf_path
except Exception as e:
    raise SystemExit(f"Could not import dxf_reader: {e}")

# Tim's routing: who does he FOLD (vs only laser)?
TIM_FOLDS = {"01M", "06M", "02M", "08M"}          # Tim folds these
TIM_FLAT  = {"03M", "04M", "05M"}                  # Tim only lasers these (flat)

def part_tag(name: str) -> str:
    # pull the NNM token (e.g. 01M, 08M) from a filename
    import re
    m = re.search(r"-(\d{2}M)\b", name) or re.search(r"\b(\d{2}M)\b", name)
    return m.group(1) if m else ""

def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    folder = Path(sys.argv[1])
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")

    dxfs = sorted([p for p in folder.rglob("*") if is_dxf_path(p)])
    if not dxfs:
        raise SystemExit(f"No DXF files found under {folder}")

    print(f"Found {len(dxfs)} DXF(s) under the job folder.\n")
    print(f"{'file':52} {'part':6} {'bends':>6} {'flat?':>6}  {'vs Tim'}")
    print("-" * 96)

    rows = []
    for p in dxfs:
        tag = part_tag(p.name)
        try:
            flat = extract_flat_pattern_data(p)
            bends = flat.get("bend_count")
            flatp = flat.get("flat_pattern_detected")
        except Exception as e:
            print(f"{p.name[:52]:52} {tag:6} {'ERR':>6} {'--':>6}  ({e})")
            continue

        # verdict vs Tim's routing
        verdict = ""
        if tag in TIM_FLAT:
            if bends and bends > 0:
                verdict = f"engine folds; Tim lasers (flat) — {bends} bend(s): CHECK"
            else:
                verdict = "no bends — engine should NOT fold (matches Tim=laser)"
        elif tag in TIM_FOLDS:
            if bends and bends > 0:
                verdict = f"{bends} bend(s) — Tim folds too: OK"
            else:
                verdict = "no bends read, but Tim FOLDS — under-read?"
        rows.append((tag, bends))
        print(f"{p.name[:52]:52} {tag:6} {str(bends):>6} {str(flatp):>6}  {verdict}")

    print("-" * 96)
    print("\nINTERPRETATION:")
    print("  - 03M/04M/05M with bends>0  -> engine folding them is defensible; Tim")
    print("    treating them flat is the difference (maybe formed differently).")
    print("  - 03M/04M/05M with bends=0  -> engine is OVER-FOLDING flat parts. The fold")
    print("    route + 30-min setup on those parts is phantom labour. Real routing bug:")
    print("    fold should only fire when bend_count > 0.")
    print("  - 01M/02M/06M/08M with bends=0 -> engine UNDER-reading bends Tim folds.")
    print("\n(Read-only. Nothing written.)")

if __name__ == "__main__":
    main()
