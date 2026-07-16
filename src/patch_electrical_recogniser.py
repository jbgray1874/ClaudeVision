"""
PATCH: add deterministic electrical-BOM recognition to bought_in_recogniser.py.

WHY: the electricals (junction box, mains cable, earth strap, LED link light, GU10
downlight, loom) are described in assembly prose but were NOT in the frequency-mined
vocabulary (they don't recur >=5x), so they fell to the non-deterministic LLM note-scan
and silently dropped (BOM 15->9, ~£45 swing). This makes them a CURATED, always-scanned
vocabulary, priced from REAL historical quotes via a containment match (guarded by an
electrical plausibility band), everything flagged for the estimator. No LLM, no invented
numbers — real price where history has it (loom £24.15, LED £10.65), honest flag where not.

WHAT IT DOES (three edits to C:\ClaudeVision\src\bought_in_recogniser.py):
  1. Adds _ELECTRICAL_VOCAB (curated phrase->headword) + _ELECTRICAL_PRICE_BAND after _MIN_TOKEN.
  2. Merges the curated electrical phrases into the scan and relaxes the `if not ref.vocab`
     guard so electricals work even if DB mining returned nothing.
  3. Adds an electrical containment-match helper on the reference and uses it when strict
     Jaccard misses, so "loom" prices from "ELECTRICS - 50cm LOOM".

SAFE: read-modify-write with a timestamped .bak. Idempotent (re-running detects the marker
and skips). Verifies Python syntax of the result before saving.

Run: C:\ClaudeVision\.venv\Scripts\python.exe patch_electrical_recogniser.py
"""
import ast
import shutil
import time
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src\bought_in_recogniser.py")
text = SRC.read_text(encoding="utf-8")

MARKER = "_ELECTRICAL_VOCAB"
if MARKER in text:
    print("Already patched (found _ELECTRICAL_VOCAB). No changes made.")
    raise SystemExit

# ── EDIT 1: curated electrical vocabulary + plausibility band, after _MIN_TOKEN = 3 ──
anchor1 = "_MIN_TOKEN = 3\n"
if anchor1 not in text:
    print("FAIL: could not find anchor '_MIN_TOKEN = 3'. Aborted, no changes.")
    raise SystemExit

insert1 = '''_MIN_TOKEN = 3


# ---------------------------------------------------------------------------
# CURATED ELECTRICAL VOCABULARY (deterministic, always-scanned).
# The lighting electricals (loom / junction box / mains cable / earth strap / LED link /
# GU10 downlight) are described in assembly PROSE but are a MINORITY across jobs, so they
# never cleared the >=5x frequency-mining bar for the general vocab and fell to the (non-
# deterministic) LLM backstop — which silently dropped them. These are a KNOWN, FINITE,
# safety-critical set ("don't miss BOMs"), so we scan for them explicitly regardless of
# mined frequency. Phrase -> head-word (all SAFE). Multi-word, whole-word matched, same as
# the mined vocab. Pricing still comes from REAL history (see _electrical_priced_match);
# nothing here invents a price.
_ELECTRICAL_VOCAB = {
    "lighting loom": "loom",
    "50cm loom": "loom",
    "led link light": "light",
    "led link lights": "light",
    "gu10 downlight": "downlight",
    "gu10 led downlight": "downlight",
    "led downlight": "downlight",
    "junction box": "box",
    "mains cable": "cable",
    "earth strap": "strap",
    "lighting electrics": "cable",
}
# ANCHOR tokens per electrical phrase: the distinctive electrical noun(s) that MUST all be
# present in a historical line for it to price that phrase. Keeps "loom" from matching a
# non-loom line, and requires "led"+"link" together for the link light. Phrases not listed
# here (junction box / mains cable / earth strap) simply have no historical price -> flagged.
_ELECTRICAL_ANCHORS = {
    "lighting loom": {"loom"},
    "50cm loom": {"loom"},
    "led link light": {"led", "link"},
    "led link lights": {"led", "link"},
    "gu10 downlight": {"downlight"},
    "gu10 led downlight": {"downlight"},
    "led downlight": {"downlight"},
    "junction box": {"junction", "box"},
    "mains cable": {"mains", "cable"},
    "earth strap": {"earth", "strap"},
}
# Electrical items priced from history must fall in a sane band, so a loose "loom" token can
# never pick up a £125 herb-stand loom or a £132 gasket kit. Real Milwaukee electricals sit
# well inside this. Anything outside -> flag "estimator to price" rather than apply.
_ELECTRICAL_PRICE_BAND = (1.0, 40.0)
'''
text = text.replace(anchor1, insert1, 1)

# ── EDIT 2: add electrical containment matcher method on BoughtInReference ──
# Insert just before the module-level singleton comment.
anchor2 = "# Module-level singleton so the reference is built once per process."
if anchor2 not in text:
    print("FAIL: could not find anchor for singleton comment. Aborted.")
    raise SystemExit

insert2 = '''    def electrical_priced_match(self, phrase: str) -> Optional[Dict[str, Any]]:
        """Price a CURATED electrical phrase from history by ANCHOR-token containment.

        The known electrical phrases ("50cm loom", "led link light") are shorter than their
        historical descriptions ("ELECTRICS - 50cm LOOM", "900mm LED Link Lights"), so strict
        Jaccard under-scores them. Instead we require the phrase's ANCHOR tokens (the
        distinctive electrical noun, e.g. {loom} or {led,link}) to all be present in the
        historical line, keep only lines inside the electrical plausibility band (defends
        against a £125 bundle loom), then pick the MOST SPECIFIC line — the one sharing the
        most phrase tokens (so "50cm loom" -> the 50cm line £24.15, not a generic AEG loom),
        cheapest as a tie-break. Flagged, never trusted blindly. Descriptions kept verbatim.
        """
        anchors = _ELECTRICAL_ANCHORS.get(phrase)
        if not anchors:
            return None
        ptoks = _sig_token_set(phrase)
        lo, hi = _ELECTRICAL_PRICE_BAND
        cands = [r for r in self.priced
                 if r["desc_tokens"] and anchors.issubset(r["desc_tokens"])
                 and lo <= r["price"] <= hi]
        if not cands:
            return None
        # most shared phrase tokens = most specific match; cheaper wins ties (safe floor)
        best = max(cands, key=lambda r: (len(ptoks & r["desc_tokens"]), -r["price"]))
        union = ptoks | best["desc_tokens"]
        score = (len(ptoks & best["desc_tokens"]) / len(union)) if union else 0.0
        return {
            "matched_desc": best["desc"],
            "price": best["price"],
            "code": best["code"],
            "source": best["source"],
            "match_score": round(score, 3),
        }


# Module-level singleton so the reference is built once per process.'''
text = text.replace(anchor2, insert2, 1)

# ── EDIT 3a: relax the empty-vocab guard so electricals scan even with no mined vocab ──
anchor3 = '''    ref = get_reference(get_connection)
    if not ref.vocab:
        return []  # nothing mined (e.g. no DB) -> layer-2 no-op, backstop carries
'''
if anchor3 not in text:
    print("FAIL: could not find the ref.vocab guard block. Aborted.")
    raise SystemExit

insert3 = '''    ref = get_reference(get_connection)
    # NOTE: we proceed even if ref.vocab is empty, because the CURATED electrical vocab below
    # is DB-independent and must always run (it is how the lighting electricals are caught).
'''
text = text.replace(anchor3, insert3, 1)

# ── EDIT 3b: merge curated electrical phrases into the scanned phrase list ──
anchor4 = "    phrases = sorted(ref.vocab.keys(), key=lambda p: len(p), reverse=True)\n"
if anchor4 not in text:
    print("FAIL: could not find the phrases = sorted(...) line. Aborted.")
    raise SystemExit

insert4 = '''    # Curated electrical phrases are ALWAYS scanned (not subject to frequency mining), then
    # the mined vocab. Electrical head-words are registered so downstream logic treats them
    # as SAFE. A phrase only produces an item if it actually appears in THIS drawing's prose.
    _scan_vocab = dict(ref.vocab)
    for _ph, _hd in _ELECTRICAL_VOCAB.items():
        _scan_vocab.setdefault(_ph, _hd)
    phrases = sorted(_scan_vocab.keys(), key=lambda p: len(p), reverse=True)
'''
text = text.replace(anchor4, insert4, 1)

# ── EDIT 3c: use electrical containment match when strict Jaccard misses, for electricals ──
# The head lookup `head = ref.vocab[phrase]` will KeyError for curated electrical phrases
# (they're in _scan_vocab, not ref.vocab). Fix that lookup, and add the containment fallback.
anchor5 = "        head = ref.vocab[phrase]\n"
if anchor5 not in text:
    print("FAIL: could not find 'head = ref.vocab[phrase]'. Aborted.")
    raise SystemExit
insert5 = "        head = _scan_vocab[phrase]\n"
text = text.replace(anchor5, insert5, 1)

# Add containment fallback right after the strict-Jaccard `match = ref.best_priced_match(desc)`.
anchor6 = "            match = ref.best_priced_match(desc)\n"
if anchor6 not in text:
    print("FAIL: could not find 'match = ref.best_priced_match(desc)'. Aborted.")
    raise SystemExit
insert6 = '''            match = ref.best_priced_match(desc)
            # Electrical items: their short phrase under-scores on Jaccard vs a longer
            # historical line, so fall back to a containment match inside the electrical
            # plausibility band (loom -> "ELECTRICS - 50cm LOOM" £24.15). Flagged, not trusted.
            _is_electrical = key in _ELECTRICAL_VOCAB or head in {"loom", "downlight"}
            if not match and _is_electrical:
                match = ref.electrical_priced_match(key)
'''
text = text.replace(anchor6, insert6, 1)

# ── verify syntax, back up, write ──
try:
    ast.parse(text)
except SyntaxError as e:
    print(f"FAIL: patched file has a syntax error ({e}). NOT written.")
    raise SystemExit

bak = SRC.with_suffix(f".py.bak_{time.strftime('%Y%m%d_%H%M%S')}")
shutil.copy2(SRC, bak)
SRC.write_text(text, encoding="utf-8")
print(f"Patched OK.\n  backup: {bak}\n  wrote:  {SRC}")
print("Verify with: Select-String -Path C:\\ClaudeVision\\src\\bought_in_recogniser.py -Pattern \"_ELECTRICAL_VOCAB\"")
