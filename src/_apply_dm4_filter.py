#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_dm4_filter.py  — extend _THREAD_SPEC_RE to catch detail/thread callouts
like 'D-M4' that were slipping through _is_false_part_number and landing in the
Sheet Steel block with no geometry (blank gauge -> #DIV/0!).

WHAT IT CHANGES (document_builder.py, ONE regex):
  BEFORE:  r"^M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)"
  AFTER:   r"^(?:D-?)?M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)"
                ^^^^^^^ optional 'D-' or 'D' detail prefix

  This makes 'D-M4', 'DM4', 'D-M6' match as false part numbers (thread/detail
  callouts), while REAL parts stay safe:
    - '12120-01-01M' : does NOT start with optional-D + M + digit -> NOT matched
    - 'B-03'         : NOT matched
    - 'M4', 'M6-6H'  : still matched (unchanged behaviour)

  Exact-string-replace. Makes a .bak. Verifies before + after. Idempotent.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_dm4_filter.py
Then re-run 12120.
"""
from __future__ import annotations
import re, shutil, sys
from pathlib import Path

TARGET = Path("document_builder.py")

OLD = r'''r"^M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)"'''
NEW = r'''r"^(?:D-?)?M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)"'''

def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()}  (run from C:\\ClaudeVision\\src)")
    src = TARGET.read_text(encoding="utf-8")

    # sanity: self-test the two regexes on known cases BEFORE touching the file
    old_re = re.compile(r"^M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)", re.I)
    new_re = re.compile(r"^(?:D-?)?M\d{1,2}(\s*[-xX]\s*\d|\s+-\s*\d+H|\s+THRU|\s+FINE|\s+COARSE|\s*$)", re.I)
    checks = {
        "D-M4": (False, True), "DM4": (False, True), "D-M6": (False, True),
        "M4": (True, True), "M6-6H": (True, True), "M4 x 10": (True, True),
        "12120-01-01M": (False, False), "B-03": (False, False), "12120-01-101": (False, False),
    }
    print("Self-test (old -> new) on known part codes:")
    ok = True
    for pn, (want_old, want_new) in checks.items():
        go = bool(old_re.match(pn)); gn = bool(new_re.match(pn))
        flag = "" if (go == want_old and gn == want_new) else "  <-- UNEXPECTED"
        if flag: ok = False
        print(f"  {pn:16} old={go!s:5} new={gn!s:5}{flag}")
    if not ok:
        raise SystemExit("Self-test failed — not patching. The regex behaves unexpectedly.")
    print("  Self-test PASSED: D-M4/DM4/D-M6 now caught; real parts (01M/B-03/101) untouched.\n")

    if NEW in src:
        print("Already patched (new regex present). Nothing to do.")
        return
    n = src.count(OLD)
    if n == 0:
        raise SystemExit("Could not find the exact _THREAD_SPEC_RE pattern to replace.\n"
                         "The live file differs from expected — paste the current "
                         "_THREAD_SPEC_RE line so I can re-target.")
    if n > 1:
        raise SystemExit(f"Pattern found {n} times — expected 1. Stopping to avoid a wrong edit.")

    bak = TARGET.with_suffix(".py.bak_dm4")
    shutil.copy2(TARGET, bak)
    patched = src.replace(OLD, NEW)
    TARGET.write_text(patched, encoding="utf-8")

    # confirm the write landed
    back = TARGET.read_text(encoding="utf-8")
    if NEW in back and OLD not in back:
        print(f"PATCHED: _THREAD_SPEC_RE extended to catch 'D-' detail prefix.")
        print(f"  backup: {bak.name}")
        print(f"  Re-run 12120 — D-M4 should be filtered out; #DIV/0! gone; 7 parts compute.")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change made.")

if __name__ == "__main__":
    main()
