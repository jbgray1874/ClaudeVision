L = open(r"C:\ClaudeVision\src\wb_populate.py", encoding="utf-8").read().splitlines()
import re
for i, ln in enumerate(L):
    if re.search(r"coated|powder|m2|blank_area|POWDER_KG|coat_area|surface", ln, re.I):
        print(f"{i+1}: {ln.strip()[:140]}")
