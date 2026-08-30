L = open(r"C:\ClaudeVision\src\dxf_reader.py", encoding="utf-8").read().splitlines()
import re
for i, ln in enumerate(L):
    if re.search(r"cut_len|blank|LWPOLYLINE|polygonize|unary_union|\.length|bounding|LINE|ARC|CIRCLE|closed", ln):
        print(f"{i+1}: {ln.rstrip()}")
