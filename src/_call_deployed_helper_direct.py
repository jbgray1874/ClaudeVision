r"""READ-ONLY, FAST (no populate). Import the ACTUAL deployed _find_manual_workbook from main.py and
call it with the exact args the run used — to settle in SECONDS whether the deployed code finds
1282's manual. If it FINDS it here, the run's 'no manual found' was environmental (share hiccup
during that run) and the CODE is fine. If it MISSES here, the deployed code has a real bug.
No full run needed. No edits."""
import sys, os, json
SRC=r"C:\ClaudeVision\src"
sys.path.insert(0, SRC)

# import main WITHOUT running it (main() is under if __name__=='__main__')
import importlib
try:
    main_mod = importlib.import_module("main")
except Exception as e:
    print(f"couldn't import main.py: {type(e).__name__}: {e}")
    # some main.py run code at import — if so, fall back to exec-extract just the helper
    raise SystemExit

helper = getattr(main_mod, "_find_manual_workbook", None)
if helper is None:
    print("_find_manual_workbook not importable from main.py")
    raise SystemExit

# load the real 1282 summary (as the run would have)
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
summary = json.loads(open(JP,encoding="utf-8").read())

print("="*66); print("calling deployed _find_manual_workbook DIRECTLY"); print("="*66)
result = helper("1282 - Milwaukee Wall Bay", summary)
print(f"\n  RESULT: {result!r}")
if result:
    print("\n  -> Deployed helper FINDS the manual when called directly.")
    print("     => The run's 'no manual found' was ENVIRONMENTAL (share momentarily unreachable")
    print("        during that long run). The CODE is correct. Just re-run --deliverables when the")
    print("        share is reachable, or add a retry. NOTHING to fix in the logic.")
else:
    print("\n  -> Deployed helper MISSES even when called directly.")
    print("     => Real bug in deployed code. The instrumented patch will show which check fails.")

# quick share reachability check right now
share=r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
print(f"\n  share reachable now: {os.path.isdir(share)}")
