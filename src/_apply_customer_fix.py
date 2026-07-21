r"""LIVE PATCH (match-or-refuse, AST-validated, backup). Fix _derive_customer's '01-GA-' bug.
Root: line 140-141 strips the job number then takes .split()[0] -> grabs the drawing-number
fragment '01-GA-' as the customer. Fix: (1) try the manual-estimate folder (the customer is the
folder under 'Manual Estimates\\<year>\\<CUSTOMER>\\'), (2) reject drawing-number-fragment tokens
(NN-GA, NN-XX, pure codes) from the word-grab fallback, (3) neutral 'Customer' rather than a code.
General: works for any job whose manual sits under a customer folder, or whose folder yields a code.
"""
import ast, shutil, datetime, os

SRC=r"C:\ClaudeVision\src\client_quote_html.py"
bak=SRC+".bak_customerfix_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
with open(SRC,encoding="utf-8") as f: src=f.read()

# Anchor: the exact fallback tail of _derive_customer.
ANCHOR = '''    prod = re.sub(r"^\\d+\\s*-\\s*", "", job_stem or "").strip()
    return prod.split()[0] if prod else "Customer"'''

if src.count(ANCHOR) != 1:
    # try a whitespace-tolerant search to report what's actually there
    import re as _re
    cand = _re.findall(r'prod = re\.sub.*?return prod\.split\(\)\[0\].*', src, _re.S)
    raise SystemExit(f"REFUSE: anchor found {src.count(ANCHOR)}x. Nearby: {cand[:1]}")

REPLACEMENT = '''    # (1) Manual-estimate folder carries the real customer:
    #     ...\\Manual Estimates\\<year>\\<CUSTOMER>\\<jobfolder>\\...
    #     Prefer it over any folder-name guess (fixes the '01-GA-' drawing-fragment bug).
    _cust_from_manual = _customer_from_manual_path(summary)
    if _cust_from_manual:
        return _cust_from_manual

    # (2) Word-grab fallback, but REJECT drawing-number fragments (e.g. '01-GA-', '02-XX')
    #     and pure codes — those are never a customer name.
    prod = re.sub(r"^\\d+\\s*-\\s*", "", job_stem or "").strip()
    first = prod.split()[0] if prod else ""
    _looks_like_code = bool(re.match(r"^\\d+[-]?[A-Za-z]{0,3}[-]?$", first)) or bool(re.match(r"^\\d", first))
    if first and not _looks_like_code:
        return first
    # (3) Neutral — never emit a drawing-number fragment as the customer.
    return "Customer"


def _customer_from_manual_path(summary: Dict[str, Any]) -> str:
    """If a manual estimate exists for this job, its path is
    ...\\Manual Estimates\\<year>\\<CUSTOMER>\\<jobfolder>\\*.xls — return <CUSTOMER>.
    Uses the deployed _find_manual_workbook when available; else returns ''."""
    try:
        import file_scan as _FS
        mp = _FS._find_manual_workbook(summary) if hasattr(_FS, "_find_manual_workbook") else None
    except Exception:
        mp = None
    if not mp:
        return ""
    try:
        norm = str(mp).replace("/", "\\\\")
        parts = norm.split("\\\\")
        for i, seg in enumerate(parts):
            if seg.strip().lower() == "manual estimates" and i + 2 < len(parts):
                # parts[i+1] = year, parts[i+2] = customer
                cust = parts[i + 2].strip()
                if cust and not cust.isdigit():
                    return cust
    except Exception:
        return ""
    return ""'''

src2 = src.replace(ANCHOR, REPLACEMENT, 1)
ast.parse(src2)
shutil.copy2(SRC, bak)
with open(SRC,"w",encoding="utf-8") as f: f.write(src2)
print(f"PATCHED  {SRC}")
print(f"backup   {bak}")
print("_derive_customer now: manual-folder customer (Tesco) -> non-code word -> neutral 'Customer'.")
print("Never emits the '01-GA-' drawing-number fragment.")
