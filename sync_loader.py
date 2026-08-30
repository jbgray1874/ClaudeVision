"""One-shot: copy Codex load_historical_quotes.py into src/. Run from C:\\ClaudeVision."""
import shutil
from pathlib import Path

SRC = Path(
    r"C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\src\load_historical_quotes.py"
)
DST = Path(__file__).resolve().parent / "src" / "load_historical_quotes.py"
shutil.copy2(SRC, DST)
print(f"Copied {SRC.stat().st_size} bytes -> {DST}")
assert "historical_quote_material_line" in DST.read_text(encoding="utf-8")
