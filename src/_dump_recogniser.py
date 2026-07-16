"""READ-ONLY. Print the complete real bought_in_recogniser.py so it can be edited
verbatim (not reconstructed). Run:
C:\ClaudeVision\.venv\Scripts\python.exe _dump_recogniser.py > recogniser_dump.txt
then open recogniser_dump.txt, OR just run it and copy the output."""
from pathlib import Path
p = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py")
text = p.read_text(encoding="utf-8", errors="replace")
print(f"### {p} : {len(text.splitlines())} lines ###")
print(text)
