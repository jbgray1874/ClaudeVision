#!/usr/bin/env python3
"""Smoke-check: compile every .py file under src/ to catch syntax breaks.

No database, no imports of third-party packages — this only parses the source,
so it runs anywhere in seconds and is safe to wire into CI or a pre-commit hook.

Usage:
    python scripts/check_compile.py [root]

Exit code 0 if everything parses, 1 if any file fails (failures are listed).
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

DEFAULT_ROOT = "src"


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / DEFAULT_ROOT
    if not root.exists():
        print(f"error: root not found: {root}")
        return 1

    files = [p for p in sorted(root.rglob("*.py")) if p.is_file()]
    failures: list[tuple[Path, str]] = []

    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append((path, str(exc)))

    print(f"Checked {len(files)} file(s) under {root}")
    if failures:
        print(f"\n{len(failures)} file(s) failed to compile:\n")
        for path, err in failures:
            print(f"  ✗ {path}")
            print(f"      {err.strip().splitlines()[-1] if err.strip() else 'unknown error'}")
        return 1

    print("All files parsed cleanly. ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
