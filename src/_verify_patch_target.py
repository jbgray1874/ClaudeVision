"""READ-ONLY. Verify the applier's OLD block matches the LIVE _part_cost_credibility
before running the applier, so it succeeds first try instead of refusing.

Prints:
  - the live function's first ~15 lines verbatim (with repr on key lines so we can
    see exact whitespace / line endings)
  - whether the applier's expected OLD block is present byte-for-byte
  - whether the exemption is ALREADY there (idempotency guard)
  - confirms which file main.py imports (estimator vs estimator_)
"""
import re, io
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src")
EST = SRC / "estimator.py"
txt = EST.read_text(encoding="utf-8", errors="replace")

# the applier's expected OLD block
OLD = (
    'def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:\n'
    '    """Return (credible, reasons) for whether this part\'s cost belongs in the headline total."""\n'
    '    reasons: List[str] = []\n'
    '    ext = float(est_part.get("extended_total_cost_gbp") or 0.0)\n'
    '    if ext <= 0:\n'
    '        return True, []\n'
    '    mfg = mfg or {}\n'
    '    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))'
)

print("=" * 80)
print("A. Is the exemption ALREADY present? (idempotency)")
print("=" * 80)
already = "Bought-in parts structurally never have a DXF" in txt
print(f"  exemption comment present: {already}  "
      + ("-> already patched, do NOT re-apply" if already else "-> not yet applied"))

print("\n" + "=" * 80)
print("B. Does the applier's OLD block match byte-for-byte?")
print("=" * 80)
print(f"  exact OLD block found: {OLD in txt}  (count={txt.count(OLD)})")

print("\n" + "=" * 80)
print("C. The LIVE function verbatim (first 16 lines) — repr shows exact whitespace")
print("=" * 80)
m = re.search(r"def _part_cost_credibility\b.*", txt)
if m:
    start = txt[:m.start()].count("\n") + 1
    lines = txt.splitlines()
    for i in range(start - 1, min(start + 15, len(lines))):
        # repr on the first ~9 lines so whitespace/quote style is visible
        show = repr(lines[i]) if (i - start) < 9 else lines[i]
        print(f"  {i+1:5}: {show}")
else:
    print("  def _part_cost_credibility NOT FOUND — is it in estimator_.py instead?")
    est_ = SRC / "estimator_.py"
    if est_.exists() and "_part_cost_credibility" in est_.read_text(encoding='utf-8', errors='replace'):
        print("  -> FOUND in estimator_.py — patch THAT file if it's the imported one.")

print("\n" + "=" * 80)
print("D. Which estimator does main.py import?")
print("=" * 80)
mp = (SRC / "main.py")
if mp.exists():
    for i, l in enumerate(mp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if re.search(r"^\s*(from|import)\s+estimator", l):
            print(f"  main.py:{i}: {l.strip()}")

print("\n" + "=" * 80)
print("VERDICT")
print("=" * 80)
if already:
    print("  Exemption already applied — skip the applier, just re-run 1282 + verify.")
elif OLD in txt and txt.count(OLD) == 1:
    print("  SAFE TO RUN THE APPLIER — OLD block matches exactly, single occurrence.")
else:
    print("  DO NOT RUN THE APPLIER AS-IS — OLD block does not match the live text.")
    print("  Use the verbatim lines in section C to correct the applier's OLD string first.")
