"""READ-ONLY. Dump job_decision_report.py to a UTF-8 file (avoids the cp1252 console
crash on emoji). Then open the .txt and paste it, OR just paste from the file.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _dump_jdr.py
Then: notepad C:\ClaudeVision\src\jdr_dump.txt"""
import io
from pathlib import Path
src = Path(r"C:\ClaudeVision\src\job_decision_report.py").read_text(encoding="utf-8", errors="replace")
out = Path(r"C:\ClaudeVision\src\jdr_dump.txt")
with io.open(out, "w", encoding="utf-8") as f:
    f.write(src)
print(f"Wrote {len(src.splitlines())} lines to {out}")
print("Open with: notepad C:\\ClaudeVision\\src\\jdr_dump.txt")
