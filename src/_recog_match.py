"""READ-ONLY. Dump best_priced_match + _sig_token_set + the vocab-mining tail (lines ~85-236)
so the electrical vocab is added at the right place with the right matching behaviour.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _recog_match.py"""
from pathlib import Path
lines = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py").read_text(encoding="utf-8", errors="replace").splitlines()
for i in range(84, 237):
    print(f"{i+1:4}: {lines[i]}")
