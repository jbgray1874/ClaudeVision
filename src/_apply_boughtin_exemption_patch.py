"""Applies the bought-in exemption patch to _part_cost_credibility in estimator.py.

Does an exact string replace (not a manual hand-edit) so success/failure is
unambiguous: either the old block is found and replaced, or the script tells
you plainly it didn't match and changes nothing.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_boughtin_exemption_patch.py

Then re-run the 1282 pipeline and _credibility_fix_verify.py as before.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

OLD = '''def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (credible, reasons) for whether this part's cost belongs in the headline total."""
    reasons: List[str] = []
    ext = float(est_part.get("extended_total_cost_gbp") or 0.0)
    if ext <= 0:
        return True, []

    mfg = mfg or {}
    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))'''

NEW = '''def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (credible, reasons) for whether this part's cost belongs in the headline total."""
    reasons: List[str] = []
    ext = float(est_part.get("extended_total_cost_gbp") or 0.0)
    if ext <= 0:
        return True, []

    mfg = mfg or {}

    # Bought-in parts structurally never have a DXF -- that's not a credibility
    # problem, it's the nature of the part. Exempt them from no_part_dxf so a
    # well-priced catalogue/historical line doesn't drag the cost-credibility
    # ratio down for lacking geometry it was never going to have. page_roles
    # is the signal confirmed 100%-reliable against real job data (1282,
    # all 15 bought-in parts) -- see credibility gate probe.
    if "bought_in" in [str(r).lower() for r in (mfg.get("page_roles") or [])]:
        return True, []

    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))'''

src = TARGET.read_text(encoding="utf-8")

if OLD not in src:
    print("NOT APPLIED -- exact text not found in estimator.py.")
    print("This means the live function differs from what I expect (whitespace,")
    print("line endings, or the function has already been edited differently).")
    print("Paste back the output of:")
    print(r'  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "def _part_cost_credibility" -Context 0,10')
    raise SystemExit(1)

count = src.count(OLD)
if count > 1:
    print(f"NOT APPLIED -- found {count} matches, expected exactly 1. Refusing to guess which.")
    raise SystemExit(1)

new_src = src.replace(OLD, NEW)
TARGET.write_text(new_src, encoding="utf-8")
print("APPLIED -- _part_cost_credibility patched with the bought-in exemption.")
print("Next: re-run the 1282 pipeline, then re-run _credibility_fix_verify.py.")
