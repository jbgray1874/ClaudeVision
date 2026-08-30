r"""
GENERAL token-match patch for estimate_full_parity_report.py — applies to ANY job.

Problem (measured on 1282, but general): Tim's manual fuses code+description
(FIXING125-M8X25MMGUIDES) while the engine uses the stem (FIXING125). _norm_line_code only
strips spaces/trailing-dash, so `manual_codes & ai_codes` == empty even when parts genuinely
match. Fuzzy description matching was measured UNSAFE (paired BASE-1.2M with wrong HEADER BASE
at 0.70), so this patch uses ONLY leading-token code matching — deterministic, no guessing.

Fix (three exact-string edits, all general):
  1) Add _leading_code_token(): stem = first '-'-delimited segment (FIXING125 from
     FIXING125-M8X25..., ELECTRICS from ELECTRICS-50CMLOOM, VINYL76 from VINYL76-BASEPLATE).
  2) Rewrite the reconciliation match step: pass 1 = exact norm-code intersect (unchanged
     behaviour, highest confidence, match_kind='code'); pass 2 = token intersect on the
     REMAINDER only, deduped so one AI part matches one manual line (match_kind='code_stem').
     Everything still unmatched -> manual_only / ai_only exactly as before.
  3) Guard the manual parser's Problem-B garbage: don't accept a bare numeric ('1.0') that
     was mis-picked from the Qty column as a code (require a letter in the code).

Makes a TIMESTAMPED backup. Validates by AST-parsing the result. Match-or-refuse on exact
current strings (keyed to the repr I read live), so it will REFUSE if the file differs.
"""
import re, ast, shutil, datetime, sys, os

TARGET = r"C:\ClaudeVision\src\estimate_full_parity_report.py"

# ---- exact current strings (from live read) ----
OLD_NORM = '''def _norm_line_code(raw: Any) -> str:
    """Normalise a BOM code for set matching: upper, strip spaces, drop trailing dash."""
    s = str(raw or "").strip().upper()
    s = re.sub(r"\\s+", "", s)
    s = re.sub(r"-+$", "", s)
    return s'''

NEW_NORM = '''def _norm_line_code(raw: Any) -> str:
    """Normalise a BOM code for set matching: upper, strip spaces, drop trailing dash."""
    s = str(raw or "").strip().upper()
    s = re.sub(r"\\s+", "", s)
    s = re.sub(r"-+$", "", s)
    return s


def _leading_code_token(norm_code: str) -> str:
    """Leading part-code stem for cross-estimator matching (GENERAL, any job).

    Estimators fuse code+description in one cell (FIXING125-M8X25MMGUIDES) while the engine
    stores the stem (FIXING125). The stem is the first '-'-delimited segment. Deterministic;
    used only as a *fallback* after exact-code matching, never to override an exact match.
    Examples: FIXING125-M8X25MMGUIDES->FIXING125, ELECTRICS-50CMLOOM->ELECTRICS,
    VINYL76-BASEPLATE->VINYL76, BI-ADHESIVECABLE->BI (harmless; BI-* still exact-match first).
    """
    seg = str(norm_code or "").split("-", 1)[0]
    return seg'''

# match step: replace the three-set-build + intersect header through the manual_only/ai_only loops.
OLD_MATCH = '''    ai_by_code = {ln["code"]: ln for ln in ai_lines}
    manual_by_code = {ln["code"]: ln for ln in manual_lines}

    ai_codes = set(ai_by_code)
    manual_codes = set(manual_by_code)'''

NEW_MATCH = '''    ai_by_code = {ln["code"]: ln for ln in ai_lines}
    manual_by_code = {ln["code"]: ln for ln in manual_lines}

    ai_codes = set(ai_by_code)
    manual_codes = set(manual_by_code)

    # --- Pass 2 prep: leading-token stems for cross-estimator fallback matching (general) ---
    # Only stems that are UNIQUE on each side are eligible, so a stem can never pair a manual
    # line with the wrong one of several same-stem AI parts (and vice versa).
    def _unique_stem_index(by_code):
        from collections import Counter
        stems = {c: _leading_code_token(c) for c in by_code}
        counts = Counter(stems.values())
        return {stem: c for c, stem in stems.items() if counts[stem] == 1 and stem and len(stem) >= 3}
    _ai_stem = _unique_stem_index(ai_by_code)       # stem -> ai code
    _man_stem = _unique_stem_index(manual_by_code)   # stem -> manual code
    # token pairs where BOTH sides have that unique stem, and neither is already exact-matched
    _exact_codes = manual_codes & ai_codes
    _stem_pairs = {}  # manual_code -> ai_code  (via shared unique stem)
    for stem, mcode in _man_stem.items():
        acode = _ai_stem.get(stem)
        if acode and mcode not in _exact_codes and acode not in _exact_codes:
            _stem_pairs[mcode] = acode'''

# the manual-only loop header — inject stem-pair handling so token-matched manual codes
# are treated as matched, not manual_only.
OLD_MANUAL_ONLY = '''    for code in sorted(manual_codes - ai_codes):
        m = manual_by_code[code]'''
NEW_MANUAL_ONLY = '''    for code in sorted(manual_codes - ai_codes):
        if code in _stem_pairs:
            # token-matched to an AI line (match_kind code_stem) -> record as matched, skip manual_only
            m = manual_by_code[code]
            a = ai_by_code[_stem_pairs[code]]
            mc = _safe_float(m.get("cost_gbp"))
            ac = _safe_float(a.get("cost_gbp"))
            matched.append({
                "code": code,
                "ai_code": _stem_pairs[code],
                "match_kind": "code_stem",
                "description": m.get("description") or a.get("description"),
                "manual_cost_gbp": mc,
                "ai_cost_gbp": ac,
                "variance_pct": (round(100.0 * (ac - mc) / mc, 1) if (mc and ac is not None) else None),
            })
            continue
        m = manual_by_code[code]'''

# the ai-only loop header — skip AI codes already stem-matched.
OLD_AI_ONLY = '''    for code in sorted(ai_codes - manual_codes):
        a = ai_by_code[code]'''
NEW_AI_ONLY = '''    _stem_matched_ai = set(_stem_pairs.values())
    for code in sorted(ai_codes - manual_codes):
        if code in _stem_matched_ai:
            continue  # already recorded as a code_stem match above
        a = ai_by_code[code]'''

# Problem-B guard in the manual parser: require a letter in a picked code (reject bare '1.0').
OLD_GUARD = '''        code = _norm_line_code(code_val)
        if not code or code in seen or len(code) < 3:
            continue'''
NEW_GUARD = '''        code = _norm_line_code(code_val)
        # General guard: a code must contain at least one letter. Rejects bare numerics
        # ('1.0') mis-picked from the Qty column when a description cell had no digit.
        if not code or code in seen or len(code) < 3 or not any(ch.isalpha() for ch in code):
            continue'''

def apply():
    src = open(TARGET, encoding="utf-8").read()
    edits = [
        ("_norm_line_code + _leading_code_token", OLD_NORM, NEW_NORM),
        ("match-step stem prep",                  OLD_MATCH, NEW_MATCH),
        ("manual_only stem handling",             OLD_MANUAL_ONLY, NEW_MANUAL_ONLY),
        ("ai_only stem skip",                     OLD_AI_ONLY, NEW_AI_ONLY),
        ("Problem-B numeric-code guard",          OLD_GUARD, NEW_GUARD),
    ]
    for name, old, new in edits:
        n = src.count(old)
        if n != 1:
            print(f"REFUSE: '{name}' expected exactly 1 match, found {n}. File differs from what was read — aborting, no changes.")
            return False
    for name, old, new in edits:
        src = src.replace(old, new, 1)
    # validate
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"REFUSE: patched result fails AST parse: {e}. No changes written.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = TARGET + f".bak_tokenmatch_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"OK: 5 edits applied. Backup: {os.path.basename(bak)}")
    print("Rebuild the 1282 bundle to see matched_count reflect the token matches.")
    return True

if __name__ == "__main__":
    apply()
