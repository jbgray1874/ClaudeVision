r"""READ-ONLY. geometry_inference has NO llm but produces area -> that path is deterministic.
file_scan has llm=True AND touches area -> prime suspect for the material drift. Show file_scan's
LLM call config: is temperature=0? is there a seed? What does the LLM produce that could affect
area/material (material classification? dimensions? thickness?). Also check if note-scan (the one we
hardened) is the same call or a different one. No edits — pinpoint the unseeded call."""
import os, re
p=r"C:\ClaudeVision\src\file_scan.py"
txt=open(p,encoding="utf-8",errors="replace").read()
L=txt.splitlines()

# find every LLM invocation and show surrounding config lines
print("="*66); print("LLM calls in file_scan.py + their params"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(messages\.create|chat\.completions|client\.chat|\.invoke\(|responses\.create)", ln, re.I):
        lo=max(0,i-2); hi=min(len(L),i+18)
        print(f"\n  --- call at line {i+1} ---")
        for j in range(lo,hi):
            mark=">>" if j==i else "  "
            if re.search(r"(temperature|seed|model|max_tokens|reasoning|top_p|messages\.create|\.invoke|responses\.create|def )", L[j], re.I):
                print(f"  {mark}{j+1}: {L[j].strip()[:96]}")

# is temperature/seed set ANYWHERE in file_scan?
print("\n"+"="*66); print("determinism knobs present in file_scan.py?"); print("="*66)
print("  temperature=0 :", bool(re.search(r"temperature\s*=\s*0",txt)))
print("  any temperature:", bool(re.search(r"temperature\s*=",txt)))
print("  seed=         :", bool(re.search(r"seed\s*=",txt)))
for i,ln in enumerate(L):
    if re.search(r"(temperature|seed)\s*=",ln,re.I):
        print(f"    {i+1}: {ln.strip()[:90]}")

# what does the LLM output feed? look for what the response is used for near the calls
print("\n"+"="*66); print("what the LLM output feeds (material? thickness? dims?)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(material|thickness|dimension|blank|area|width|length)", ln, re.I) and re.search(r"(response|completion|result|llm|parsed|json\.loads)", ln, re.I):
        print(f"    {i+1}: {ln.strip()[:96]}")

# note-scan hardening — is it a separate function? (we hardened note-scan before)
print("\n"+"="*66); print("note-scan function (the one we hardened) vs other LLM calls"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"def .*note|note_scan|scan_note|def .*llm", ln, re.I):
        print(f"    {i+1}: {ln.strip()[:90]}")
