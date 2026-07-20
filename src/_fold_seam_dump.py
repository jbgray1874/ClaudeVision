L = open(r"C:\ClaudeVision\src\estimator.py", encoding="utf-8").read().splitlines()
# dump 2140-2160 verbatim (the folding seam) and confirm the guard vars exist in the function
for i in range(2139, 2160):
    if i < len(L):
        print(f"{i+1}|{L[i]!r}")
print("\n--- confirm guard vars in scope (search upward from 2150 within the function) ---")
import re
# find nearest preceding assignments of _mat_u, _SHEET_METALS use, _section_no_dxf, bends, bend_length_mm
for var in (r"_mat_u\s*=", r"_SHEET_METALS", r"_CUT_BOARDS", r"_section_no_dxf\s*=", r"\bbends\s*=", r"bend_length_mm\s*="):
    last=None
    for i in range(0, 2160):
        if i < len(L) and re.search(var, L[i]):
            last=(i+1, L[i].strip()[:110])
    print(f"  {var:<22}: {last}")
