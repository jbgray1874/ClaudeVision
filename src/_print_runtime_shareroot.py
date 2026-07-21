r"""READ-ONLY. Deployed helper returns None but share isdir=True + logic finds 4. Prime suspect:
the raw-string share_root has DOUBLED backslashes (r"\\\\sdi-dc01\\..." = 4 leading + doubled),
which isdir may tolerate but GLOB won't resolve. Print the EXACT runtime value from the deployed
module and test isdir AND glob on it, vs the correct path. This pins the escaping bug. No edits."""
import sys, os, glob, importlib, re
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

# read the literal straight from source (bytes-accurate)
src=open(os.path.join(SRC,"main.py"),encoding="utf-8").read()
m=re.search(r"def _find_manual_workbook.*?share_root\s*=\s*(r?)(['\"])(.+?)\2", src, re.S)
if m:
    is_raw = m.group(1)=="r"
    literal = m.group(3)
    print("="*66); print("share_root as written in source"); print("="*66)
    print(f"  raw string?: {is_raw}")
    print(f"  literal chars (repr): {literal!r}")
    # reconstruct the ACTUAL runtime value
    if is_raw:
        runtime = literal  # raw: backslashes literal as-is
    else:
        runtime = literal.encode().decode('unicode_escape')  # non-raw: process escapes
    print(f"  RUNTIME value (repr): {runtime!r}")
    print(f"  runtime leading chars: {runtime[:12]!r}")
    print(f"\n  isdir(runtime) = {os.path.isdir(runtime)}")
    g = glob.glob(os.path.join(runtime, '20*'))
    print(f"  glob(runtime\\20*) hits = {len(g)}   {[os.path.basename(x) for x in g][:5]}")

    correct = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
    print(f"\n  CORRECT value (repr): {correct!r}")
    print(f"  isdir(correct) = {os.path.isdir(correct)}")
    gc = glob.glob(os.path.join(correct, '20*'))
    print(f"  glob(correct\\20*) hits = {len(gc)}   {[os.path.basename(x) for x in gc][:5]}")

    print("\n"+"="*66); print("VERDICT"); print("="*66)
    if runtime != correct:
        print(f"  MISMATCH — deployed runtime share_root is WRONG.")
        print(f"    deployed: {runtime!r}")
        print(f"    correct : {correct!r}")
        print("  -> This is the escaping bug. Fix: replace with the correct raw literal r'\\\\sdi-dc01\\...'.")
    else:
        print("  runtime == correct — so the bug is elsewhere; run the instrumented patch.")
else:
    print("couldn't extract share_root from source")
