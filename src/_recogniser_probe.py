"""READ-ONLY. Dump the real bought_in_recogniser.py structure so we can extend its
vocabulary to catch the electrical BOM items (junction box, mains cable, earth strap,
LED link light, GU10 downlight) deterministically instead of via the LLM backstop.

Prints: the module source (or key parts), its vocabulary/keyword list, and the function
signature of recognise_bought_in_in_prose.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _recogniser_probe.py
"""
import inspect, re
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py")
if not SRC.exists():
    print(f"NOT FOUND: {SRC}")
    # try to import and locate
    try:
        import bought_in_recogniser as m
        print("module file:", m.__file__)
        SRC = Path(m.__file__)
    except Exception as e:
        print("import failed:", e)
        raise SystemExit

text = SRC.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()
print(f"=== {SRC.name}: {len(lines)} lines ===\n")

# 1. Show all top-level def/class and any UPPERCASE vocab constants
print("--- top-level defs / classes / vocab constants ---")
for i, ln in enumerate(lines, 1):
    if re.match(r"^(def |class |[A-Z_]{3,}\s*[:=])", ln):
        print(f"  {i:4}: {ln[:100]}")

# 2. Dump anything that looks like the vocabulary (lists/dicts/tuples of terms)
print("\n--- lines mentioning electrical / bought-in vocab terms ---")
for i, ln in enumerate(lines, 1):
    u = ln.upper()
    if any(t in u for t in ("STRAP", "LOOM", "CLIP", "CABLE", "TIE", "JUNCTION",
                            "EARTH", "LED", "DOWNLIGHT", "GU10", "MAINS", "RIVET",
                            "VOCAB", "KEYWORD", "_TERMS", "_MAP", "component")):
        print(f"  {i:4}: {ln.strip()[:110]}")

# 3. Signature of the main function
print("\n--- recognise_bought_in_in_prose signature ---")
try:
    import bought_in_recogniser as m
    print("  " + str(inspect.signature(m.recognise_bought_in_in_prose)))
except Exception as e:
    print("  (import for signature failed:", e, ")")
