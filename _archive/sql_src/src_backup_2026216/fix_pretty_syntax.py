"""Fix SyntaxError in estimate_parity_pretty_report.py (broken ai_parts comprehension)."""
import py_compile
import re
from pathlib import Path

p = Path(__file__).resolve().parent / "estimate_parity_pretty_report.py"
text = p.read_text(encoding="utf-8")

pattern = re.compile(
    r"    ai_parts = \[\n"
    r"        p for p in parts\n"
    r"        ps = p\.get\(\"price_source\"\).*?\n"
    r"        if str\(ps\.get\(\"source_type\"\).*?\n"
    r"    \]",
    re.DOTALL,
)

replacement = """    ai_parts = []
    for p in parts:
        ps = p.get("price_source") or (p.get("material_estimate") or {}).get("price_source") or {}
        src = str(ps.get("source_type") or ps.get("source") or "").lower()
        if src in {"web_ai_fallback", "web_search", "llm_market_estimate"}:
            ai_parts.append(p)"""

new_text, n = pattern.subn(replacement, text, count=1)
if n == 0:
    # already fixed or different layout
    if "ai_parts.append(p)" in text:
        print("already fixed")
    else:
        raise SystemExit("Could not find broken ai_parts block — edit manually around line 683")
else:
    p.write_text(new_text, encoding="utf-8")
    print(f"patched {p} ({n} replacement)")

py_compile.compile(str(p), doraise=True)
print("py_compile OK")
