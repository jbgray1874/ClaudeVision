"""READ-ONLY. Print the exact current text of the two regions I'll edit in
bought_in_recogniser.py, so the str_replace anchors match byte-for-byte.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _get_edit_anchors.py"""
from pathlib import Path
lines = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py").read_text(encoding="utf-8", errors="replace").splitlines()
print("### ANCHOR A: _MIN_TOKEN line + _norm (where the electrical vocab constant goes after) ###")
for i in range(78, 94):
    print(f"{i+1:4}|{lines[i]}")
print("\n### ANCHOR B: line 277-282 (ref.vocab guard + scan setup) ###")
for i in range(276, 303):
    print(f"{i+1:4}|{lines[i]}")
print("\n### ANCHOR C: best_priced_match signature 196-207 ###")
for i in range(195, 208):
    print(f"{i+1:4}|{lines[i]}")
