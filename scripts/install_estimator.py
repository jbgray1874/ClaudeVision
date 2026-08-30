#!/usr/bin/env python3
"""Install Downloads estimator (11).py as src/estimator.py (falls back to (9))."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "src" / "estimator.py"
SOURCES = [
    ROOT.parent / "Documents" / "Downloads" / "estimator (11).py",
    Path.home() / "Documents" / "Downloads" / "estimator (11).py",
    ROOT.parent / "Documents" / "Downloads" / "estimator (9).py",
    Path.home() / "Documents" / "Downloads" / "estimator (9).py",
    ROOT / "src" / "estimator.py",  # refresh from self if re-run
]


def main() -> int:
    for src in SOURCES:
        if not src.is_file():
            continue
        shutil.copy2(src, DST)
        text = DST.read_text(encoding="utf-8")
        for needle in ("infer_primary_dimensions", "_dxf_geometry_trusted", "estimate_document"):
            if needle not in text:
                print(f"WARN: {needle} missing after copy from {src}")
        print(f"Installed {src} -> {DST} ({len(text.splitlines())} lines)")
        return 0
    print("ERROR: estimator (11).py / (9).py not found in Downloads")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
