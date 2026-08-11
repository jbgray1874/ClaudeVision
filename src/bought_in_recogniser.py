# -*- coding: utf-8 -*-
"""
bought_in_recogniser.py  -  LAYER 2 of the three-layer bought-in capture model.
THE THREE LAYERS (deterministic-first, LLM-last):
  Layer 1  Structured BOM grid scan (pdfplumber)  -> items in the ITEM/DWG/DESC/QTY table.
           Reliable, already built (estimator.extract_bought_in_from_pages).
  Layer 2  THIS MODULE - deterministic PROSE recogniser. Reads the drawing's own note
           text, matches against a vocabulary of bought-in component TYPES mined from SDI's
           real history (dbo.historical_quote_material_line + dbo.bought_in_parts) PLUS a
           curated electrical vocabulary, and emits the items that are genuinely described
           in THIS drawing's prose - priced from real SDI history where a confident match
           exists. Deterministic: same drawing -> same items -> same prices, every run.
  Layer 3  LLM note-scan (note_scan.py) - BACKSTOP only. Catches novel phrasings layer 2's
           vocabulary does not yet know. Flagged as AI-sourced. When it finds something new,
           that term is a candidate to add to the vocabulary so layer 2 catches it next time.
PROVENANCE / SAFETY DISCIPLINE (do not weaken):
  * The VOCABULARY (what a bought-in component is called) is global, mined across all jobs.
  * INCLUSION on a job's BOM is local: an item appears ONLY because its type-words appear in
    THIS drawing's prose. A vocabulary term never forces an item onto a job.
  * A historical price is replayed ONLY for a confident same-part match. Descriptions are
    kept VERBATIM (never reworded) so they (a) stay traceable to source and (b) keep matching
    the same part on future jobs. A weak match is SURFACED (flagged) but not silently priced
    as if verified.
  * Cross-job contamination guard: we match a *type/description*, not a specific job's part;
    bundles from one job (e.g. a "downlights+transformer+cable+plug" package) are NOT matched
    onto a different job's individual components.
This module reads the DB read-only. It never writes. It never sends DXF geometry anywhere.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from supplier_reference import synthesise_key
# ---------------------------------------------------------------------------
# HEAD-WORDS: the generic nouns that name a physical PURCHASED component. A prose
# phrase only counts as a bought-in item if it is multi-word AND anchored on one of
# these. This is what kills the boilerplate noise (CLIENT, BARN, SURFACE, TABLE...):
# none of those contain a head-word, so they can never form a valid component phrase.
#
# SAFE head-words: almost always a bought-in component. Recognise and price freely.
# AMBIGUOUS head-words: name things SDI both MAKES and BUYS (a "base plate" is usually a
#   fabricated DXF part, not bought). These are recognised but NOT priced when the item is
#   already accounted for as a fabricated part - they surface as a flagged QUERY for the
#   estimator so they can never silently double-count.
# ---------------------------------------------------------------------------
_HEADWORDS_SAFE = set("""
screw bolt nut nutsert insert washer rivet stud bush glide grommet magnet hinge castor
clip strap tie cable loom downlight transformer driver lamp bulb plug socket connector
gland sleeve cap knob handle catch latch lock pin spacer fastener clamp fixing
tape edging seal sticker label pad foam
box light led junction earth mains electrics
""".split())
_HEADWORDS_AMBIGUOUS = set("""
plate channel rail bar panel frame foot bracket cover profile
""".split())
_HEADWORDS = _HEADWORDS_SAFE | _HEADWORDS_AMBIGUOUS
# ---------------------------------------------------------------------------
# CURATED ELECTRICAL VOCABULARY (deterministic, always-scanned).
# The lighting electricals (loom / junction box / mains cable / earth strap / LED link /
# GU10 downlight) are described in assembly PROSE but are a MINORITY across jobs, so they
# never cleared the >=5x frequency-mining bar for the general vocab and fell to the (non-
# deterministic) LLM backstop - which silently dropped them (BOM 15->9, ~£45 swing). These
# are a KNOWN, FINITE, safety-critical set ("don't miss BOMs"), so we scan for them
# explicitly regardless of mined frequency. Phrase -> head-word (all SAFE). Multi-word,
# whole-word matched, same machinery as the mined vocab. Pricing still comes from REAL
# history (see BoughtInReference.electrical_priced_match); nothing here invents a price.
_ELECTRICAL_VOCAB = {
    "lighting loom": "loom",
    "50cm loom": "loom",
    "led link light": "light",
    "led link lights": "light",
    "gu10 downlight": "downlight",
    "gu10 led downlight": "downlight",
    "led downlight": "downlight",
    "led downlights": "downlight",
    "junction box": "box",
    "mains cable": "cable",
    "earth strap": "strap",
}
# ANCHOR tokens per electrical phrase: the distinctive electrical noun(s) that MUST all be
# present in a historical line for it to price that phrase. Keeps "loom" from matching a
# non-loom line, and requires "led"+"link" together for the link light. Phrases whose
# anchors find no in-band historical line (junction box / mains cable / earth strap) simply
# get no price -> flagged "estimator to price".
_ELECTRICAL_ANCHORS = {
    "lighting loom": {"loom"},
    "50cm loom": {"loom"},
    "led link light": {"led", "link"},
    "led link lights": {"led", "link"},
    "gu10 downlight": {"downlight"},
    "gu10 led downlight": {"downlight"},
    "led downlight": {"downlight"},
    "led downlights": {"downlights"},
    "junction box": {"junction", "box"},
    "mains cable": {"mains", "cable"},
    "earth strap": {"earth", "strap"},
}
# Electrical items priced from history must fall in a sane band, so a loose "loom" token can
# never pick up a £125 herb-stand loom or a £132 gasket kit. Real Milwaukee electricals sit
# well inside this. Anything outside -> flag "estimator to price" rather than apply.
_ELECTRICAL_PRICE_BAND = (1.0, 40.0)
# ---------------------------------------------------------------------------
# Stopwords / non-component words. Kept deliberately small and obvious. These
# are words that recur in material descriptions but are NOT component types
# (spreadsheet artefacts, admin words, units, generic adjectives).
# ---------------------------------------------------------------------------
_STOP = set("""
and the to of for with a an or be in on per x mm cm m std part each set kg no not all
from as is by off thru dia ext int down up rev semi gloss ral mat material description
item misc inc max min height width depth charge total cost delivery elc upc sticker
black white red blue grey green clear natural left right top bottom front back side
new old approx tbc na n/a unless otherwise stated qty quantity price each
""".split())
# Minimum token length to be considered a meaningful type-word.
_MIN_TOKEN = 3
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())
def _tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [w for w in s.split() if len(w) >= _MIN_TOKEN and w not in _STOP and not w.isdigit()]
def _sig_token_set(s: str) -> Set[str]:
    return set(_tokens(s))


# ---------------------------------------------------------------------------
# SCOPE OF SUPPLY: what the drawing DEPICTS is not what SDI SUPPLIES.
#
# A drawing routinely shows things it is not quoting for -- the customer's screen, an
# existing wall, a monitor arm bought by someone else -- and says so in a standard phrase
# next to them. 12120's GA carries "SCREEN & CABLE SHOWN FOR REFERENCE"; the recogniser saw
# the SAFE electrical head-word "cable", minted BI-SCREENCABLE, priced it and booked
# handling labour against it. Nothing in the engine read the half of the sentence that says
# it is not ours.
#
# These are drawing conventions, not one customer's wording, so the rule inherits to every
# job. Deliberately excluded: a bare "existing", which is too common a word to carry the
# meaning on its own, and "typical"/"similar", which qualify how MANY are supplied rather
# than whether any are.
# ---------------------------------------------------------------------------
_SUPPLY_EXCLUSION_MARKERS = (
    "for reference", "reference only", "ref only", "for ref", "shown for ref",
    "not supplied", "not included", "not in scope", "excluded from supply", "no supply",
    "not part of this", "not to be supplied",
    "by others", "supplied by others", "installed by others", "fitted by others",
    "by client", "client supplied", "supplied by client",
    "by customer", "customer supplied", "supplied by customer",
    "free issue", "customer free issue",
    "shown dotted", "dotted for clarity", "for clarity only",
    "for illustration", "illustration only", "indicative only",
)


def _supply_segments(note_text: str) -> List[str]:
    """The drawing's prose split into the clauses a scope note actually applies to.

    A marker governs its own sentence or line, not the whole page. Splitting on line breaks
    and sentence punctuation keeps "SCREEN & CABLE SHOWN FOR REFERENCE" from excusing a
    genuine bought-in listed three notes further down.
    """
    # A BARE NEWLINE IS A LINE WRAP, NOT A CLAUSE BOUNDARY.
    #
    # This split on every newline, and 12120's real PDF text wraps the disclaimer:
    #
    #     SCREEN & CABLE SHOWN
    #     FOR REFERENCE
    #
    # which became two clauses -- one naming the cable with no marker, one carrying the
    # marker with nothing to attach it to -- so the cable was supplied and priced. The
    # synthetic fixture wrote it on one line and passed.
    #
    # What IS a boundary: sentence punctuation, and a newline that starts a new numbered or
    # bulleted note. Those keep note 2's hardware safe from note 1's disclaimer. A newline
    # in the middle of a note is layout, and the PDF reader's line breaks are not the
    # draughtsman's sentences.
    _parts = re.split(r"[;.]+|\n(?=\s*(?:\d+[.)]|[-*\u2022])\s)|(?<=\))\s+",
                      str(note_text or ""))
    _out = []
    for _p in _parts:
        _n = re.sub(r"[^a-z0-9 ]", " ", (_p or "").lower())
        _n = re.sub(r"\s+", " ", _n).strip()
        if _n:
            _out.append(" " + _n + " ")
    return _out


def bom_row_is_reference_only(description: Any, comments: Any = "",
                              note_text: Any = "") -> bool:
    """A BOM row the drawing DEPICTS but does not supply.

    The prose recogniser was guarded first, and 12120 then shipped BI-SCREENCABLE anyway
    with no recogniser message at all -- because the row reached the estimate through the
    whole-document extract's own `bom` list, which is a different door into the same
    mistake. One predicate, two doors: the marker vocabulary is shared with
    is_reference_only rather than restated, so a phrase added for one path covers both.

    Two ways a row qualifies. Its OWN text can carry the disclaimer, which is the common
    case when the model transcribes "SCREEN & CABLE - SHOWN FOR REFERENCE" into a row's
    description or comments. Or the drawing's notes can disclaim every mention of it, which
    is the same test the prose path uses.

    Deliberately NOT keyed on the word cable, or on any part name. A rule that knows about
    cables would have to be extended for the next screen, monitor arm or customer bracket
    somebody shows for reference.
    """
    _own = " ".join(str(x or "") for x in (description, comments)).strip()
    if _own:
        for _seg in _supply_segments(_own):
            if any(_m in _seg for _m in _SUPPLY_EXCLUSION_MARKERS):
                return True
    return is_reference_only(description, note_text)


def is_reference_only(phrase: str, note_text: str) -> bool:
    """True when every mention of `phrase` sits in a clause that disclaims supplying it.

    EVERY mention, not any: a drawing that shows a bracket for reference on one view and
    schedules it as a supplied item elsewhere is supplying it. Erring the other way would
    turn a scope note into a silent deletion of a real BOM line, which is the more expensive
    mistake and the harder one to notice.
    """
    _ph = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(phrase or "").lower())).strip()
    if not _ph:
        return False
    _needle = " " + _ph + " "
    _seen = _excluded = 0
    for _seg in _supply_segments(note_text):
        if _needle not in _seg:
            continue
        _seen += 1
        if any(_m in _seg for _m in _SUPPLY_EXCLUSION_MARKERS):
            _excluded += 1
    return _seen > 0 and _seen == _excluded
# ---------------------------------------------------------------------------
# Vocabulary + priced reference, loaded ONCE from SDI history.
# ---------------------------------------------------------------------------
class BoughtInReference:
    """Holds the mined type-vocabulary and the priced historical descriptions.
    Built once (a few seconds: one SQL pull + in-memory tally), then matching per job is
    in-memory and effectively instant - it never re-queries the 68k rows per job.
    """
    def __init__(self) -> None:
        # vocab maps a head-word-anchored phrase -> the head-word it is anchored on,
        # so the recogniser knows whether a hit is SAFE or AMBIGUOUS.
        self.vocab: Dict[str, str] = {}
        self.priced: List[Dict[str, Any]] = []  # [{desc, desc_tokens, price, code, source}]
        self.loaded = False
    def load(self, get_connection, *, min_term_freq: int = 5,
             max_price: float = 750.0) -> "BoughtInReference":
        """Mine vocabulary + priced reference from SDI history (read-only)."""
        try:
            conn = get_connection()
            cur = conn.cursor()
        except Exception:
            # No DB - module stays empty; layer-2 becomes a no-op and the LLM backstop carries.
            self.loaded = True
            return self
        rows: List[Tuple[str, Optional[float], Optional[str]]] = []
        # Priced bought-in material lines (the gold: real descriptions + real prices + codes).
        try:
            cur.execute("""
                SELECT line_description, unit_price_gbp, part_code
                FROM dbo.historical_quote_material_line
                WHERE line_description IS NOT NULL
            """)
            rows += [(r[0], r[1], r[2]) for r in cur.fetchall()]
        except Exception:
            pass
        # Curated bought_in_parts (small, clean, also priced).
        try:
            cur.execute("""
                SELECT description, unit_price_gbp, part_code
                FROM dbo.bought_in_parts
                WHERE description IS NOT NULL
            """)
            rows += [(r[0], r[1], r[2]) for r in cur.fetchall()]
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        # Build priced reference (keep descriptions VERBATIM) + tally HEAD-WORD-ANCHORED
        # multi-word phrases only. A phrase qualifies as vocabulary ONLY if it is multi-word
        # AND contains a component head-word. This is what removes the boilerplate noise that
        # a naive single-word mine produced (CLIENT/BARN/SURFACE/TABLE etc.).
        from collections import Counter
        phrase_freq: Counter = Counter()
        phrase_head: Dict[str, str] = {}
        for desc, price, code in rows:
            toks = _tokens(str(desc))
            if not toks:
                continue
            # bigrams + trigrams that contain at least one head-word
            for n in (2, 3):
                for i in range(len(toks) - n + 1):
                    gram = toks[i:i + n]
                    heads = [w for w in gram if w in _HEADWORDS]
                    if not heads:
                        continue
                    phrase = " ".join(gram)
                    phrase_freq[phrase] += 1
                    # record the head-word (prefer a safe one if the phrase has several)
                    if phrase not in phrase_head:
                        safe = [h for h in heads if h in _HEADWORDS_SAFE]
                        phrase_head[phrase] = (safe[0] if safe else heads[0])
            try:
                p = float(price) if price is not None else None
            except Exception:
                p = None
            if p is not None and 0 < p <= max_price:
                self.priced.append({
                    "desc": str(desc).strip(),          # VERBATIM - never reworded
                    "desc_tokens": set(toks),
                    "price": p,
                    "code": (str(code).strip() if code else None),
                    "source": "historical_quote_material_line",
                })
        # Vocabulary = head-word-anchored phrases recurring at least min_term_freq times.
        self.vocab = {ph: phrase_head[ph] for ph, n in phrase_freq.items() if n >= min_term_freq}
        self.loaded = True
        return self
    # --- matching -----------------------------------------------------------
    def best_priced_match(self, phrase: str, *, min_overlap: float = 0.6,
                          min_shared: int = 2) -> Optional[Dict[str, Any]]:
        """Find the closest priced historical line for a recognised phrase, by token overlap.
        Conservative on purpose: returns a match only when the phrase and a historical
        description share enough significant tokens. Confidence scales with overlap so the
        caller can flag weak matches rather than apply them blindly. Never rewords anything.
        """
        ptoks = _sig_token_set(phrase)
        if len(ptoks) < min_shared:
            return None
        best = None
        best_score = 0.0
        for ref in self.priced:
            rtoks = ref["desc_tokens"]
            if not rtoks:
                continue
            shared = ptoks & rtoks
            if len(shared) < min_shared:
                continue
            # Jaccard (shared / union), NOT shared/smaller. shared/smaller let a 2-token
            # phrase ("foam tape") score 1.0 against any longer line containing both words
            # (e.g. a £132 "foam tape gasket kit 25m"), producing confidently-wrong prices.
            # Jaccard penalises unexplained tokens on the historical side, so a short phrase
            # only matches a similarly-short, genuinely-equivalent description.
            union = ptoks | rtoks
            score = len(shared) / len(union) if union else 0.0
            if score > best_score:
                best_score, best = score, ref
        if best is None or best_score < min_overlap:
            return None
        return {
            "matched_desc": best["desc"],       # verbatim source description
            "price": best["price"],
            "code": best["code"],
            "source": best["source"],
            "match_score": round(best_score, 3),
        }
    def electrical_priced_match(self, phrase: str) -> Optional[Dict[str, Any]]:
        """Price a CURATED electrical phrase from history by ANCHOR-token containment.
        The known electrical phrases ("50cm loom", "led link light") are shorter than their
        historical descriptions ("ELECTRICS - 50cm LOOM", "900mm LED Link Lights"), so strict
        Jaccard under-scores them. Instead we require the phrase's ANCHOR tokens (the
        distinctive electrical noun, e.g. {loom} or {led,link}) to all be present in the
        historical line, keep only lines inside the electrical plausibility band (defends
        against a £125 bundle loom), then pick the MOST SPECIFIC line - the one sharing the
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
# Module-level singleton so the reference is built once per process.
_REFERENCE: Optional[BoughtInReference] = None
def get_reference(get_connection) -> BoughtInReference:
    global _REFERENCE
    if _REFERENCE is None or not _REFERENCE.loaded:
        _REFERENCE = BoughtInReference().load(get_connection)
    return _REFERENCE
# ---------------------------------------------------------------------------
# The layer-2 prose recogniser.
# ---------------------------------------------------------------------------
def _phrase_tokens(text: Any) -> List[str]:
    """The alphanumeric runs in a piece of text, upper-cased.

    "M6 BOLT, BZP" and "BOLT(BZP)" and "BOLT - BZP" all reduce to the same words, which is
    what makes a phrase findable on a sheet that punctuates it differently from the way the
    recogniser read it.
    """
    return re.findall(r"[A-Z0-9]+", str(text or "").upper())


def _tokens_run_in(needle: List[str], haystack: List[str]) -> bool:
    """True when `needle` appears in `haystack` as a consecutive run, in order.

    Consecutive and in order on purpose. A page that merely contains both words somewhere
    is not a page that names the part, and matching that loosely would hand an owner to a
    sheet that never mentioned it — which is worse than leaving it unowned.
    """
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i] == first and haystack[i:i + len(needle)] == needle:
            return True
    return False


def _page_that_says(phrase: Any, pages: Optional[List[Dict[str, Any]]]) -> Optional[int]:
    """The page number whose own text contains this phrase, or None.

    First match wins, in page order. Where a phrase appears on several sheets the first is
    as defensible as any — and the compiler only ever uses this to offer an owner, which it
    then refuses unless the page is an assembly page of a drawing the job already knows.

    BOTH SIDES ARE NORMALISED, and originally only one was. The needle had its whitespace
    collapsed and the page text did not, so "BOLT BZP" failed to match a note reading
    "BOLT\\nBZP" — and drawing notes wrap constantly, which makes a line break the normal
    case rather than an edge one. BI-BOLTBZP is a real GBP 0.83 bolt that blocked job 12392
    as a disconnected node for exactly this: the sheet that named it was found, compared
    against an un-normalised copy of itself, and reported as not saying so.
    """
    if not phrase or not pages:
        return None
    # WORDS, NOT CHARACTERS. Collapsing whitespace fixed the line-wrap case and left every
    # punctuated one failing: a note reads "M6 BOLT, BZP" or "BOLT (BZP)" or "BOLT - BZP"
    # as readily as "BOLT BZP", and a drawing note is full of punctuation. On 12392 the
    # button-head screw found its page and the bolt did not, which is the same phrase
    # matcher succeeding and failing on the same sheet for want of a comma.
    #
    # Alphanumeric runs, matched CONSECUTIVELY AND IN ORDER. That is deliberately tight:
    # it accepts any separator between the words and still refuses "BZP BOLT", which is a
    # different phrase, and refuses a page that merely contains both words apart.
    _needle = _phrase_tokens(phrase)
    if not _needle:
        return None
    for page in pages:
        if not isinstance(page, dict):
            continue
        blob = []
        region = page.get("region_text")
        if isinstance(region, dict):
            blob.append(str(region.get("notes") or ""))
        for key in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview", "text"):
            value = page.get(key)
            if value:
                blob.append(str(value))
        if _tokens_run_in(_needle, _phrase_tokens(" ".join(blob))):
            number = page.get("page_number")
            try:
                return int(number)
            except (TypeError, ValueError):
                return None
    return None


def recognise_bought_in_in_prose(
    note_text: str,
    *,
    get_connection,
    existing_pns: Optional[Set[str]] = None,
    existing_descriptions: Optional[Set[str]] = None,
    fabricated_descriptions: Optional[Set[str]] = None,
    stub_builder=None,
    pages: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Deterministically recognise bought-in items described in THIS drawing's prose.
    Scans the prose for head-word-anchored vocabulary phrases (mined from SDI history) PLUS
    a curated electrical vocabulary (always scanned, so the lighting electricals are never
    missed). For each hit:
      * SAFE head-word (screw/clip/strap/cable/loom...): recognise + price from history if a
        confident match exists, else surface flagged "no price - estimator to price".
      * AMBIGUOUS head-word (plate/rail/bar...): recognise, but if the item is already
        accounted for as a fabricated part, surface it as a flagged QUERY with NO price
        (so it can never silently double-count a made-in part). Otherwise treat like SAFE.
    Deterministic: same note_text + same DB -> same items + prices, every run. No LLM. No DXF.
    """
    if not note_text or stub_builder is None:
        return []
    existing_pns = existing_pns or set()
    existing_descriptions = existing_descriptions or set()
    fabricated_descriptions = fabricated_descriptions or set()
    ref = get_reference(get_connection)
    # NOTE: we proceed even if ref.vocab is empty, because the CURATED electrical vocab is
    # DB-independent and must always run (it is how the lighting electricals are caught). If
    # BOTH the mined vocab and the electrical vocab produce nothing, the loop simply yields [].
    up = " " + re.sub(r"[^a-z0-9 ]", " ", (note_text or "").lower()) + " "
    up = re.sub(r"\s+", " ", up)
    # Pre-compute fabricated-part token sets once (for the double-count guard).
    fab_token_sets = [_sig_token_set(f) for f in fabricated_descriptions if f]
    def _is_already_fabricated(phrase: str) -> bool:
        pts = _sig_token_set(phrase)
        if not pts:
            return False
        for fts in fab_token_sets:
            if not fts:
                continue
            shared = pts & fts
            if len(shared) >= max(2, int(0.6 * len(pts))):
                return True
        return False
    # Curated electrical phrases are ALWAYS scanned (not subject to frequency mining), then
    # the mined vocab. Electrical head-words are registered as SAFE (see _HEADWORDS_SAFE). A
    # phrase only produces an item if it actually appears in THIS drawing's prose.
    _scan_vocab: Dict[str, str] = dict(ref.vocab)
    for _ph, _hd in _ELECTRICAL_VOCAB.items():
        _scan_vocab.setdefault(_ph, _hd)
    # Scan: longest phrases first (most specific). A phrase matches only as a whole-word
    # run in the prose. Track character spans so we don't double-emit overlapping phrases.
    phrases = sorted(_scan_vocab.keys(), key=lambda p: len(p), reverse=True)
    claimed_spans: List[Tuple[int, int]] = []
    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in claimed_spans)
    out: List[Dict[str, Any]] = []
    emitted: Set[str] = set()
    for phrase in phrases:
        needle = " " + phrase + " "
        idx = up.find(needle)
        if idx < 0:
            continue
        # Claim only the phrase characters (exclude the padding spaces), so two adjacent
        # phrases that share a single separator space do not falsely register as overlapping
        # (that bug silently dropped e.g. "50cm loom" when "lighting electrics" abutted it).
        s, e = idx + 1, idx + len(needle) - 1
        if _overlaps(s, e):
            continue
        claimed_spans.append((s, e))
        head = _scan_vocab[phrase]
        # THE DRAWING SHOWS IT; THE DRAWING ALSO SAYS IT IS NOT OURS.
        # Checked against the ORIGINAL note_text, not the flattened blob, because the
        # clause boundaries are what scope the marker -- see _supply_segments.
        if is_reference_only(phrase, note_text):
            print(f"   [bought-in] '{phrase}' NOT recognised: every mention is in a clause "
                  f"that disclaims supply (reference only / by others / customer supplied). "
                  f"No part, no price, no handling labour.", flush=True)
            continue
        ambiguous = head in _HEADWORDS_AMBIGUOUS
        desc = phrase.strip().title()
        key = _norm(desc)
        if not key or key in emitted:
            continue
        # Dedup against layer-1 bought-in descriptions already found.
        dts = _sig_token_set(desc)
        if any(len(dts & _sig_token_set(x)) >= max(2, int(0.6 * len(dts)))
               for x in existing_descriptions if x):
            continue
        # MINTED HERE, AND SAID SO. The prefix used to be written inline, which made it a
        # spelling rather than a fact: nothing downstream could ask whether a part number had
        # been read off a drawing or invented in this loop, so BI-BINDINGSCREW went to every
        # catalogue lookup looking exactly like a code a supplier might recognise. It is now
        # minted by the module that also answers the question.
        code_guess = synthesise_key(phrase)
        if code_guess in existing_pns:
            continue
        # DOUBLE-COUNT GUARD: if this phrase matches something already counted as a
        # fabricated (DXF/grid) part, do NOT add a priced line. For ambiguous head-words
        # this is the common case (e.g. "base plate"); surface as a flagged query instead.
        already_fab = _is_already_fabricated(desc)
        stub = stub_builder(code_guess, desc, 1)
        stub["source"] = "prose_recogniser_layer2"
        stub["_layer2_recognised"] = True
        stub["_headword"] = head
        # WHICH SHEET SAID SO. The caller reads the notes page by page and joins them one
        # line before calling this, so the page was known and thrown away — and a recognised
        # purchase with no page can never be given an owner. BI-BOLTBZP is a real GBP 0.83
        # bolt that blocked job 12392 as a "disconnected node" for exactly that reason:
        # nothing could say which drawing listed it.
        #
        # Attributed AFTER the match rather than by scanning per page, so which phrases are
        # recognised does not change at all — the same defect was fixed the same way for BOM
        # rows. A phrase spanning a page break still matches; it simply lands on no page,
        # which is the honest answer.
        _found_on = _page_that_says(phrase, pages)
        if _found_on is not None:
            stub["pages"] = [_found_on]
            stub["source_page"] = _found_on
        stub["page_roles"] = ["bought_in"]
        stub["review_flag"] = True
        flags = [f"Deterministically recognised in drawing notes (head-word: '{head}')"]
        if already_fab:
            # Recognise but DON'T price - it's likely the fabricated part counted elsewhere.
            stub["cost_source"] = "layer2_possible_fabricated_query"
            stub["_no_price_reason"] = "matches a fabricated part - possible double-count"
            flags.append("QUERY: also appears as a fabricated part - estimator confirm "
                         "bought-in vs made-in (NOT priced, to avoid double-counting)")
        else:
            match = ref.best_priced_match(desc)
            # Electrical items: their short phrase under-scores on Jaccard vs a longer
            # historical line, so fall back to an anchor-token containment match inside the
            # electrical plausibility band (loom -> "ELECTRICS - 50cm LOOM" £24.15). Flagged.
            _is_electrical = key in _ELECTRICAL_VOCAB
            if not match and _is_electrical:
                match = ref.electrical_priced_match(key)
            # Plausibility guard: a small loose consumable (clip/tie/tape/strap/rivet/etc.)
            # priced implausibly high is almost certainly a bad token match (e.g. "foam tape"
            # matching a £132 assembly line). Reject the price rather than apply a confidently
            # wrong figure - fall through to "estimator to price" (honest gap beats wrong number).
            # Electrical items are exempt (their band guard already bounds them).
            _CONSUMABLE_HEADS = {"clip", "tie", "tape", "strap", "rivet", "screw", "washer",
                                 "nut", "bolt", "insert", "grommet", "cap", "pin", "spacer",
                                 "sleeve", "gland", "seal", "sticker", "label", "pad", "foam"}
            if (match and not _is_electrical and head in _CONSUMABLE_HEADS
                    and match["price"] > 20.0):
                match = None  # implausible for a loose consumable - do not apply
                flags.append("A possible historical price match was rejected as implausibly "
                             "high for a loose consumable - estimator to price")
            if match:
                stub["unit_cost_gbp"] = match["price"]
                stub["unit_material_cost_gbp"] = match["price"]
                stub["extended_total_cost_gbp"] = round(match["price"], 2)
                stub["cost_source"] = "historical_quote_material_line"
                stub["price_verified"] = False
                stub["_matched_historical_desc"] = match["matched_desc"]
                stub["_matched_code"] = match["code"]
                stub["_match_score"] = match["match_score"]
                conf = "confident" if match["match_score"] >= 0.8 else "indicative"
                flags.append(
                    f"Priced from SDI history ({conf}, score {match['match_score']}): "
                    f"\u00a3{match['price']:.2f} \u2190 \u201c{match['matched_desc']}\u201d"
                    + (f" [{match['code']}]" if match["code"] else "") + " \u2014 verify")
            else:
                # Recognised, no historical price. Flag for estimator + (future) web/LLM price
                # + queue for promotion into the bought-in catalogue.
                stub["cost_source"] = "layer2_no_price_match"
                stub["_queue_for_catalogue"] = True
                flags.append("Type recognised, no historical price \u2014 estimator to price; "
                             "queue for catalogue (UDEF) so it is known next time")
        stub["review_flags"] = flags
        out.append(stub)
        emitted.add(key)
    if out:
        names = [s.get("part_number") or s["description"][:20] for s in out]
        print(f"[DEBUG] Layer-2 prose recogniser (deterministic) found {len(out)} item(s): {names}")
    else:
        print("[DEBUG] Layer-2 prose recogniser ran; 0 items recognised in prose")
    return out
