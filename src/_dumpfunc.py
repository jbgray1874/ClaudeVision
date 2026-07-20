L = open(r"C:\ClaudeVision\src\dxf_reader.py.py", encoding="utf-8").read().splitlines()
import re
# find the function and print it verbatim (repr shows exact indentation)
start = next((i for i,l in enumerate(L) if l.strip().startswith("def _exact_perimeter_and_area")), None)
if start is None:
    print("NOT FOUND")
else:
    # print until the next top-level def
    i = start + 1
    end = len(L)
    while i < len(L):
        if L[i].startswith("def ") and not L[i].startswith("    "):
            end = i; break
        i += 1
    for j in range(start, end):
        print(f"{j+1}|{L[j]!r}")
