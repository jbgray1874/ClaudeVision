"""READ-ONLY. Dump how bought_in_recogniser prices a recognised item from historical
quotes, so the new electrical recogniser reuses the SAME pricing path (not a parallel one).
Shows the BoughtInReference class internals: how it loads priced descriptions and matches.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _recog_pricing_probe.py
"""
import re
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py")
text = SRC.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

# Show the BoughtInReference class body + the pricing/match part of recognise_...
def show_range(start_pat, n_after, title):
    print("=" * 72); print(title); print("=" * 72)
    for i, ln in enumerate(lines):
        if re.search(start_pat, ln):
            for j in range(i, min(i + n_after, len(lines))):
                print(f"  {j+1:4}: {lines[j]}")
            print()
            return
    print("  (pattern not found)\n")

# The mining/loading query (how historical prices get in)
show_range(r"def _mine|def load|read-only", 55, "1. How the reference mines/loads historical prices")
# The pricing lookup inside recognise_
show_range(r"price.*from history|priced|_priced|def _price|best.*match", 30, "2. Pricing / match logic")
# The class attributes
show_range(r"class BoughtInReference", 40, "3. BoughtInReference class body")
