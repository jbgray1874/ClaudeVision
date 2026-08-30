L = open(r"C:\ClaudeVision\src\file_scan.py", encoding="utf-8").read().splitlines()
hit = next((i for i, ln in enumerate(L) if "resolve_effective_quantities" in ln), None)
if hit is None:
    print("NOT FOUND")
else:
    lo, hi = max(0, hit-8), min(len(L), hit+50)
    for i in range(lo, hi):
        print(f"{i+1}|{L[i]}")
