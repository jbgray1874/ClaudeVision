#!/usr/bin/env python3
r"""
_apply_powder_pointer_resolution.py

WHAT THE DRAWINGS ACTUALLY SAY  (confirmed by _probe_assembly_finish.py, not assumed)
-------------------------------------------------------------------------------------
  1310  page 2 (ASSEMBLY):        SURFACE FINISH: POWDER COATED - SEMI-GLOSS
        pages 3, 4 (details):     SEE ASSEMBLY DRAWING          -> the pointer IS answered
        Tim's manual charges P.Coat £2.00 + powder £0.30.

  1282  pages 1, 10, 11 (ASSEMBLIES):  POWDER COATED - SEMI-GLOSS
                                       COLOUR: RAL3020 - TRAFFIC RED
        pages 4, 5, 22, 23 (details):  SEE ASSEMBLY DRAWING     -> answered
        pages 12-15:                   RAW  (weldment children — correctly NOT coated)
        page 16:                       SCRAPED EDGES (acrylic lens — correctly NOT coated)

"SEE ASSEMBLY DRAWING" is a POINTER, not an absence. The engine has been reading it as
"no finish" and dropping powder on every part that carries it.

THE CURRENT GATE (wb_populate ~line 663)
----------------------------------------
    _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)

It keys on textual_operations — a DERIVED signal — rather than on the FINISH, which is what
the drawing actually states. Two consequences:

  * pointer parts (1448-01/02, 3886-02/03 on 1282; both parts on 1310) -> powder dropped
  * 1455-C-101 HEADER WELDMENT carries "POWDER COATED - SEMI-GLOSS" in its OWN
    surface_finishes, but normalized_finish came out empty, so the gate never sees it.
    The one part that unambiguously says "coat me" is not coated.

THE FIX — read the finish, and follow the pointer
--------------------------------------------------
  1. finish contains POWDER                -> coat it
  2. finish is a POINTER (SEE ASSEMBLY...)  -> resolve against the assembly page's finish
  3. finish is RAW / SCRAPED EDGES / etc    -> do NOT coat (explicit, honour it)
  4. no finish text at all                  -> fall back to the old textual_operations signal

If a part points at an assembly and NO assembly page states a finish, we cost NOTHING and
raise a DRAWING DEFECT flag. A detail that defers to an assembly which never answers is an
unanswerable drawing — that goes to Design, it does not get guessed at.

normalized_finish is empty on some parts, so surface_finishes is used as the fallback —
that alone fixes 1455-C-101.

EXPECTED IMPACT — SAY IT BEFORE THE RUN
----------------------------------------
  1310: both parts gain P.Coat. Tim charges £2.00. VALIDATE HERE FIRST — 1310 has a manual.
        If the engine's P.Coat comes out near £10.81/line (its flat rate on 1282), that is
        the KNOWN flat-P.Coat defect showing up, NOT a failure of this fix. Report both.

  1282: FIVE parts gain P.Coat (1448-01, 1448-02, 3886-02, 3886-03, 1455-C-101).
        At the flat £10.81/line that is roughly +£54, taking the anchor from £278.93 to
        somewhere near £333. THE ANCHOR WILL MOVE, AND IT SHOULD — it has been under-costing
        powder on a bright red powder-coated retail display. But 1282 has NO manual, so we
        cannot validate the new number. That is exactly why 1310 is fixed and checked first.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_powder_pointer_resolution.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_POWDER_POINTER_HINTS"

OLD = '''    _mw_parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _powder_ok = {}
    for _mp in _mw_parts:
        _pn = str(_mp.get("part_number") or "")
        _tops = _mp.get("textual_operations") or []
        if isinstance(_tops, str):
            _tops = [_tops]
        _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)'''

NEW = '''    # POWDER GATE — reads the DRAWING FINISH, and FOLLOWS POINTERS. (2026-07-13)
    #
    # "SEE ASSEMBLY DRAWING" is a POINTER, not an absence. It was being read as "no finish",
    # so powder was dropped on every part carrying it — including both parts of 1310, where
    # Tim charges P.Coat £2.00, and four parts of the 1282 Milwaukee bay, which the assembly
    # drawing states is POWDER COATED - SEMI-GLOSS, RAL3020 TRAFFIC RED.
    #
    #   1. finish contains POWDER              -> coat it
    #   2. finish is a POINTER                 -> resolve against the assembly page's finish
    #   3. finish is RAW / SCRAPED EDGES / ... -> do NOT coat (explicit; honour it)
    #   4. no finish text at all               -> fall back to textual_operations (old signal)
    #
    # If a part points at an assembly and NO assembly page states a finish, we cost NOTHING
    # and raise a DRAWING DEFECT flag. An unanswerable drawing goes to Design; it is not
    # guessed at.
    #
    # normalized_finish is empty on some parts (e.g. 1455-C-101 HEADER WELDMENT, which does
    # carry "POWDER COATED - SEMI-GLOSS" in surface_finishes), so surface_finishes is the
    # fallback. That alone fixes the one part that unambiguously says "coat me" and wasn't.
    _POWDER_POINTER_HINTS = ("SEE ASSEMBLY", "SEE GA", "AS ASSEMBLY",
                             "PER ASSEMBLY", "REFER TO ASSEMBLY")

    def _pg_role(_pg):
        _r = _pg.get("page_role")
        if isinstance(_r, dict):
            return str(_r.get("primary_role") or "")
        return str(_r or "")

    def _pg_text(_pg):
        _t = ""
        for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):
            if _pg.get(_k):
                _t += " " + str(_pg[_k])
        return _t.upper()

    _assembly_is_powder = False
    _assembly_finish_seen = False
    for _pg in (summary.get("pages") or []):
        if not _pg_role(_pg).lower().startswith("assembl"):
            continue
        _at = _pg_text(_pg)
        if "SURFACE FINISH" in _at or "POWDER" in _at:
            _assembly_finish_seen = True
        if "POWDER" in _at:
            _assembly_is_powder = True
            break

    _mw_parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _powder_ok = {}
    for _mp in _mw_parts:
        _pn = str(_mp.get("part_number") or "")
        _fin = str(_mp.get("normalized_finish") or "").strip()
        if not _fin:
            _fin = " ".join(str(x) for x in (_mp.get("surface_finishes") or [])).strip()
        _fin_u = _fin.upper()
        _tops = _mp.get("textual_operations") or []
        if isinstance(_tops, str):
            _tops = [_tops]

        if "POWDER" in _fin_u:
            _powder_ok[_pn] = True
        elif any(_h in _fin_u for _h in _POWDER_POINTER_HINTS):
            _powder_ok[_pn] = _assembly_is_powder
            if _assembly_is_powder:
                _flag(f"{_pn}: finish is a POINTER ('{_fin[:38]}') — resolved to POWDER "
                      f"from the assembly drawing.", flags)
            else:
                _flag(f"{_pn}: finish points to the assembly drawing, but NO assembly page "
                      f"states a finish. DRAWING DEFECT — not coated, and not invented. "
                      f"Raise with Design.", flags)
        elif _fin_u:
            _powder_ok[_pn] = False      # RAW / SCRAPED EDGES / etc — explicit
        else:
            _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match for the powder gate, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{OLD}\n")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_powderptr_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  powder gate now reads the drawing finish and follows SEE ASSEMBLY pointers")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 FIRST — it has a manual, so it is the only one we can validate against.

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\1310 Drill Stud Holder (Rev C)" --folder-as-job

EXPECT:
  * flags: "1310-01: finish is a POINTER — resolved to POWDER from the assembly drawing"
           and the same for 1310-02
  * NO MORE "dropped powder on 1310-01 / 1310-02"
  * a P.Coat labour row appears                         (Tim: £2.00)
  * powder material rises from £0.06                    (Tim: £0.30)

  If P.Coat lands near Tim's £2.00 -> the fix is right and the pointer is resolved.
  If P.Coat lands near £10.81 -> the pointer resolution is STILL RIGHT (the drawing says
  powder), but the KNOWN flat-P.Coat rate defect is now visible on this job too. Report it
  as such. Do not blame this fix for a defect it merely revealed.

THEN 1282 (qty 10). THE ANCHOR WILL MOVE — expected, and correct:
  * five parts gain P.Coat: 1448-01, 1448-02, 3886-02, 3886-03, 1455-C-101
  * roughly £278.93 -> ~£333 at the flat rate
  * 1282 has NO manual, so this number cannot be validated. It is right in KIND (the
    assembly says POWDER COATED, RAL3020 TRAFFIC RED) but its MAGNITUDE depends on the
    flat-P.Coat defect, which is still open.
  * RAW parts (1455-C-001..004) and the acrylic lens must STILL be dropped. If they gain
    powder, the gate has over-reached — revert.
""")


if __name__ == "__main__":
    main()
