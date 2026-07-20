# Read-only: dump the live powder-area loop verbatim + find where _sl/_sw come from.
L = open(r"C:\ClaudeVision\src\wb_populate.py", encoding="utf-8").read().splitlines()

print("=== powder-area region (lines 494-521) verbatim ===")
for i in range(493, 522):
    if i < len(L):
        print(f"{i+1}|{L[i]!r}")

import re
print("\n=== _sl / _sw / _sq assignments (the L/W the powder loop reads) ===")
for i, ln in enumerate(L):
    if re.search(r"_sl\s*=|_sw\s*=|_sq\s*=|_sl,\s*_sw|blank_length_mm|blank_width_mm|blank_area_mm2", ln):
        print(f"{i+1}: {ln.strip()[:150]}")

print("\n=== the loop header that iterates parts for powder (look for 'for' near 494-515) ===")
for i in range(490, 520):
    if i < len(L) and ("for " in L[i] or "in " in L[i]):
        print(f"{i+1}: {L[i].strip()[:150]}")
