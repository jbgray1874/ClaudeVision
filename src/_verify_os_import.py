r"""READ-ONLY. We just hit NameError:os from a missing import. The 300-DPI patch uses os.getenv —
verify os IS imported at module level in vision_extraction.py BEFORE applying, so we don't repeat
the bug. Show the top-of-file imports. No edits."""
import re
p=r"C:\ClaudeVision\src\vision_extraction.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()
print("top-of-file imports (first 40 lines):")
for i in range(min(40,len(L))):
    if re.match(r"\s*(import|from)\s", L[i]):
        print(f"  {i+1}: {L[i].strip()}")
# explicit check
src="\n".join(L)
has_os = bool(re.search(r"^import os\b|^import .*\bos\b|^from os\b", src, re.M)) or "import os" in src
print(f"\n  'os' imported at module level: {has_os}")
# does the file ALREADY use os.getenv (line 61 did)? then it's fine
uses=[i+1 for i,ln in enumerate(L) if "os.getenv" in ln or "os.path" in ln or re.search(r"\bos\.",ln)]
print(f"  existing os.* usages at lines: {uses[:8]}")
if uses and not has_os:
    print("  *** os is USED but not imported at top?? then module-level relies on something else.")
elif has_os:
    print("  -> os is imported. The 300-DPI patch's os.getenv is SAFE.")
