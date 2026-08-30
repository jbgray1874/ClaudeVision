#!/usr/bin/env python3
r"""
_revert_guard1_notetext.py

WHAT WENT WRONG
---------------
Guard 1 (added 2026-07-13 in _apply_phantom_boughtin_guards.py) reduced the note-scan page
text from FOUR extraction variants to ONE, by adding a `break`:

    for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):
        _v = _pg.get(_k)
        if _v:
            _note_chunks.append(str(_v))
            break                      # <-- Guard 1

I described those four keys as "duplicate variants". THEY ARE NOT. They are four DIFFERENT
extractions of the same page and they do not contain the same text. pdfplumber_text is
almost always present, so the loop breaks on it and normalized_text / pypdf_text /
text_preview are never read at all.

CONSEQUENCE: job 1282 lost BI-LEDDOWNLIGHTS (£26.00, £27.04 with scrap) from its BOM.
Deterministically — three consecutive runs, zero downlights, where the pre-guard run on
10 Jul had them. `_note_text` feeds BOTH the deterministic prose recogniser (line ~3532)
AND the LLM note-scan (line ~3591), so starving it silently blinded both.

I earlier told JG the guards were "exonerated" because the BOM-overflow flag accounted for
the £28. That was wrong: I found AN explanation and stopped looking. The overflow was real
but it was only dropping the £0 PACKAGING/DELIVERY placeholders. This was the real loss.

THE FIX
-------
Remove the `break`. All four variants are appended again, exactly as before.

The £105 phantom bought-in (the job's own title costed as a purchased part) stays fixed:
that is GUARD 2 — `_job_identity_tokens` / `_is_job_identity_desc` at ~line 3543 — which
drops any recognised bought-in whose words are a subset of the job name. It does not depend
on Guard 1 in any way. Guard 3 (loud flagging of priced-but-unverified bought-ins) is also
untouched.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _revert_guard1_notetext.py
"""
from __future__ import annotations
import re, shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "GUARD-1 REVERTED"

PAT = re.compile(
    r'([ \t]*)for _k in \("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"\):\n'
    r'([ \t]*)_v = _pg\.get\(_k\)\n'
    r'([ \t]*)if _v:\n'
    r'([ \t]*)_note_chunks\.append\(str\(_v\)\)\n'
    r'([ \t]*)break\n'
)


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()

    if SENTINEL in src:
        sys.exit("Already reverted (sentinel present). Nothing to do.")

    hits = PAT.findall(src)
    if len(hits) != 1:
        sys.exit(
            f"ABORT: expected exactly 1 match for the Guard-1 loop, found {len(hits)}.\n"
            "The deployed file is not what was probed. Nothing written.\n"
            "Re-run the Select-String around _note_chunks and send the exact block."
        )

    m = PAT.search(src)
    i1, i2, i3, i4, _i5 = m.groups()

    new_block = (
        f'{i1}# GUARD-1 REVERTED 2026-07-13. The `break` here took only the FIRST text\n'
        f'{i1}# variant. These four keys are DIFFERENT extractions of the same page, not\n'
        f'{i1}# duplicates — pdfplumber_text is nearly always present, so the loop broke on\n'
        f'{i1}# it and normalized_text / pypdf_text / text_preview were never read. That\n'
        f'{i1}# deterministically lost BI-LEDDOWNLIGHTS (£26) from 1282 for three runs.\n'
        f'{i1}# _note_text feeds BOTH the prose recogniser AND the LLM note-scan, so\n'
        f'{i1}# starving it blinded both. Append every variant, as before.\n'
        f'{i1}# The £105 phantom stays fixed by GUARD 2 (_job_identity_tokens), which does\n'
        f'{i1}# not depend on this loop.\n'
        f'{i1}for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):\n'
        f'{i2}_v = _pg.get(_k)\n'
        f'{i3}if _v:\n'
        f'{i4}_note_chunks.append(str(_v))\n'
    )

    src = PAT.sub(lambda _m: new_block, src, count=1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_revertguard1_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  removed Guard-1 `break` — all four text variants restored")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
VERIFY the break is gone (should print the loop with NO break):

    Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern "_note_chunks.append" -Context 2,2

THEN regress 1282:

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="10"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "<1282 folder>" --folder-as-job

EXPECT — both of these, or the fix is not right:
  * BI-LEDDOWNLIGHTS  Led Downlights  £26.00  BACK in the BOM  (17 BOM lines now)
  * NO  BI-DRILLSTUDHOLDER-style phantom  (Guard 2 still holding)
  * D6 = 10, AF82 = 9.73
  * Unit Cost ~ £277  (£250.08 + £27.04)

Then run 1310 and confirm the £105 phantom is STILL dead — that is the test that Guard 2
is doing the work on its own.
""")


if __name__ == "__main__":
    main()
