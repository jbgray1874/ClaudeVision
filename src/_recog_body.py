"""READ-ONLY. Dump recognise_bought_in_in_prose body + the pricing/match helpers
(lines ~237-400) so the electrical vocabulary plugs into the real match+price path.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _recog_body.py"""
from pathlib import Path
lines = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py").read_text(encoding="utf-8", errors="replace").splitlines()
for i in range(236, min(400, len(lines))):
    print(f"{i+1:4}: {lines[i]}")
