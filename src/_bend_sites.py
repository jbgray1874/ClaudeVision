# Dump the exact live bytes of every bend_count read in estimator.py, verbatim (repr),
# so the fix keys precisely. Three known sites: ~1185, ~1240, ~1975.
L = open(r"C:\ClaudeVision\src\estimator.py", encoding="utf-8").read().splitlines()
import re
print("=== all lines reading bend_count / angles_deg / fold_values_mm / fold_count_textual ===")
for i, ln in enumerate(L):
    if re.search(r"bend_count|angles_deg|fold_values_mm|fold_count_textual", ln):
        print(f"{i+1}|{ln!r}")
