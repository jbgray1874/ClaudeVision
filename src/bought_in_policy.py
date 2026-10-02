"""
bought_in_policy.py — one answer to "do we MAKE this part, or do we BUY it?"

That question was being answered in four places with four different rules
(estimation_report, job_decision_report, the estimator's dedup pass, and the estimator's
own bought_in_candidate logic), which is how one record came to be a catalogue line on the
BOM and a fabricated part carrying weld, powder and glue labour on the route at once.

The rule, and why:

  CATALOGUE IDENTITY DECIDES. A part matching a bought-in code family, carrying a
  bought-in page role, or priced as a catalogue line IS bought in. A drawing existing for
  it changes nothing — we routinely draw bought-in components so they can be located on an
  assembly, and treating "has a drawing" as evidence of fabrication is what let fabrication
  labour attach to purchased items.

  CONFLICTS ARE FLAGGED, NOT RESOLVED SILENTLY. Where a part is bought-in by identity and
  ALSO carries genuine fabrication evidence — its own flat pattern, a modelled cut list —
  the two sources disagree about what the part is. That deserves an estimator's attention
  and is recorded on the part. It is not grounds for the engine to overrule the catalogue
  on its own: the failure mode of guessing wrong here is fabrication labour booked against
  something we simply buy.

Deliberately identity-only — no cost, no route, no timing — so it is safe to call at any
stage, including BEFORE process costing. That is the point: the cost of getting this wrong
is labour on a purchased item, and by costing time it is already too late to ask cheaply.
"""
from __future__ import annotations

import re

from typing import Any, Dict, List

# The one module that knows how SDI's part numbers are spelled. Identity-only and
# dependency-free, like this one, so asking it here costs nothing and keeps the convention
# in a single place — a private regex in each reader is how one of them goes quietly stale.
import part_code_conventions

__all__ = [
    "is_bought_in",
    "bought_in_reason",
    "has_fabrication_evidence",
    "bought_in_conflict",
    "strip_fabrication_ops",
    "strip_leaf_operations",
    "purchased_stock_product",
    "make_buy_question",
    "is_assembly",
    "assembly_reason",
    "FABRICATION_OPS",
    "LEAF_ONLY_OPS",
    "FABRICATED_FAMILIES",
]

# THE FAMILY IS AN ANSWER TO THIS QUESTION, AND IT WAS BEING THROWN AWAY.
#
# Every BOM row the extract returns is classified metal / acrylic / timber / wire / tube /
# bought_in. Five of those six are things we cut and form here; only one is a purchase. That
# classification was read from the drawing and then consumed by nothing at all.
#
# On M&S 2085 the two tubes arrived with no material — the GA states MILD STEEL once, at
# assembly level — and an unidentified part falls through to BOUGHT_IN by default. Being
# bought-in, every fabrication operation was stripped, so the saw and the weld never
# happened, and the outer tube was priced at GBP 86.04 by a market estimate. GBP 2.00 of
# labour on a welded three-part bracket.
#
# A stated family beats a defaulted material, which is all "BOUGHT_IN with nothing else on
# the record" ever was. It does NOT beat catalogue identity — a BI- code, a bought-in page
# role, an explicit flag — because that is the module's founding rule and the failure mode of
# getting it wrong is fabrication labour booked against something we simply buy.
FABRICATED_FAMILIES = frozenset({"metal", "acrylic", "timber", "wire", "tube"})

# Code families that are bought-in by construction. BI- is SDI's own prefix; the rest are
# commercial lines that are never fabricated.
_BOUGHT_IN_PREFIXES = ("BI-", "FIXING", "VINYL", "PACKAGING", "DELIVERY", "POWDER",
                       "THUM", "STD PART")

# Sources that only ever produce bought-in records.
_BOUGHT_IN_SOURCE_TOKENS = ("recogniser", "bought_in", "note_scan", "catalogue")

# Fabrication operations a purchased component can never incur. Handling/assembly is NOT
# here: we do handle and fit bought-in parts, and that bench time is real work.
FABRICATION_OPS = frozenset({
    "laser_cutting", "laser", "punch", "punching", "guillotine", "saw", "tube_cut",
    "folding", "fold", "linebend", "line_bending", "rolling", "roll", "tubebend",
    "tube_bending", "welding", "spot_welding", "spotweld", "resistance_welding",
    "dress_welds", "dressing", "cnc_routing", "cnc", "cnc_machining", "cnc_joinery",
    "pin_router", "edge_banding", "wire_forming", "robomac", "hole_machining",
    "drilling", "deburring", "deburr", "linishing", "glue", "gluing", "glueing",
    "bonding", "powder_coating", "wet_spray", "diamond_polish", "diamond_polishing",
})


# OPERATIONS THAT CAN ONLY HAPPEN TO ONE PIECE OF STOCK, so an assembly cannot incur them —
# they belong to the parts it is made from. A deliberate SUBSET of FABRICATION_OPS, and what
# is left out is the point:
#
#   JOINING stays. Welding, gluing and bonding are what an assembly IS. The route compiler
#   already has a weld-parent rule for exactly this, and stripping welds from a weldment
#   would take the job's real labour out of the estimate.
#   FINISHING stays. A welded frame is powder coated as one thing, after joining, and
#   assembly-level finish is a case this engine handles on purpose.
#
# What remains cuts, forms or dresses a single blank: you cannot laser an assembly, and you
# cannot edge-band one. On job 12392 the panel assembly 12392-02-201 collected cnc_routing,
# edge banding and laminating from an MDF title block on a different sheet of the same pack —
# three joinery operations on a thing that is two steel panels bolted together, each
# unverifiable because no part on the assembly could have incurred them.
#
# The vocabulary lives here beside FABRICATION_OPS on purpose: two lists of operation names
# maintained separately are two lists that disagree the first time one is edited.
LEAF_ONLY_OPS = frozenset({
    "laser_cutting", "laser", "punch", "punching", "guillotine", "saw", "tube_cut",
    "folding", "fold", "linebend", "line_bending", "rolling", "roll", "tubebend",
    "tube_bending", "cnc_routing", "cnc", "cnc_machining", "cnc_joinery", "pin_router",
    "edge_banding", "edgebanding", "laminating", "lamination", "veneering",
    "wire_forming", "robomac", "hole_machining", "drilling", "deburring", "deburr",
    "linishing",
})


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


# The words a draughtsman uses for things that come off a roll or out of a bag. \bTAPE\b is
# a word, so TAPERED does not match; the glued token 10975EPDMCLOSEDCELL does not match
# either, which is fine — its DESCRIPTION says TAPE and the description is checked too.
_CONSUMABLE_RE = re.compile(
    r"\b(?:EPDM|VHB|GASKET|GROMMET|VELCRO|SELF[- ]?ADHESIVE|DOUBLE[- ]SIDED"
    r"|FOAM\s+(?:TAPE|PAD|STRIP)|(?:FELT|FOAM|RUBBER)\s+PAD|HOOK\s+(?:&|AND)\s+LOOP"
    r"|TAPE)\b")


# A STOCK PRODUCT BOUGHT READY-MADE (D-381). 12173-04-04M / 05M, "LOWER / UPPER TIER MESH",
# had no flat and no wire schedule of their own, and were lasered as 1 mm sheet and put on the
# Robomac. The words are config (PURCHASED_STOCK_PRODUCT_WORDS); this is the default.
#
# WHO MAKES IT IS A SEPARATE QUESTION FROM WHAT IT IS CALLED (D-383). D-381's list held bare
# "MESH", so any part named MESH lost its laser, Robomac, weld, dress and deburr on a word,
# and "MDF MESH INFILL" and "MESH FRAME" were ruled bought as well. A welded grid is bought as
# weldmesh or welded here, and neither the word nor a wire gauge says which: a bought weldmesh
# is specified by gauge ("50x50x3") and is welded. So:
#   * a COMPOUND product word (WELDMESH, EXPANDED METAL ...) still rules the part bought, and
#     unless the pack states the purchase (a -X suffix, a supplier or catalogue code) a
#     make-or-buy question is raised beside the ruling;
#   * a QUESTION word (config STOCK_PRODUCT_QUESTION_WORDS: MESH) never rules — the route
#     stays as computed and the question is raised;
#   * bend callouts on the part's own sheet (not copied from a mirrored base) say we form it.
# Weld, wire gauge, wire family and wire_forming ops are not "made" signals here: the pack's
# "RESISTANCE WELDING WIRE TO WIRE" is border legend on every M&S sheet (stock_form_rules,
# D-338), and 12173-04-04M's own FINISH: WELDED is how a bought weldmesh is described too.
_STOCK_PRODUCT_WORDS_DEFAULT = ("WELDMESH", "WELD MESH", "WELDED MESH", "WIRE MESH PANEL",
                                "EXPANDED METAL")
_STOCK_QUESTION_WORDS_DEFAULT = ("MESH",)

# The coats a purchased panel can still take here: a bought mesh is powder coated with the
# frame it sits in when its own sheet says so.
_COAT_OPS = {"powder_coating": "powder", "wet_spray": "wet_spray"}


def _config_words(key: str, default: tuple) -> tuple:
    try:
        import config as _cfg
        words = getattr(_cfg, key, None)
    except Exception:                                            # noqa: BLE001
        words = None
    return tuple(words) if words else default


def _first_word(words: Any, text: str) -> str:
    for w in words or ():
        if re.search(rf"\b{re.escape(str(w).upper())}\b", text):
            return str(w).upper()
    return ""


def _made_on_its_own_sheet(part: Dict[str, Any]) -> bool:
    """Bend callouts printed on the part's OWN sheet — not copied from a mirrored base."""
    if not part.get("drawing_bend_callouts"):
        return False
    try:
        import source_precedence as _sp
        return _sp.source_of(part, "drawing_bend_callouts") != "mirror_of_measured"
    except Exception:                                            # noqa: BLE001
        return True


def _purchase_stated(part: Dict[str, Any]) -> bool:
    """The pack itself says we buy it: SDI's purchased suffix, a supplier or a catalogue code."""
    return bool(part_code_conventions.purchased_suffix(_upper(part.get("part_number")))
                or str(part.get("supplier") or "").strip()
                or str(part.get("catalogue_code") or "").strip()
                or str(part.get("supplier_code") or "").strip())


def make_or_buy_ruling(part: Any) -> str:
    """"buy", "make" or "" — the estimator's answer to the make-or-buy question, stamped from
    config.JOB_DECISIONS[<job>].estimator_decisions.make_or_buy (D-384). A ruling outranks
    every reading below; it is the question's answer, not another reading."""
    if not isinstance(part, dict):
        return ""
    _r = str(part.get("_estimator_make_or_buy") or "").strip().lower()
    return _r if _r in ("buy", "make") else ""


def _stock_product_candidate(part: Dict[str, Any]) -> bool:
    """No measured flat, not an assembly, no wire or bar schedule, no bend callouts of its own."""
    if not isinstance(part, dict) or has_fabrication_evidence(part):
        return False
    if make_or_buy_ruling(part) == "make":
        return False
    if part.get("is_assembly_parent") or part.get("is_sub_assembly") \
            or part.get("assembly_children"):
        return False
    if part.get("_bar_recognised") or part.get("wire_schedule") or part.get("bar_schedule"):
        return False
    return not _made_on_its_own_sheet(part)


def purchased_stock_product(part: Dict[str, Any]) -> str:
    """The stock-product word this part's own description names, or "" (D-381, D-383).

    Never for a part with measured flat geometry, an assembly, a wire or bar schedule, or bend
    callouts on its own sheet — those are things we cut or form, whatever they are called. A
    QUESTION word (MESH) never rules; see make_buy_question."""
    if not _stock_product_candidate(part):
        return ""
    text = " ".join(_upper(part.get(k)) for k in ("description", "name"))
    return _first_word(_config_words("PURCHASED_STOCK_PRODUCT_WORDS",
                                     _STOCK_PRODUCT_WORDS_DEFAULT), text)


def make_buy_question(part: Dict[str, Any]) -> Dict[str, Any]:
    """The make-or-buy question a stock-product name leaves open, or {} when none (D-383).

    {"word", "ruled" ("bought" or ""), "why"}. A compound product word with nothing on the
    pack stating the purchase is ruled bought AND asked; a question word is only asked. A part
    whose purchase is stated, or that we evidently make, raises nothing."""
    if make_or_buy_ruling(part) or not _stock_product_candidate(part):
        return {}                       # answered by the estimator, or not a candidate
    text = " ".join(_upper(part.get(k)) for k in ("description", "name"))
    w = _first_word(_config_words("PURCHASED_STOCK_PRODUCT_WORDS",
                                  _STOCK_PRODUCT_WORDS_DEFAULT), text)
    if w:
        if _purchase_stated(part):
            return {}
        return {"word": w, "ruled": "bought",
                "why": (f"its description names a stock product ({w}) and it has no flat, "
                        f"wire schedule or bend callouts of its own; nothing on the pack "
                        f"(a -X suffix, a supplier, a catalogue code) says it is bought")}
    q = _first_word(_config_words("STOCK_PRODUCT_QUESTION_WORDS",
                                  _STOCK_QUESTION_WORDS_DEFAULT), text)
    if q:
        return {"word": q, "ruled": "",
                "why": (f"it is described as {q}, with no flat, wire schedule or bend callouts "
                        f"of its own; the pack does not say whether it is bought ready-made "
                        f"or made here")}
    return {}


def keeps_its_coat(part: Dict[str, Any], op: Any) -> bool:
    """A purchased stock product keeps a coat its OWN sheet states (powder, wet spray)."""
    fam = _COAT_OPS.get(str(op or "").lower())
    if not fam or not (purchased_stock_product(part) or make_or_buy_ruling(part) == "buy"):
        return False
    try:
        from finish_rules import finish_families, stated_finish
    except Exception:                                            # noqa: BLE001
        return False
    return fam in finish_families(stated_finish(part))


def _is_named_consumable(part: Dict[str, Any]) -> bool:
    text = " ".join(_upper(part.get(k)) for k in ("description", "part_number", "name"))
    return bool(_CONSUMABLE_RE.search(text))


def bought_in_reason(part: Dict[str, Any]) -> str:
    """WHICH rule decided, in words, or "" for a part we make.

    is_bought_in returns a bare boolean, and when a part turned out to be classified wrongly
    there was no way to tell which of seven rules had fired without reading the record by
    hand. This returns the answer and the reason together so a wrong classification is
    diagnosable from the run itself."""
    if not isinstance(part, dict):
        return ""
    # THE ESTIMATOR'S RULING FIRST (D-384). A make-or-buy answer from config.JOB_DECISIONS is
    # the question settled by a person, and it is read before any reading below.
    if make_or_buy_ruling(part) == "buy":
        return (f"ruled bought in by {part.get('_estimator_make_or_buy_by') or 'the estimator'} "
                f"(estimator_decisions.make_or_buy)")
    # Catalogue identity first — these are the strong signals and they are not overridable.
    if part.get("is_bought_in") or part.get("_bought_in_from_text_scan"):
        return "flagged bought-in on the record"
    _roles = [str(r).strip().lower() for r in (part.get("page_roles") or [])]
    if "bought_in" in _roles:
        # A PAGE ROLE THAT CONTRADICTS ITSELF IS NOT AUTHORITY. 12392's mounting brackets
        # carry BOTH "detail" and "bought_in": one page reads as a detail sheet for a part we
        # cut, another as a bought-in listing. That is two readings of the same code
        # disagreeing, not a catalogue statement — and taken as decisive it stripped the
        # laser and the fold from two steel brackets the workbook then had to put back.
        #
        # Only a SECOND positive signal overturns it, so this cannot be reached by absence:
        # the part must both be drawn as a detail AND carry SDI's own material-suffix
        # convention, which is a code written by whoever drew it. Two statements that we make
        # the part, against one that reads it as bought. Every stronger rule — an explicit
        # flag, a bought-in-only source, a BI- code family — is checked before this and is
        # untouched.
        _detailed = any(r in {"detail", "fabricated", "flat_pattern"} for r in _roles)
        if not (_detailed and part_code_conventions.material_suffix(_upper(part.get("part_number")))):
            return "the drawing page is a bought-in page"
    src = str(part.get("source") or "").lower()
    for tok in _BOUGHT_IN_SOURCE_TOKENS:
        if tok in src:
            return f"read from a bought-in-only source ({tok})"
    if _upper(part.get("part_number")).startswith(_BOUGHT_IN_PREFIXES):
        return "the part number is a bought-in code family"
    # THE PRINTED CODE IS A PURCHASE CLASS. SDI prints "P/P" (or a bare "FIXING") in the code
    # column of a line it buys, and part_identity gives each such row an identity of
    # "<class>-<its words>" so the articles stay apart. The class word is the drawing saying
    # "we buy this" — and this module did not read it. 12567-02-GA's LED driver, printed P/P,
    # inherited the GA's MILD STEEL, was handed an 80 x 40 x 1.5 blank by the sibling borrow,
    # nested on the Sheet Steel block, lasered and powder coated (D-263).
    _pn = _upper(part.get("part_number"))
    _head = re.split(r"[-\s]", _pn, 1)[0] if _pn else ""
    if _head and part_code_conventions.is_category_not_a_code(_head):
        return f"the printed code is a purchase class word ({_head}), not a part we cut"
    # A CATALOGUE FAMILY CODE: a word and a number and nothing else. FIXING49, THUM620 and
    # MAGNET21 are SDI's own purchasing codes for standard articles — a family name and a
    # sequence number — and nothing SDI cuts is numbered that way: a drawing number opens with
    # the job number and carries hyphenated segments (part_code_conventions). The families
    # this module listed by name (FIXING, THUM) are the two that had bitten; MAGNET21 was the
    # third, and was given a 400 x 300 blank, a place in a fold row and a powder coat. The
    # shape is the rule, not the list. Measured geometry of the part's own still outranks it.
    if _pn and re.fullmatch(r"[A-Z]{3,}\d{1,6}", _pn) and not has_fabrication_evidence(part):
        return "a catalogue family code (a word and a number, no drawing segments), not a drawing number"
    # SDI'S OWN SUFFIX, AVAILABLE FROM THE FIRST STAGE — which is the whole point of it
    # being here. The same letter is already read this way at costing:
    # estimator._is_special_bought_in_item calls "-X" a "Special / bought-in FINISHING item"
    # that carries "no saw/glue/CNC/laser/weld fab labour", strips those ops, and appends
    # "bought_in" to page_roles. That is the seventh rule this module was written to absorb
    # and the only one it missed.
    #
    # MISSING IT COST THE WHOLE MILWAUKEE BEARING. On a code like "12552-01-01X" the
    # estimator's append is the ONLY thing that ever sets the bought_in role, because
    # document_builder's retag skips anything matching ^\d{3,5}- as an SDI drawing reference
    # — a rule written to protect the parts we cut, which protected the purchases with them.
    # So at geometry_inference the bearing's roles were ['assembly'] and this predicate said
    # False; it was handed 12552-01-01M's 650.7 x 178.7 flat by the sibling borrow, read as
    # sheet metal, given a laser op and 269 seconds. By the time anything printed the record
    # the role was on it, so the run looked consistent with itself.
    #
    # It sits BELOW the page-role rule, not above, so the "detail + material suffix"
    # override there is untouched — and an "-X" code cannot reach that override anyway,
    # since material_suffix admits only T/M/A. Above the material-family defaults below,
    # because a letter the draughtsman wrote is a statement and "we could not identify the
    # material" is an absence.
    if part_code_conventions.purchased_suffix(_upper(part.get("part_number"))):
        return "SDI's numbering marks it bought (-X), not a part we cut"

    # A CONSUMABLE NAMED AS ONE. "EPDM TAPE 25X1MM - TAPE 113C" is not a part anybody cuts,
    # whatever material string it inherited from the assembly that configured it. On
    # 10975-02 the tape arrived wearing the GA's ACRYLIC, classified as a leaf, claimed the
    # GA page, and left the route compiler welded, dressed and powder-coated — £120 of the
    # job's £163 labour on three strips of foam tape. The description is the draughtsman's
    # own word for what the thing is, and it outranks an inherited material. Geometry still
    # outranks the name: a part with fabrication evidence of its own is not a consumable
    # however it is described, and an SDI material-suffix code stays ours to cut.
    if _is_named_consumable(part) and not has_fabrication_evidence(part) \
            and not part_code_conventions.material_suffix(_upper(part.get("part_number"))):
        return "a named consumable (tape / gasket / adhesive) with no fabrication evidence"

    # A STOCK PRODUCT, NAMED AS ONE (D-381). No material-suffix exemption: SDI numbers a
    # bought mesh panel "-M" like any steel part, and the suffix says steel, not who makes it.
    _stock = purchased_stock_product(part)
    if _stock:
        return (f"a purchased stock product ({_stock}) with no flat pattern or wire schedule "
                f"of its own")

    fam = str(part.get("material_family") or "").strip().lower()
    if fam == "bought_in":
        return "the drawing classifies it as a purchased component"
    if _upper(part.get("normalized_material")) == "BOUGHT_IN" or _upper(part.get("material")) == "BOUGHT_IN":
        # The weakest signal there is: "we could not identify the material". A family read
        # from the drawing is a positive statement and outranks that absence.
        if fam in FABRICATED_FAMILIES:
            return ""
        # SO IS THE PART NUMBER. "12392-04-01M" is not a name; it is SDI's own convention for
        # a part we cut in metal (-M steel, -A acrylic, -T MDF), and it is written by the
        # person who drew it. That is a statement about what the part IS, from the drawing,
        # in exactly the way a stated family is — so it stops the same default, and only that
        # default. Every catalogue rule above has already returned: a BI- code, a bought-in
        # page role, a bought-in-only source and an explicit flag all outrank this and are
        # untouched, which matters because the cost of getting THIS wrong is a purchased item
        # carrying laser and fold time.
        #
        # Two independent paths reached the same wrong answer on 12392 and this is the second
        # one. The first was json_normaliser never consulting the convention when the material
        # text was noise rather than blank; fixing it there means these brackets arrive as
        # MILD_STEEL and never reach this branch. But a part can be stamped BOUGHT_IN by other
        # routes, and a rule that holds in one module and not the other is not one rule.
        if part_code_conventions.material_suffix(_upper(part.get("part_number"))):
            return ""
        return "no material was identified, so it defaulted to bought-in"
    return ""


def is_bought_in(part: Dict[str, Any]) -> bool:
    """True when the part is purchased rather than made.

    Union of every rule the codebase previously applied separately, so adopting this
    predicate cannot make any consumer classify FEWER parts as bought-in than before — with
    one deliberate exception, documented at FABRICATED_FAMILIES: a part the drawing puts in a
    fabricated family is not bought-in merely because its material went unidentified."""
    return bool(bought_in_reason(part))


def has_fabrication_evidence(part: Dict[str, Any]) -> bool:
    """POSITIVE evidence that SDI makes this part: measured flat geometry of its own.

    Deliberately narrow. A drawing, a material or a thickness is not evidence — bought-in
    components have all three. Only geometry we could actually cut from counts."""
    if not isinstance(part, dict):
        return False
    # An explicit "nothing was measured" outranks every positive marker below. flat_pattern
    # _detected is also set from drawing EXTENTS as a fallback (drawing_job_merge), which is
    # not measured geometry, and being checked first it let a matched-but-unreadable DXF
    # count as evidence — the exact case this predicate was narrowed to exclude.
    #
    # "No blank was measured" is NOT "nothing was measured". A DXF whose cut layer yields a
    # measured cut path but no closed outline has told us something real: a profile is being
    # cut. Only the blank claim is absent, and only the blank claim gates the allowance. The
    # two used to share dxf_measured_outline, so withdrawing the blank claim would otherwise
    # take the part's fabrication evidence with it and make something we cut look purchased.
    #
    # THE OPPOSITE HAND OF A MEASURED FLAT IS MEASURED TOO — and that clause used to sit
    # last, below this exit, so a hand whose own DXF matched and measured nothing was ruled
    # unmeasured before the mirrored flat it carries was ever looked at (D-280). The mirror
    # copies only from a base measured at DXF or model rank; it is read first.
    _ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"),
                                                           dict) else {}
    _mirrored = (str(_ng.get("geometry_source") or "").lower() == "mirror_of_measured"
                 and bool(_ng.get("mirrored_from")))
    if (part.get("dxf_measured_outline") is False
            and not part.get("dxf_measured_cut_length")
            and not part.get("native_flat_pattern")
            and not _mirrored):
        return False
    if part.get("flat_pattern_detected") or part.get("native_flat_pattern"):
        return True
    # dxf_augmented is set ONLY where an outline was actually measured. dxf_source_file is
    # deliberately NOT accepted: it records that a file MATCHED, which since the reader
    # learned to distinguish the two can be true with nothing measured at all (a flat
    # exported as an unreadable block, say). Counting it would make "a DXF exists" into
    # fabrication evidence again — the very thing this predicate is narrow to avoid — and
    # would raise a make/buy conflict on a purchased part that merely has a drawing.
    if part.get("dxf_augmented") or part.get("dxf_measured_outline"):
        return True
    _gs = str(part.get("geometry_source") or "").lower()
    if "dxf" in _gs and _gs != "dxf_matched_no_geometry":
        return True
    # THE OPPOSITE HAND OF A MEASURED FLAT IS MEASURED TOO. apply_mirror_geometry copies a
    # flat only from a base whose own geometry ranks at DXF or model, so "mirror_of_measured"
    # is a measured flat one step removed. 11650-06's Mirror11650-03-02M was nested, lasered
    # and folded from the plain arm's flat, and still classified bought-in from the kit page
    # it was listed on — so every tab called a part the sheet cuts a catalogue component.
    return _mirrored


def looks_fabricated_for_identity(part: Dict[str, Any]) -> bool:
    """A LOWER bar than has_fabrication_evidence, for a narrower and more destructive
    question: may these two identities be merged into one node?

    has_fabrication_evidence decides make-or-buy, so it demands measured geometry and
    nothing less — a drawing, a material and a thickness are things a bought-in component
    has too. That bar is right for classification and wrong here, because the consequences
    are not symmetric.

    Refusing a merge costs a visible extra row an estimator can look at and resolve.
    Allowing a wrong one hands a fabricated leaf's identity to something we purchase, and
    its laser, fold and weld go with it — silently, because the row it was on is gone.

    So a part with a leaf-only operation read against it counts here even without measured
    geometry. You do not laser-cut or fold something you buy in, and if the note scan has
    put those against a purchased part, that is a mis-read worth seeing rather than a
    reason to merge.
    """
    if has_fabrication_evidence(part):
        return True
    ops = {str(o).strip().lower().replace(" ", "_")
           for o in (part.get("textual_operations") or [])}
    ops |= {str(o).strip().lower().replace(" ", "_")
            for o in ((part.get("manufacturing_interpretation") or {}).get("operations") or [])}
    return bool(ops & LEAF_ONLY_OPS)


def bought_in_conflict(part: Dict[str, Any]) -> bool:
    """Bought-in by identity, yet carrying its own measured geometry — the two sources
    disagree about what this part is. Flagged for an estimator, never auto-resolved."""
    return is_bought_in(part) and has_fabrication_evidence(part)


def assembly_reason(part: Dict[str, Any]) -> str:
    """WHY this record is a parent rather than a part we cut, in words, or "" for a leaf.

    THE SAME IDEA UNDER FOUR NAMES. estimator.py's own comment records the defect: "both
    suppressions here and in estimate_part keyed on is_assembly_parent, a different name for
    the same idea", and 12120-01-103 was correctly identified as a sub-assembly from the GA
    tree while still being given sheet material, a laser and a fold — because the field that
    said so was not the field that pass read. The canonical graph adds a fifth spelling,
    canonical_kind.

    A union, deliberately, exactly as is_bought_in is: adopting this predicate cannot make
    any consumer recognise FEWER assemblies than it did before. That is what makes it safe to
    introduce into a costing path — the failure direction is a parent charged as a leaf,
    which is material and fabrication booked twice, and a union can only reduce it.

    It does NOT decide anything about geometry. A part with its own measured flat is a
    fabricated leaf whatever a transcribed hierarchy says, and that arbitration stays where
    it is, in the caller that holds the measurement.
    """
    if not isinstance(part, dict):
        return ""
    if str(part.get("canonical_kind") or "").strip().lower() == "assembly":
        return "the canonical part graph compiled it as an assembly"
    if part.get("is_assembly_parent"):
        return "flagged an assembly parent on the record"
    if part.get("is_sub_assembly"):
        return "the drawing's hierarchy names it as a sub-assembly"
    if part.get("assembly_children"):
        return "it names children of its own"
    return ""


def is_assembly(part: Dict[str, Any]) -> bool:
    """True when the record is a parent: its material and leaf work belong to its children."""
    return bool(assembly_reason(part))


def strip_leaf_operations(part: Dict[str, Any]) -> List[str]:
    """Remove single-blank operations from an ASSEMBLY, in place. Returns what was removed.

    Deliberately mirrors strip_fabrication_ops, because it is the same shape of mistake in
    the other direction: there, a purchased part carrying work we never did; here, a parent
    carrying work that belongs to its children. Both put labour on a record that cannot have
    incurred it, and both were flagged for an estimator and then charged anyway.

    Does nothing unless the record is already classified as an assembly. That classification
    is the canonical graph's to make and this never second-guesses it — a part wrongly called
    an assembly is a different defect, and silently stripping its route would hide it.
    """
    if not (part.get("is_assembly_parent") or part.get("is_sub_assembly")
            or str(part.get("canonical_kind") or "").lower() == "assembly"):
        return []
    removed: List[str] = []
    # EDGING THE ASSEMBLY'S OWN PARTS LIST STATES IS THE ASSEMBLY'S. 12173-03-01J is a glued
    # stack of two numbered 25 mm discs (D-378) and its own parts list states "EDGING, L:
    # 1979mm" (D-381). As an assembly it lost edge_banding here, so the stated length had no
    # operation left to price it — the banding vanished without a word. A stated length on
    # the assembly's own sheet keeps the op there, and whether the edge is banded once on the
    # joined stack or on each piece is asked, never decided either way in silence.
    try:
        _stated_band = float(part.get("stated_banded_length_mm") or 0.0)
    except (TypeError, ValueError):
        _stated_band = 0.0
    _kept_stated = False
    for field in ("textual_operations", "inferred_operations"):
        vals = part.get(field)
        if not isinstance(vals, list):
            continue
        kept: List[Any] = []
        for op in vals:
            _low = str(op).strip().lower()
            if _low in LEAF_ONLY_OPS:
                if _stated_band > 0 and _low in ("edge_banding", "edgebanding"):
                    kept.append(op)
                    _kept_stated = True
                    continue
                if str(op) not in removed:
                    removed.append(str(op))
            else:
                kept.append(op)
        part[field] = kept
    if _kept_stated:
        _q = {
            "issue": (f"Is the edging {part.get('part_number')} states on its own parts list "
                      f"({_stated_band:g} mm) applied once to the joined assembly, or to each "
                      f"of its pieces?"),
            "assumption": ("charged on the assembly at the stated length; edging any of its "
                           "pieces carries of its own is charged as well"),
            "action": ("if the stack is banded once after joining, strike the pieces' edging; "
                       "if each piece is banded, strike the assembly's"),
            "source": "bought_in_policy.strip_leaf_operations",
            "subject": "edge_banding",
            "charged_operations": ["edge_banding"],
        }
        _qs = part.setdefault("manufacturing_questions", [])
        if isinstance(_qs, list) and not any(
                isinstance(x, dict) and x.get("issue") == _q["issue"] for x in _qs):
            _qs.append(_q)
    return removed


def strip_fabrication_ops(part: Dict[str, Any]) -> List[str]:
    """Remove fabrication operations from a bought-in part, in place.

    Returns what was removed so the caller can flag it. Does nothing to a part that is not
    bought-in, and never touches handling/assembly — fitting a purchased component is real
    bench time and must keep being charged."""
    if not is_bought_in(part):
        return []
    removed: List[str] = []
    for field in ("textual_operations", "inferred_operations"):
        vals = part.get(field)
        if not isinstance(vals, list):
            continue
        kept: List[Any] = []
        for op in vals:
            if str(op).lower() in FABRICATION_OPS and not keeps_its_coat(part, op):
                if str(op) not in removed:
                    removed.append(str(op))
            else:
                kept.append(op)
        part[field] = kept
    return removed
