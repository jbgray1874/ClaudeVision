r"""
patch_wire_readback.py — wire the Excel-COM price readback into the populate run.

After wb_populate writes the .xlsx (and the Decision/Provenance sheets are added + saved at
main.py:706), open the populated .xlsx via Excel COM, read the REAL computed totals (Material/
Labour/Unit) and stamp them into the summary JSON's workbook_equivalent_pricing. This makes the
JSON match the spreadsheet, so every downstream consumer (parity, pricing_service, pricing_
variance, fallback writer) reports the authoritative price instead of the stale reconstruction.

STRICTLY ADDITIVE & FAILURE-ISOLATED: wrapped in try/except; on any failure (Excel busy, COM
error, no file) the run continues and the JSON keeps its existing WEP. The estimate output is
never affected — wb_populate already produced the correct spreadsheet.

Inserts AFTER line 707's success print, using xlsx_path (in scope) and the canonical JSON path
(saved_output_paths.json, same pattern used at line 572). Match-or-refuse on the exact anchor,
AST-validated, timestamped backup.
"""
import re, ast, shutil, datetime, os

TARGET = r"C:\ClaudeVision\src\main.py"

# Anchor: the end of the report-sheets try/except block (lines 706-709). Insert the readback
# as its OWN isolated block right after, so it runs whether or not report-sheets succeeded,
# and its own failure can't affect anything else.
ANCHOR = '''                _wb.save(str(xlsx_path))
                print(f"   -> Decision Report + AI Provenance sheets added")
            except Exception as _rep_exc:
                print(f"   -> Report sheets skipped: {_rep_exc}", flush=True)'''

REPLACEMENT = '''                _wb.save(str(xlsx_path))
                print(f"   -> Decision Report + AI Provenance sheets added")
            except Exception as _rep_exc:
                print(f"   -> Report sheets skipped: {_rep_exc}", flush=True)

        # ── Price read-back: stamp the REAL Excel-computed totals into the JSON ──
        # wb_populate writes Excel FORMULAS; the true unit cost is computed by Excel on load,
        # not in Python. The JSON's workbook_equivalent_pricing is a reconstruction that can
        # drift from the spreadsheet. Open the populated .xlsx via Excel COM, read the real
        # Material/Labour/Unit totals, and write them into the JSON so every consumer agrees.
        # Failure-isolated: any error leaves the JSON unchanged and never breaks the run.
        if xlsx_path:
            try:
                from wep_readback_from_xlsx import stamp_real_totals_into_json as _stamp_wep
                _canon_json = (summary.get("saved_output_paths") or {}).get("json")
                if _canon_json and Path(_canon_json).exists():
                    _stamp_wep(str(xlsx_path), str(_canon_json))
                else:
                    print("   [wep-readback] canonical JSON path not found — readback skipped.", flush=True)
            except Exception as _wep_exc:
                print(f"   [wep-readback] skipped ({_wep_exc}) — JSON unchanged, run continues.", flush=True)'''

def apply():
    src = open(TARGET, encoding="utf-8").read()
    n = src.count(ANCHOR)
    if n != 1:
        print(f"REFUSE: anchor found {n} times (need 1). main.py differs from what was read — aborting, no changes.")
        return False
    new = src.replace(ANCHOR, REPLACEMENT, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: patched main.py fails AST parse: {e}. No changes written.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = TARGET + f".bak_wepreadback_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(new)
    print(f"OK: readback wired into main.py. Backup: {os.path.basename(bak)}")
    print("Next populate run will stamp real Excel-computed totals into the JSON automatically.")
    return True

if __name__ == "__main__":
    apply()
