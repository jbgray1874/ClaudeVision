#!/usr/bin/env python3
r"""
_apply_weld_mig_tig_wordboundary.py

FIX: `extractor_patterns.py` weld_keywords used bare substring tests
       or "MIG" in text
       or "TIG" in text
which match INSIDE ordinary words. On drawing 1300-01 the designer name
`robert.tigg` contains "tig", so weld_keywords fired, `welding` was appended,
and the estimator added a ~£4.54 phantom Weld (CO2) line to a flat shelf that
has NO weld (DXF confirmed: single flat blank, 0 inserts, 0 weld annotations;
regex_match=None for \bWELD\b — it was never a real weld cue).

CHANGE (surgical, two lines only):
    or "MIG" in text        ->   or re.search(r"\bMIG\b", text, flags=re.IGNORECASE)
    or "TIG" in text        ->   or re.search(r"\bTIG\b", text, flags=re.IGNORECASE)

Real cues are UNAFFECTED: "WELD" (1106), \bWELD\b regex (1113), WELD INT/FLUSH/
CLOSED/CORNER, "TIG WELD"/"MIG WELD" (the WELD token still matches) all still
fire. Word boundaries mean `robert.tigg`, FATIGUE, INVESTIGATE, MITIGATE, etc.
no longer false-trigger welding. 1282's genuine welds come from real WELD/SPOT
callouts and are untouched -> regression anchor safe.

Idempotent: refuses to run twice; asserts each old line is present exactly once.
Backs up the file first. READ the diff it prints before deploying.
"""
import re, shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\extractor_patterns.py"

REPLACEMENTS = [
    ('        or "MIG" in text\n',
     '        or re.search(r"\\bMIG\\b", text, flags=re.IGNORECASE)\n'),
    ('        or "TIG" in text\n',
     '        or re.search(r"\\bTIG\\b", text, flags=re.IGNORECASE)\n'),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    # already patched?
    if 'r"\\bTIG\\b"' in src or 'r"\\bMIG\\b"' in src:
        sys.exit("Already patched (found \\bMIG\\b/\\bTIG\\b). No change made.")

    # verify each target appears exactly once BEFORE touching anything
    for old, _ in REPLACEMENTS:
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of:\n{old!r}\nfound {n}. "
                     f"No change made — re-check the source around line 1107-1108.")

    new = src
    for old, rep in REPLACEMENTS:
        new = new.replace(old, rep)

    # ensure `import re` exists (it does in this module, but assert)
    if "import re" not in new:
        sys.exit("ABORT: `import re` not found in module; would break at runtime.")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_weldfix_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- changed lines ---")
    print('  1107: or "MIG" in text   ->   or re.search(r"\\bMIG\\b", text, flags=re.IGNORECASE)')
    print('  1108: or "TIG" in text   ->   or re.search(r"\\bTIG\\b", text, flags=re.IGNORECASE)')
    print("\nVerify with:")
    print(r'  Select-String -Path C:\ClaudeVision\src\extractor_patterns.py -Pattern "bMIG|bTIG" -Context 1,1')


if __name__ == "__main__":
    main()
