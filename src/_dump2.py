L = open(r"C:\ClaudeVision\src\estimator.py", encoding="utf-8").read().splitlines()
for i, ln in enumerate(L):
    if "_pn_new" in ln and "match_idx" not in ln:
        for j in range(max(0, i-6), min(len(L), i+8)):
            print(f"{j+1}|{L[j]!r}")
        print("----")
