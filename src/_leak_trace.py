r"""
_leak_trace.py — READ-ONLY. Two general checks, no part numbers:

1. FOLD_PATTERN generality: dump the actual regex(es) so we confirm fold detection keys
   on the CLASS (UP|DOWN)+angle, not a list of specific callouts.

2. Net-area -> powder leak path: find every place blank_area_mm2 / blank_length_mm /
   blank_width_mm are WRITTEN (not just read), especially any code that DERIVES one
   dimension from area (e.g. width = area / length). That derivation is the suspected
   bridge by which the shapely net-area change reached the powder loop (which reads L x W).
   General: we look at the field-flow, not at 1282.
"""
import os, re
root = r"C:\ClaudeVision\src"

print("="*70)
print("1. FOLD_PATTERN / FOLD_VALUE_PATTERN — is it a CLASS or a list?")
print("="*70)
for fn in ("extractor_patterns.py",):
    p = os.path.join(root, fn)
    if not os.path.exists(p):
        print("  (extractor_patterns.py not found)"); continue
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    for i, ln in enumerate(L):
        if re.search(r"FOLD_PATTERN|FOLD_VALUE_PATTERN|UP\|DOWN|DOWN\|UP|_PATTERN\s*=.*(fold|bend|angle)", ln, re.I):
            # print the assignment and a couple following lines (regex may wrap)
            print(f"  {i+1}: {ln.strip()[:160]}")

print("\n" + "="*70)
print("2. WRITES to blank_area_mm2 / blank_length_mm / blank_width_mm  (the leak surface)")
print("="*70)
WRITE = re.compile(r"""(\[["']blank_(area_mm2|length_mm|width_mm)["']\]\s*=|"""
                   r"""["']blank_(area_mm2|length_mm|width_mm)["']\s*:|"""
                   r"""\.update\(|blank_(length|width)_mm\s*=\s*.*area|"""
                   r"""(width|length).*=\s*.*area\s*/|"""
                   r"""=\s*.*blank_area)""", re.I)
DERIVE = re.compile(r"(width|length|_w|_l)\s*=\s*[^=].*?(area|/\s*)", re.I)
for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py") or fn.startswith("_"): continue
    if fn.endswith((".backup.py",".bak")): continue
    p = os.path.join(root, fn)
    try:
        L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        continue
    hits = []
    for i, ln in enumerate(L):
        s = ln.strip()
        # writes of the three fields, OR any dimension derived from area
        if re.search(r'blank_(area_mm2|length_mm|width_mm)', s):
            if ('=' in s and 'get(' not in s.split('=')[0]) or '":' in s or "':" in s or '.update' in s:
                hits.append((i+1, s))
        if re.search(r'\b(blank_width_mm|blank_length_mm|_wid|_len|width|length)\b\s*=', s) and re.search(r'area|sqrt|/\s*\b(_?l|_?w|length|width)\b', s, re.I):
            hits.append((i+1, "DERIVE? "+s))
    if hits:
        print(f"\n  ---- {fn} ----")
        for ln_no, s in hits[:18]:
            print(f"    {ln_no}: {s[:150]}")

print("\n" + "="*70)
print("3. geometry_inference.py — does it BACK-DERIVE L/W (the prime suspect)?")
print("="*70)
p = os.path.join(root, "geometry_inference.py")
if os.path.exists(p):
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    for i, ln in enumerate(L):
        if re.search(r"blank_(length|width|area)|=\s*.*sqrt|=\s*.*area\s*/|width\s*=|length\s*=|aspect", ln, re.I):
            print(f"  {i+1}: {ln.strip()[:150]}")
