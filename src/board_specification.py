"""What a drawing specifies for a board beyond its family, and whether a catalogue row is it (D-693).

12693-01-04J LARGE TOP INSERT. Its own sheet prints MATERIAL: MRMDF and COLOUR: EGGER: U999 ST2:
a moisture-resistant MDF, in Egger's décor U999 in texture ST2. Its pieces are 18 and 12 mm board,
and the workbook priced them from a generic 18 mm MDF sheet at £38.49. A reviewer: "A generic
£38.49 MDF sheet rate does not establish that the required moisture-resistant board and surface
specification are included ... not an assumption that every décor means applied laminate."

Two readings were lost before the catalogue was asked. The GRADE: MR MDF is MDF for the rate key,
the density and the block, and the sheet-rate search reads MR as a qualifier, so a row for any
MDF answered for moisture-resistant MDF. The DÉCOR: SDI Live was asked for U999, which it holds in
PM and PT, and a row in either would have been called the product.

So the board's specification is read once, here: the grade the part's own material words state
(config BOARD_GRADES), the décor-and-texture pairs its product reference names
(product_reference.decor_textures), and the substrate its family is (config
BOARD_SUBSTRATE_BY_WORD). A catalogue row is judged against it; the rows that price a line are the
ones that meet the most of it, and what they do not meet is said, so a figure from plain MDF is
never presented as the specified board. Nothing here decides what the décor is made of: a décor
is a stated requirement, not a laminate construction.

Leaf module: imports nothing of the engine, so the price chain and its tests can both ask it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

_GRADES_DEFAULT = {
    "MR": {"name": "moisture resistant", "spellings": ("MR", "MOISTURE RESISTANT")},
    "FR": {"name": "fire retardant", "spellings": ("FR", "FIRE RETARDANT", "FLAME RETARDANT")},
    "EXT": {"name": "exterior", "spellings": ("EXT", "EXTERIOR")},
}
_SUBSTRATE_DEFAULT = {"MDF": "MDF", "MFMDF": "MDF", "MFC": "CHIPBOARD", "CHIPBOARD": "CHIPBOARD",
                      "PLY": "PLYWOOD", "PLYWOOD": "PLYWOOD", "OSB": "OSB",
                      "HARDBOARD": "HARDBOARD"}
# The fields a part's material is stated in (the D-688 pieces carry the same ones).
_MATERIAL_FIELDS = ("material_text_as_printed", "material_stated", "material", "materials",
                    "material_grade", "normalized_material")
_GAUGE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*MM\b\s*", re.IGNORECASE)


def _cfg(key: str, default: Any) -> Any:
    try:
        import config as _c
        v = getattr(_c, key, None)
    except Exception:                                            # noqa: BLE001
        v = None
    return v or default


def _grades() -> Dict[str, Dict[str, Any]]:
    return {str(k).upper(): dict(v) for k, v in (_cfg("BOARD_GRADES", _GRADES_DEFAULT)).items()}


def _substrates() -> Dict[str, str]:
    return {str(k).upper(): str(v).upper()
            for k, v in (_cfg("BOARD_SUBSTRATE_BY_WORD", _SUBSTRATE_DEFAULT)).items()}


def _words(text: Any) -> List[str]:
    """The words of a text, upper case, with a dotted or slashed two-letter grade closed up:
    "M.R. MDF" and "M/R MDF" are MR MDF."""
    up = str(text or "").upper().replace("_", " ")
    up = re.sub(r"(?<![A-Z0-9])([A-Z])\s*[./]\s*([A-Z])(?![A-Z0-9])\.?", r"\1\2", up)
    return [w for w in re.split(r"[^A-Z0-9]+", up) if w]


def substrates_in(text: Any) -> List[str]:
    """The board substrates a text names (MDF, CHIPBOARD ...), a grade glued to a board word
    ("MRMDF") included, in order and once each. Whole runs of letters: SUPPLY is not PLY."""
    subs, codes = _substrates(), list(_grades())
    out: List[str] = []
    for run in re.findall(r"[A-Z]+", str(text or "").upper()):
        s = subs.get(run)
        if s is None:
            for c in codes:
                if run.startswith(c) and subs.get(run[len(c):]):
                    s = subs[run[len(c):]]
                    break
        if s and s not in out:
            out.append(s)
    return out


def grades_in(text: Any) -> List[str]:
    """The grade codes a text states: a spelling as whole words, or the code glued to a board
    word ("MRMDF", "FRMDF")."""
    words = _words(text)
    if not words:
        return []
    phrase = f" {' '.join(words)} "
    runs = re.findall(r"[A-Z]+", " ".join(words))
    subs = _substrates()
    out: List[str] = []
    for code, g in _grades().items():
        spellings = [code] + [str(s) for s in (g.get("spellings") or ())]
        hit = any(f" {' '.join(_words(s))} " in phrase for s in spellings if _words(s))
        if not hit:
            hit = any(r.startswith(code) and r[len(code):] in subs for r in runs)
        if hit and code not in out:
            out.append(code)
    return out


def _material_texts(part: Dict[str, Any], material: Any) -> List[Tuple[str, str]]:
    """(field, text) for every material wording on the part, then the family asked for."""
    out: List[Tuple[str, str]] = []
    for f in _MATERIAL_FIELDS:
        v = part.get(f)
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            s = " ".join(str(x or "").split())
            if s and s not in {t for _f, t in out}:
                out.append((f, s))
    m = " ".join(str(material or "").replace("_", " ").split())
    if m and m not in {t for _f, t in out}:
        out.append(("material_asked", m))
    return out


def _substrate_of(part: Dict[str, Any], material: Any) -> Optional[str]:
    """The board the part is: the family asked for where it names one, else its own words."""
    subs = substrates_in(material)
    if subs:
        return subs[0]
    if str(material or "").strip():
        return None                      # asked as something that is not a board
    for _f, t in _material_texts(part, None):
        subs = substrates_in(t)
        if subs:
            return subs[0]
    return None


def board_grade(part: Any, material: Any = None) -> List[Dict[str, str]]:
    """The grades the part's own material words state, each {"code", "name", "as_printed"};
    [] when none is stated or the part is not a board (a grade is a board's).

    A grade is taken only from words about THIS board: a text naming the part's substrate
    ("MRMDF", "18mm MR MDF"), or the part's own grade field ("MR"). A text naming another
    material says nothing about this one."""
    if not isinstance(part, dict):
        return []
    sub = _substrate_of(part, material)
    if not sub:
        return []
    grades = _grades()
    out: List[Dict[str, str]] = []
    for field, t in _material_texts(part, material):
        named = substrates_in(t)
        if (named and sub not in named) or (not named and field != "material_grade"):
            continue
        for code in grades_in(t):
            if code not in {g["code"] for g in out}:
                out.append({"code": code, "name": str(grades[code].get("name") or code.lower()),
                            "as_printed": t})
    return out


def specification(part: Any, material: Any = None) -> Optional[Dict[str, Any]]:
    """What the drawing requires of this board beyond its family, or None when it requires
    nothing more (no grade and no décor with its texture): such a board is priced exactly as
    before.

    {"grades": [...], "decors": [{"decor", "texture", "as_printed"}], "substrate": "MDF" or
     None, "material": the family asked for, "key": a cache key for the whole of it}"""
    if not isinstance(part, dict):
        return None
    grades = board_grade(part, material)
    try:
        from product_reference import decor_textures
        decors = decor_textures(part)
    except Exception:                                            # noqa: BLE001
        decors = []
    if not grades and not decors:
        return None
    sub = _substrate_of(part, material)
    return {
        "grades": grades, "decors": decors, "substrate": sub,
        "material": str(material or "").replace("_", " ").strip().upper(),
        "key": ("spec:" + "+".join(g["code"] for g in grades) + "|"
                + "+".join(f"{d['decor']}/{d['texture']}" for d in decors) + "|" + (sub or "")),
    }


def judge_row(spec: Dict[str, Any], description: Any) -> Dict[str, Any]:
    """A catalogue row against the specification: {"grades": the required grades it states,
    "grade_ok", "decor": the drawn décor code it carries or None, "decor_ok" (the décor AND its
    texture), "row_texture", "substrate_ok" (it names no other board), "substrates"}."""
    desc = str(description or "")
    need = [g["code"] for g in spec.get("grades") or []]
    has = [c for c in grades_in(desc) if c in need]
    try:
        from product_reference import decor_on_row
        d = decor_on_row(desc, spec.get("decors") or [])
    except Exception:                                            # noqa: BLE001
        d = {"decor": None, "texture": False, "row_texture": None}
    named = substrates_in(desc)
    sub = spec.get("substrate")
    return {"grades": has, "grade_ok": len(has) == len(need),
            "decor": d.get("decor"), "decor_ok": bool(d.get("texture")),
            "row_texture": d.get("row_texture"),
            "substrate_ok": not (sub and named and sub not in named),
            "substrates": named}


def choose_rows(spec: Dict[str, Any], rows: Iterable[Dict[str, Any]], from_reference: bool
                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """(the rows that price the line, what of the specification they do not carry).

    A row naming another board is never used. A row carrying the drawn décor is used only
    when it carries it in its drawn texture: another texture is a near miss, not the product.
    Of the rows left, those meeting the most of the specification are used, the
    grade first (it is the board), then the décor (it is the face). ([], []) when no row can
    be used."""
    judged = [(r, judge_row(spec, r.get("description"))) for r in rows or ()]
    # A near miss never prices the line, from either probe: U999 PM is another product, not
    # a stand-in for U999 ST2 and not a plain member of the family either.
    usable = [(r, j) for r, j in judged if j["substrate_ok"]
              and not (j["decor"] and not j["decor_ok"])
              and (j["decor_ok"] or not (from_reference and spec.get("decors")))]
    if not usable:
        return [], []
    best = max((j["grade_ok"], j["decor_ok"]) for _r, j in usable)
    chosen = [(r, j) for r, j in usable if (j["grade_ok"], j["decor_ok"]) == best]
    missing: List[Dict[str, str]] = []
    if not best[0]:
        for g in spec.get("grades") or []:
            if not all(g["code"] in j["grades"] for _r, j in chosen):
                missing.append({"part": "grade", "code": g["code"],
                                "said": f"the {g['code']} ({g['name']}) grade"})
    if not best[1]:
        for d in spec.get("decors") or []:
            if not all(j["decor"] == d["decor"] for _r, j in chosen):
                missing.append({"part": "decor", "code": d["decor"],
                                "said": f"the {d['decor']} décor"})
            missing.append({"part": "texture", "code": d["texture"],
                            "said": f"the {d['texture']} texture"})
    return [r for r, _j in chosen], missing


def near_miss(spec: Dict[str, Any], description: Any, thickness_mm: Optional[float],
              row_thickness_mm: Optional[float]) -> Optional[str]:
    """What a row carrying the drawn décor code lacks, in a buyer's words ("U999 in PM, not
    ST2; not MR; 19 mm"), or None when it carries no drawn décor or lacks nothing."""
    j = judge_row(spec, description)
    if not j["decor"]:
        return None
    bits: List[str] = []
    want = next((d["texture"] for d in spec.get("decors") or [] if d["decor"] == j["decor"]), "")
    if not j["decor_ok"]:
        bits.append(f"{j['decor']} in {j['row_texture']}, not {want}" if j["row_texture"]
                    else f"{j['decor']} with no texture stated, not {want}")
    for g in spec.get("grades") or []:
        if g["code"] not in j["grades"]:
            bits.append(f"not {g['code']}")
    if not j["substrate_ok"]:
        bits.append(f"{'/'.join(j['substrates'])}, not {spec.get('substrate')}")
    try:
        if thickness_mm and row_thickness_mm and \
                abs(float(row_thickness_mm) - float(thickness_mm)) > 0.05:
            bits.append(f"{float(row_thickness_mm):g} mm")
    except (TypeError, ValueError):
        pass
    return "; ".join(bits) or None


def specified_board(spec: Dict[str, Any], thickness_mm: Optional[float]) -> str:
    """The board as the drawing specifies it, in its own words: "18 mm MRMDF, EGGER: U999 ST2"."""
    grades = spec.get("grades") or []
    mat = _GAUGE.sub("", next((g["as_printed"] for g in grades), "")).strip(" ,;-")
    if not mat:
        mat = " ".join([g["code"] for g in grades] + [spec.get("material") or ""]).strip()
    mat = mat or "board"
    decor = ", ".join(dict.fromkeys(d["as_printed"] for d in spec.get("decors") or []))
    try:
        t = f"{float(thickness_mm):g} mm " if thickness_mm else ""
    except (TypeError, ValueError):
        t = ""
    return f"{t}{mat}" + (f", {decor}" if decor else "")


def said(missing: Iterable[Dict[str, str]]) -> str:
    """'the MR (moisture resistant) grade, the U999 décor and the ST2 texture'."""
    parts = [m["said"] for m in missing or ()]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
