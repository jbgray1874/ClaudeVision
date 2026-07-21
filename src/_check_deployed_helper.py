r"""READ-ONLY. Verify the DEPLOYED _find_manual_workbook in main.py — specifically that the
share_root string literal is correct (the patch escaped backslashes; escaping bugs would produce a
wrong path -> os.path.isdir False -> 'no manual found'). Show the deployed helper verbatim so I can
see the exact share_root and glob it uses. No edits."""
import re
p=r"C:\ClaudeVision\src\main.py"
src=open(p,encoding="utf-8",errors="replace").read()
m=re.search(r"def _find_manual_workbook\b.*?(?=\ndef )", src, re.S)
if m:
    print("DEPLOYED _find_manual_workbook (verbatim):")
    print("-"*70)
    for ln in m.group(0).splitlines():
        print(ln)
    print("-"*70)
    # extract and TEST the actual share_root literal
    sr=re.search(r'share_root\s*=\s*r?["\'](.+?)["\']', m.group(0))
    if sr:
        import os
        lit=sr.group(1)
        print(f"\n  share_root literal in code: {lit!r}")
        # rebuild the actual runtime string (handle raw vs escaped)
        print(f"  os.path.isdir(that) = {os.path.isdir(lit)}")
        good=r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
        print(f"  known-good path      = {good!r}")
        print(f"  isdir(known-good)   = {os.path.isdir(good)}")
        print(f"  MATCH: {lit == good}")
        if lit != good:
            print("  *** share_root literal is WRONG (escaping bug from the patch). That's why the")
            print("      helper returned None. Fix: correct the share_root string in main.py. ***")
else:
    print("_find_manual_workbook NOT FOUND in main.py")
