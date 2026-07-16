#!/usr/bin/env python3
r"""
_apply_phantom_boughtin_guards.py

DEFECT (job 1310 Drill Stud Holder — manual £6.90, engine £128.01):
    The deterministic prose recogniser (bought_in_recogniser.py, "layer 2") minted a
    purchased part called "Drill Stud Holder" @ £105.00 — which is THE JOB ITSELF, the
    thing we fabricate from 1310-01 HOOK PLATE + 1310-02 STUD.

    Provenance proved by _probe_phantom_boughtin.py:
        source                  : prose_recogniser_layer2
        _headword               : "stud"          (legitimately in _HEADWORDS_SAFE)
        cost_source             : historical_quote_material_line
        _matched_historical_desc: "Drill stud holder"
        _match_score            : 1.0             (an EXACT match — to our own product)
        confidence.overall      : 0.0
        price_verified          : False
        review_flag             : True
        -> and it still landed £105.00 on the deliverable with NO console flag.

THREE ROOT CAUSES, THREE GUARDS:

  1. INPUT DUPLICATION.  estimator fed the recogniser FOUR copies of each assembly page
     (pdfplumber_text + normalized_text + pypdf_text + text_preview), i.e. the whole page
     — title block, revision table, company address — not the drawing's notes prose the
     module's own docstring promises.
     GUARD 1 (conservative): still pass page text (so nothing already discovered is lost —
     1282's electricals may come from it), but pass ONE variant, not four.

  2. SELF-REFERENCE.  estimator already builds `_fab_descs` so the recogniser never prices
     a part we're MAKING. But that set holds PART descriptions ({HOOK PLATE, STUD}). The
     PROJECT TITLE ("Drill Stud Holder") is not a part — so it was never excluded. The
     threat model covered "don't buy a part you're making"; it never covered "don't buy the
     PRODUCT you're building". Any job whose product name appears in quote history is exposed.
     GUARD 2 (the real fix): drop any recognised bought-in whose description words are a
     subset of the JOB IDENTITY words (job name / project title / drawing description).

  3. SILENT UNVERIFIED PRICING.  The engine recorded confidence 0.0 / price_verified False /
     review_flag True — and printed nothing. The flags exist and are ignored.
     GUARD 3: print a LOUD console flag for every priced-but-unverified recognised bought-in,
     escalating above a threshold. (Deliberately does NOT suppress the price: legitimate
     history-priced items — foam tape, looms, fasteners — are also price_verified=False, and
     suppressing them would gut 1282's BOM. Visibility first, then tighten.)

FILE: estimator.py only.  Line-based, asserted, backed up, idempotent.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_phantom_boughtin_guards.py
"""
from __future__ import annotations
import os, sys, shutil, datetime

PATH = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "_job_identity_tokens"          # idempotency marker

TOK_A_START = 'for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):'
TOK_A_END = '_note_chunks.append(str(_rt["notes"]))'
TOK_B = "if _det_items:"
TOK_C = "def _recognise_vinyl_callouts(all_text: str, existing_pns: set,"


HELPERS = '''
# ---------------------------------------------------------------------------
# JOB-IDENTITY GUARD  (added after job 1310: a £105 phantom "Drill Stud Holder")
#
# The deterministic prose recogniser matches component head-words ("stud", "clip",
# "loom"...) against SDI quote history. On 1310 it read the PROJECT TITLE out of the
# title block — "DRILL STUD HOLDER" — matched it 1.0 against a historical quote line
# for that same finished product, and costed the job we are BUILDING as a part we BUY.
#
# The existing `_fab_descs` guard excludes fabricated PART descriptions (HOOK PLATE,
# STUD). It cannot catch this, because the assembly/product name is not a part.
#
# So: never recognise a bought-in whose description is made only of words that already
# name the job. "Drill Stud Holder" ⊂ {1310, DRILL, STUD, HOLDER, REV, C} -> dropped.
# A genuine purchased component is never named solely by the job's own title words.
# ---------------------------------------------------------------------------
_JOB_IDENT_STOPWORDS = {
    "REV", "REVISION", "DRAWING", "DRAWINGS", "ASSEMBLY", "GENERAL", "JSON", "PDF",
    "DXF", "AND", "THE", "FOR", "WITH", "OFF", "NEW", "OLD", "COPY", "FINAL",
}


def _job_identity_tokens(summary: Dict[str, Any]) -> set:
    """Words that name THIS job: job/file name, project title, drawing description."""
    import re as _re
    cands: List[str] = []
    for _k in ("job_name", "job", "source_file", "document_name", "file_name",
               "project_title", "drawing_title", "title", "description"):
        _v = summary.get(_k)
        if isinstance(_v, str) and _v.strip():
            cands.append(_v)
    _da = summary.get("document_analysis") or {}
    if isinstance(_da, dict):
        for _k in ("project_title", "drawing_title", "title", "job_title", "description"):
            _v = _da.get(_k)
            if isinstance(_v, str) and _v.strip():
                cands.append(_v)
    toks: set = set()
    for _c in cands:
        for _t in _re.findall(r"[A-Za-z]{3,}", _c.upper()):
            toks.add(_t)
    return toks - _JOB_IDENT_STOPWORDS


def _is_job_identity_desc(desc: Any, job_tokens: set) -> bool:
    """True when a candidate bought-in is named ONLY by the job's own title words."""
    import re as _re
    if not desc or not job_tokens:
        return False
    dt = set(_re.findall(r"[A-Za-z]{3,}", str(desc).upper())) - _JOB_IDENT_STOPWORDS
    if not dt:
        return False
    return dt.issubset(job_tokens)


'''


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if SENTINEL in src:
        sys.exit("Already applied (found _job_identity_tokens). No change made.")

    lines = src.splitlines(keepends=True)

    def find_one(token, what):
        hits = [i for i, ln in enumerate(lines) if token in ln]
        if len(hits) != 1:
            sys.exit(f"ABORT: expected exactly 1 line containing {what}, found {len(hits)}. "
                     f"Source has drifted. No change made.")
        return hits[0]

    # ---------------- GUARD 1 : stop feeding four copies of the page -------------
    a0 = find_one(TOK_A_START, "the 4-variant page-text loop")
    a1 = find_one(TOK_A_END, "the region_text notes append")
    if a1 <= a0:
        sys.exit("ABORT: note-chunk block not in the expected order. No change made.")
    indent = lines[a0][: len(lines[a0]) - len(lines[a0].lstrip())]

    guard1 = [
        f'{indent}# GUARD 1 (job 1310): notes region first, then ONE page-text variant.\n',
        f'{indent}# Previously ALL FOUR text variants were appended — the recogniser was\n',
        f'{indent}# handed four copies of the whole page (title block included).\n',
        f'{indent}_rt = _pg.get("region_text") or {{}}\n',
        f'{indent}if isinstance(_rt, dict) and _rt.get("notes"):\n',
        f'{indent}    _note_chunks.append(str(_rt["notes"]))\n',
        f'{indent}for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):\n',
        f'{indent}    _v = _pg.get(_k)\n',
        f'{indent}    if _v:\n',
        f'{indent}        _note_chunks.append(str(_v))\n',
        f'{indent}        break\n',
    ]
    lines[a0:a1 + 1] = guard1

    # ---------------- GUARD 2 + 3 : filter and surface --------------------------
    b = find_one(TOK_B, "'if _det_items:'")
    bindent = lines[b][: len(lines[b]) - len(lines[b].lstrip())]

    guard23 = [
        f'{bindent}# GUARD 2 (job 1310): never keep a bought-in that IS the job itself.\n',
        f'{bindent}# The recogniser read the PROJECT TITLE from the title block, matched it\n',
        f'{bindent}# 1.0 against a historical quote line for the same finished product, and\n',
        f'{bindent}# costed it as a purchased part (£105 on a £6.90 job).\n',
        f'{bindent}_job_toks = _job_identity_tokens(summary)\n',
        f'{bindent}_kept_di, _dropped_di = [], []\n',
        f'{bindent}for _di in (_det_items or []):\n',
        f'{bindent}    if _is_job_identity_desc(_di.get("description"), _job_toks):\n',
        f'{bindent}        _dropped_di.append(_di)\n',
        f'{bindent}    else:\n',
        f'{bindent}        _kept_di.append(_di)\n',
        f'{bindent}for _dd in _dropped_di:\n',
        f'{bindent}    print("   [recogniser] DROPPED self-referential bought-in "\n',
        f'{bindent}          f"{{_dd.get(\'description\')!r}} (£{{_dd.get(\'unit_cost_gbp\')}}) — "\n',
        f'{bindent}          "its name is the JOB TITLE, not a purchased component.")\n',
        f'{bindent}_det_items = _kept_di\n',
        f'{bindent}\n',
        f'{bindent}# GUARD 3: a recognised bought-in that carries a price it could not verify\n',
        f'{bindent}# must SAY SO on the console. Previously confidence=0.0 / price_verified=False\n',
        f'{bindent}# was recorded in JSON and silently ignored — £105 landed unannounced.\n',
        f'{bindent}for _di in (_det_items or []):\n',
        f'{bindent}    _c = _di.get("unit_cost_gbp")\n',
        f'{bindent}    if _c and not _di.get("price_verified", False):\n',
        f'{bindent}        try:\n',
        f'{bindent}            _cf = float(_c)\n',
        f'{bindent}        except Exception:\n',
        f'{bindent}            continue\n',
        f'{bindent}        _lvl = "!! HIGH-VALUE" if _cf >= 25.0 else "!"\n',
        f'{bindent}        print(f"   [recogniser] {{_lvl}} UNVERIFIED price £{{_cf:.2f}} on "\n',
        f'{bindent}              f"{{_di.get(\'description\')!r}} "\n',
        f'{bindent}              f"(source: {{_di.get(\'source\')}}) — estimator to verify.")\n',
        f'{bindent}\n',
    ]
    lines[b:b] = guard23

    # ---------------- helpers at module level -----------------------------------
    c = find_one(TOK_C, "def _recognise_vinyl_callouts")
    lines[c:c] = [HELPERS]

    new = "".join(lines)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_phantomguards_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("""
GUARD 1  page text: 4 duplicate variants -> 1 (notes region still preferred first)
GUARD 2  drop any recognised bought-in named ONLY by the job's own title words
GUARD 3  loud console flag on every priced-but-unverified recognised bought-in

EXPECT on 1310 re-run (qty 50):
    [recogniser] DROPPED self-referential bought-in 'Drill Stud Holder' (£105.0) ...
    BI-DRILLSTUDHOLDER gone from the BOM
    Unit Cost £128.01 -> about £13 (still high: the STUD is mis-read as 8mm sheet,
    powder is being dropped, weld + robomac missing — separate defects, not this fix)

REGRESSION — 1282 MUST hold:
    its electrical BOM (loom / junction box / mains cable / earth strap) is recognised
    by this same layer. If those lines vanish, GUARD 1 is the culprit -> restore the
    backup and re-apply with the page-text loop untouched.
""")


if __name__ == "__main__":
    main()
