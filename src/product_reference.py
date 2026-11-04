"""The product a drawing names for a part, read off the part's own title block (D-386).

12173-03-03J, an 18 mm MFC back panel: COLOUR "UNILIN MINNESOTA OAK WARM NATURAL 0H440
MINNESOTA OAK (Z5L)". That is a manufacturer, a decor name and two product references — the
exact thing a purchasing system files a board under and a supplier lists it by — and the
price ladder never saw it: SDI Live was asked for "MFC" and the market for "18mm MFC board",
and the panel went out at £0 while the drawing had said what to buy.

One reader, for every line: the fields a drawing office uses to name a product (config
PRODUCT_REFERENCE_FIELDS — colour, finish, the printed material cell), split into the codes
(letters-and-digits tokens such as 0H440, Z5L, WSF45, or a plain 6-digit article number) and
the decor words (MINNESOTA, OAK, UNILIN), with colour-standard codes (RAL 9005, BS 00 E 53)
set aside because they name a colour, not a product. Leaf module: imports nothing of the
engine, so the price chain, the pricing service and the researcher can all ask it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_FIELDS_DEFAULT = ("colours", "colour", "normalized_colour", "surface_finishes", "finish",
                   "material_text_as_printed", "decor", "product_reference")
# Words that qualify a colour or finish and never name a product.
_STOP_DEFAULT = (
    "MATT", "MATTE", "GLOSS", "SATIN", "SILK", "TEXTURED", "TEXTURE", "SMOOTH", "FINISH",
    "COLOUR", "COLOR", "NATURAL", "WARM", "COOL", "LIGHT", "DARK", "SOFT", "DEEP", "PALE",
    "RAW", "POWDER", "COATED", "COAT", "WET", "SPRAYED", "SPRAY", "PAINTED", "PAINT", "LACQUER",
    "LACQUERED", "PLATED", "PLATING", "ANODISED", "POLISHED", "BRUSHED", "WELDED", "BARE",
    "SELF", "MILL", "NONE", "BLACK", "WHITE", "GREY", "GRAY", "RED", "BLUE", "GREEN", "YELLOW",
    "SILVER", "GOLD", "CLEAR", "OPAL", "AND", "WITH", "THE", "ALL", "OVER", "SIDE", "SIDES",
    "FACE", "FACES", "ONLY", "TOP", "BOTTOM", "SEE", "NOTE", "DRAWING", "DRG", "REV",
    "JET", "IVORY", "CREAM", "BEIGE", "BROWN", "ORANGE", "PURPLE", "PINK", "ANTHRACITE",
    "GRAPHITE", "CHARCOAL", "BRONZE", "COPPER", "CHROME", "NICKEL", "ZINC", "BRASS",
)
# Colour standards: a code after one of these names a shade, not a product.
_EXCLUDE_PREFIX_DEFAULT = ("RAL", "BS", "NCS", "PANTONE", "PMS")

_PLACEHOLDERS = {"N/A", "NA", "TBC", "TBA", "NONE", "-", "--", "—", "?", "SEE DRAWING", "AS DRAWING"}

_CODE = re.compile(r"(?<![A-Z0-9])(?:(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{3,10}|\d{5,8})(?![A-Z0-9])")
_SIZE = re.compile(r"^\d+(?:\.\d+)?(?:X\d+(?:\.\d+)?)+(?:MM)?$|^\d+(?:\.\d+)?MM$|^M\d{1,2}$")


def _cfg(key: str, default: Iterable[Any]) -> tuple:
    try:
        import config as _c
        v = getattr(_c, key, None)
    except Exception:                                            # noqa: BLE001
        v = None
    return tuple(str(x).upper() for x in (v or default))


def _texts(part: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(part, dict):
        return out
    for f in _cfg("PRODUCT_REFERENCE_FIELDS", _FIELDS_DEFAULT):
        v = part.get(f.lower()) if f.lower() in part else part.get(f)
        if isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v if str(x or "").strip())
        elif str(v or "").strip():
            out.append(str(v))
    seen: set = set()
    uniq: List[str] = []
    for t in out:
        k = " ".join(t.upper().split())
        # A placeholder names nothing: "N/A", "TBC", "-" in a finish cell is the drawing
        # saying there is no finish, not a product called N/A.
        if k in _PLACEHOLDERS or not re.search(r"[A-Z0-9]", k):
            continue
        if k and k not in seen:
            seen.add(k)
            uniq.append(" ".join(t.split()))
    return uniq


def product_reference(part: Any) -> Dict[str, Any]:
    """{"text", "codes", "words"} — what the drawing names this part's product as, or empty.

    text   the title-block fields joined, as printed (cleaned of whitespace)
    codes  manufacturer / article references (0H440, Z5L, WSF45, 844300), colour standards
           (RAL 9005) and sizes (15X10MM, M6) set aside
    words  decor and maker words of four letters or more that are not colour or finish
           qualifiers (UNILIN, MINNESOTA, OAK), longest first, no repeats
    """
    texts = _texts(part)
    if not texts:
        return {"text": "", "codes": [], "words": []}
    up = " ".join(texts).upper()
    stop = set(_cfg("PRODUCT_REFERENCE_STOP_WORDS", _STOP_DEFAULT))
    excl = _cfg("PRODUCT_REFERENCE_EXCLUDE_PREFIXES", _EXCLUDE_PREFIX_DEFAULT)
    codes: List[str] = []
    for m in _CODE.finditer(up):
        tok = m.group(0)
        if _SIZE.match(tok) or tok in stop:
            continue
        # A colour-standard code: "RAL9005", or "RAL 9005" (the digits follow the standard).
        if any(tok.startswith(p) and tok[len(p):].isdigit() for p in excl):
            continue
        before = up[:m.start()].rstrip()
        if any(before.endswith(p) for p in excl) and tok.isdigit():
            continue
        if tok not in codes:
            codes.append(tok)
    words: List[str] = []
    for w in re.findall(r"[A-Z]{3,}", up):
        if w in stop or w in words or len(w) < 3:
            continue
        if any(w == p for p in excl):
            continue
        words.append(w)
    words.sort(key=lambda w: (-len(w), w))
    return {"text": "; ".join(texts), "codes": codes, "words": words}


# A board maker's texture codes (config DECOR_TEXTURE_CODES): Egger's ST2, ST10, PM, PT.
_TEXTURE_DEFAULT = (r"ST\d{1,3}", "PM", "PT", "PG", "HG", "SM", "MT", "PE", "SU")


def _texture_re() -> "re.Pattern[str]":
    try:
        import config as _c
        pats = getattr(_c, "DECOR_TEXTURE_CODES", None) or _TEXTURE_DEFAULT
    except Exception:                                            # noqa: BLE001
        pats = _TEXTURE_DEFAULT
    # Not upper-cased: that would turn the pattern's \d into \D. The codes it is asked of are.
    return re.compile("^(?:" + "|".join(str(p) for p in pats) + ")$")


def _code_re(code: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])")


def decor_textures(part: Any) -> List[Dict[str, str]]:
    """Each décor the drawing names as a décor code WITH its texture code (D-693), as
    [{"decor": "U999", "texture": "ST2", "as_printed": "EGGER: U999 ST2"}], or [].

    12693-01-04J prints COLOUR: EGGER: U999 ST2. U999 is the décor and ST2 the texture, and
    SDI Live holds U999 in PM and PT: three different boards under one décor code. The texture
    is the code printed straight after the décor code that is one of a maker's texture codes
    (config DECOR_TEXTURE_CODES); a décor printed with no texture after it is not paired, and
    is looked up as before."""
    texts = _texts(part)
    if not texts:
        return []
    tex = _texture_re()
    codes = [c for c in product_reference(part)["codes"] if not tex.match(c)]
    out: List[Dict[str, str]] = []
    seen: set = set()
    for t in texts:
        up = " ".join(t.upper().split())
        for code in codes:
            for m in re.finditer(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])[\s:;,/-]*"
                                 rf"([A-Z0-9]+)", up):
                if tex.match(m.group(1)) and (code, m.group(1)) not in seen:
                    seen.add((code, m.group(1)))
                    out.append({"decor": code, "texture": m.group(1),
                                "as_printed": " ".join(t.split())})
    return out


def decor_on_row(description: Any, pairs: Iterable[Dict[str, str]]) -> Dict[str, Any]:
    """What a catalogue row says of the drawn décor and texture (D-693).

    {"decor": the drawn décor code the row carries or None, "texture": True when the row also
    carries that décor's drawn texture, "row_texture": the texture code printed after the décor
    on the row, if any}. Whole words: TEXTUREDU999 is not U999, ST22 is not ST2; the texture may
    be glued to its décor ("U999ST2")."""
    up = " ".join(str(description or "").upper().split())
    tex = _texture_re()
    got: Dict[str, Any] = {"decor": None, "texture": False, "row_texture": None}
    for p in pairs or ():
        d, t = str(p.get("decor") or "").upper(), str(p.get("texture") or "").upper()
        if not d or not _code_re(d).search(up):
            if d and t and _code_re(d + t).search(up):
                return {"decor": d, "texture": True, "row_texture": t}
            continue
        after = re.search(rf"(?<![A-Z0-9]){re.escape(d)}(?![A-Z0-9])[\s:;,/-]*([A-Z0-9]+)", up)
        row_t = after.group(1) if after and tex.match(after.group(1)) else None
        has_t = bool(t) and (bool(_code_re(t).search(up)) or bool(_code_re(d + t).search(up)))
        if has_t:
            return {"decor": d, "texture": True, "row_texture": row_t or t}
        if got["decor"] is None:
            got = {"decor": d, "texture": False, "row_texture": row_t}
    return got


def reference_probes(part: Any, limit: int = 6) -> List[str]:
    """The tokens to look a product up by in a catalogue, most specific first: every code,
    then the longest decor words. Bounded, because each is a catalogue query.

    A DÉCOR WITH ITS TEXTURE IS ASKED BY ITS DÉCOR CODE ONLY (D-693). The texture alone (ST2)
    answers for every décor in that texture and the maker's name (EGGER) for every décor the
    maker makes; neither is the product. The row the décor code finds is the product only when
    it carries the texture too, which the caller checks with decor_on_row."""
    pairs = decor_textures(part)
    if pairs:
        out: List[str] = []
        for p in pairs:
            if p["decor"] not in out:
                out.append(p["decor"])
        return out[:limit]
    ref = product_reference(part)
    out = list(ref["codes"]) + list(ref["words"])
    return out[:limit]


def describe_product(part: Any) -> str:
    """The product, in the words a buyer would use: the printed fields, joined."""
    return product_reference(part)["text"]
