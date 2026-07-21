r"""
patch_quote_svg_sizing.py — fix both logo bugs in client_quote_html.py.

ROOT CAUSE (diagnosed): the logo SVGs carry native width="1224" height="1224". A CSS max-height on
the wrapper <span> does NOT constrain an inline SVG that declares its own width/height — the SVG
renders at 1224px. So the SDI logo is massive AND the (correctly-found) Milwaukee logo renders
huge/overlapping and appears absent. The Bodycare template avoids this by putting an explicit small
size on the <svg> tag itself.

FIX: add a helper that rewrites the opening <svg ...> tag — strips any existing width/height and
injects a fixed pixel size (keeping viewBox so it scales correctly) — and route both the SDI logo
and customer-logo SVG paths through it. SDI -> 52px; customer -> height 34px (width auto via
viewBox, capped by removing the fixed width). Match-or-refuse, AST-validated, timestamped backup.
"""
import re, ast, shutil, datetime, os

T = r"C:\ClaudeVision\src\client_quote_html.py"

# 1) Insert a _size_svg helper just before _load_logo_markup
ANCHOR_HELPER = "def _load_logo_markup(customer: str) -> str:"
HELPER = '''def _size_svg(svg_markup: str, *, height_px: int, width_px: Optional[int] = None) -> str:
    """Force an inline SVG to a fixed display size. A CSS max-height does NOT constrain an SVG that
    declares its own width/height, so we rewrite the opening <svg> tag: drop existing width/height
    and inject fixed ones (viewBox is preserved so it scales correctly)."""
    m = re.search(r"<svg\\b[^>]*>", svg_markup, re.I | re.S)
    if not m:
        return svg_markup
    tag = m.group(0)
    # strip any existing width/height attributes
    tag2 = re.sub(r'\\s(width|height)="[^"]*"', "", tag, flags=re.I)
    # build the size attrs: always height; width only if given (else auto via viewBox)
    size_attr = f' height="{height_px}"'
    if width_px is not None:
        size_attr = f' width="{width_px}"' + size_attr
    tag2 = tag2[:-1] + size_attr + ' style="height:%dpx;width:auto;display:block;" >' % height_px
    return svg_markup.replace(tag, tag2, 1)


def _load_logo_markup(customer: str) -> str:'''

# 2) In _load_logo_markup: size the customer SVG (height 34) instead of raw inner
OLD_CUST = '''                m = re.search(r"<svg\\b.*?</svg>", svg, re.S | re.I)
                inner = m.group(0) if m else svg
                # constrain display size
                return f'<span style="display:inline-flex;align-items:center;max-height:34px;">{inner}</span>\''''
NEW_CUST = '''                m = re.search(r"<svg\\b.*?</svg>", svg, re.S | re.I)
                inner = _size_svg(m.group(0) if m else svg, height_px=34)
                return f'<span style="display:inline-flex;align-items:center;">{inner}</span>\''''

# 3) In _sdi_logo_markup: size the SDI SVG (52px) instead of raw inner
OLD_SDI = '''                m = re.search(r"<svg\\b.*?</svg>", svg, re.S | re.I)
                inner = m.group(0) if m else svg
                return f'<span style="display:inline-flex;align-items:center;">{inner}</span>\''''
NEW_SDI = '''                m = re.search(r"<svg\\b.*?</svg>", svg, re.S | re.I)
                inner = _size_svg(m.group(0) if m else svg, height_px=52)
                return f'<span style="display:inline-flex;align-items:center;">{inner}</span>\''''

def apply():
    src = open(T, encoding="utf-8").read()

    # OLD_SDI and OLD_CUST differ only by the trailing comment line, so OLD_SDI's pattern would also
    # match inside _load_logo_markup if we're not careful. Do the customer replace FIRST (it has the
    # unique comment line), then the SDI replace (now unique), then insert the helper.
    steps = [
        ("customer svg sizing", OLD_CUST, NEW_CUST),
        ("sdi svg sizing", OLD_SDI, NEW_SDI),
        ("insert _size_svg helper", ANCHOR_HELPER, HELPER),
    ]
    for name, old, new in steps:
        n = src.count(old)
        if n != 1:
            print(f"REFUSE at '{name}': anchor found {n} times (need 1). No changes written.")
            return False
        src = src.replace(old, new, 1)

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"REFUSE: patched file fails AST parse: {e}. No changes written.")
        return False

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_svgsize_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(src)
    print(f"OK: both logo SVGs now size-capped (SDI 52px, customer 34px). Backup: {os.path.basename(bak)}")
    return True

if __name__ == "__main__":
    apply()
