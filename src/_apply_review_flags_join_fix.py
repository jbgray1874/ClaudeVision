#!/usr/bin/env python3
r"""
_apply_review_flags_join_fix.py

CRASH (pre-existing — not from today's work; 7670 is simply the first job to trip it):

    File "wb_populate.py", line 1039, in _append_ai_sheets
        " | ".join(pe.get("review_flags") or []),
    TypeError: sequence item 1: expected str instance, dict found

review_flags normally holds strings. On 7670 something upstream appended a dict. The join
blows up, populate_workbook dies, and main.py silently falls back to xlsx_output — so the
job produces the WRONG WORKBOOK with no loud failure. That fallback is the real hazard:
a crash that degrades quietly is worse than one that stops.

FIX: coerce every element to a string, and if a dict shows up, render it compactly rather
than printing "{'code': ...}" into the estimator's review column. The dict is NOT silently
discarded — whatever information it carries still reaches the sheet.

This does NOT fix the upstream producer that is emitting a dict into a list of strings.
That is a separate, real defect: something is writing structured data into a field the rest
of the system treats as text. Worth a ticket. This patch stops it taking the workbook down.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_review_flags_join_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_flag_to_text"

OLD = '''                " | ".join(pe.get("review_flags") or []),'''

NEW = '''                " | ".join(_flag_to_text(_rf) for _rf in (pe.get("review_flags") or [])),'''

HELPER = '''

def _flag_to_text(rf):
    """review_flags is meant to be a list of strings, but something upstream sometimes
    appends a dict — which killed populate_workbook on 7670 (TypeError in str.join) and
    sent the whole job down the xlsx_output fallback path SILENTLY, producing the wrong
    workbook with no loud failure.

    Coerce to text without losing the content. A dict is rendered compactly rather than
    dumped as a raw Python repr into the estimator's review column.

    The upstream producer writing structured data into a list-of-strings field is a
    separate defect and still needs fixing at source.
    """
    if isinstance(rf, str):
        return rf
    if isinstance(rf, dict):
        for _k in ("message", "msg", "text", "reason", "flag", "detail", "description"):
            if rf.get(_k):
                _code = rf.get("code") or rf.get("type") or rf.get("name")
                return f"{_code}: {rf[_k]}" if _code else str(rf[_k])
        return "; ".join(f"{k}={v}" for k, v in rf.items() if v not in (None, "", []))
    if isinstance(rf, (list, tuple)):
        return " / ".join(_flag_to_text(x) for x in rf)
    return str(rf)
'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match for the review_flags join, found {n}. Nothing written.")
    src = src.replace(OLD, NEW, 1)

    # drop the helper in just before _append_ai_sheets
    anchor = "def _append_ai_sheets("
    if anchor not in src:
        sys.exit("ABORT: could not find _append_ai_sheets to anchor the helper against.")
    src = src.replace(anchor, HELPER.lstrip("\n") + "\n" + anchor, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_rfjoin_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  review_flags join hardened; workbook no longer dies on a dict flag")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RE-RUN 7670 (qty 50) — and set the console encoding, or the console itself dies on the
warning glyph:

    $env:PYTHONIOENCODING="utf-8"
    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\7670-01-AEG ORANGE A4 LEAFLET HOLDER" --folder-as-job

EXPECT THE WORKBOOK TO POPULATE — but expect the ESTIMATE to be poor, and for good reasons:

  * 0 labour rows. Three wire forms, no DXF, no bar schedule -> the engine cannot tell they
    are 4mm wire, so they never reach the wire route and generate no manufacturing at all.
  * No powder. The three parts are RAW — and that is CORRECT. You form raw wire, weld the
    frame, THEN coat the assembly. The finish "POWDER COATED - FINE TEXTURE" sits on the
    ASSEMBLY record (part_number None), which is not a costed part. Our powder gate is
    per-part, so it sees three raw parts and drops £2.32 of Tim's £6.74.

    I earlier called this a drawing defect. It is not. The drawings are right. The ENGINE's
    model is wrong: it has no concept of a finish applied to an ASSEMBLY after welding.

  * Tim: £6.74. Anything the engine prints will be a long way off, and the credibility gate
    (9%, DXF on 0% of parts) is right to refuse to publish it.

THIS JOB IS A DIAGNOSTIC, NOT A PARITY RUN. It has surfaced three real defects:
  1. ASSEMBLY-LEVEL FINISH is not modelled (powder applied post-weld to a weldment)
  2. DWG-ONLY PACKS are unreadable — ezdxf cannot open DWG, so geometry is zero
  3. ROBOMAC/SPOTWELD grouping is WRONG — Tim writes one row PER WIRE FORM (100/450/300 per
     hour: each form is a different bend program = a different setup). My grouping patch
     collapses them to one row per job and would UNDER-charge. Must be fixed before the
     next wire job.
""")


if __name__ == "__main__":
    main()
