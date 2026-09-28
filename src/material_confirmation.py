"""The estimator confirms what each part is made of, before the run — never a price.

"PDF/PNG-only jobs often state materials the engine cannot resolve or that estimating wants
costed differently." 12645's detail sheets all say PLAIN CARBON STEEL; Dave Wright asked for it
to be costed as standard mild steel, and the first answer was a line in the material lexicon
(D-309). A reviewer asked for a controlled, per-job confirmation instead — a person answering
for this job, on the record, rather than a rule nobody sees being applied.

THREE STEPS, AND ONLY THE FIRST NEEDS A PDF LIBRARY.

  read_pack(paths)      what the pack states, per part: material (as written and as the
                        engine's code), thickness, finish, and where each came from. Run out
                        of process with the engine's python (PyMuPDF), like printing:
                            python src/material_confirmation.py --read <files/folders> --json
  vocabulary(reading)   the controlled lists the portal's dropdowns offer, plus "unknown".
  build_answers(...)    the estimator's answers checked against the reading, and turned into
                        the job's answers file — `<drawing>_confirmed.json`, the file
                        estimator_confirmed already reads, at the ranks it already defines.

THE RULES build_answers ENFORCES, each one a way this could do harm:

  * NO PRICE, EVER. Any price, cost or rate key is refused by name, through
    estimator_confirmed's own _REFUSED_KEYS, so the two cannot drift apart.
  * A JOB DEFAULT FILLS ONLY WHAT THE DRAWINGS LEAVE UNSTATED. A mixed pack must never
    inherit one "main material" everywhere: where a sheet states a material, a thickness or a
    finish, the default does not touch it. Only a per-part answer can.
  * OVERRIDING A DRAWING NEEDS A REASON. A per-part answer that differs from what the sheet
    or its DXF states is refused without a typed reason; with one, it is written as a
    correction (estimator_confirmed "corrected", rank 100) carrying that reason.
  * "unknown" WRITES NOTHING. It is an answer — the estimator looked and cannot say — and it
    leaves the engine's own reading, or its question, in place.
  * EVERY LINE NAMES WHO SAID IT. No answers file without a person's name on it.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# ── the controlled lists ──────────────────────────────────────────────────────────────────
#
# A VOCABULARY, NOT A RULE. These are the choices a dropdown offers; nothing here decides
# what any part is made of. Materials come from the engine's own lexicon, so a choice is
# always a code the engine prices by. Finishes are the words the title blocks and the powder
# and plating rules already use.
FINISHES = ("POWDER COATED", "RAW", "PLATED", "ZINC PLATED", "GALVANISED", "PAINTED",
            "BRUSHED", "POLISHED", "ANODISED")
# Sheet and plate gauges the shop stocks and draws to, in mm. Whatever the pack itself states
# is added to the list, so a stated 9.5 mm bar is always a choice.
THICKNESSES_MM = (0.5, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
                  12.0, 15.0, 18.0, 20.0, 25.0)
UNKNOWN = "unknown"

# Who wrote the file, so a later run can tell the portal's file from one a person wrote by
# hand — and remove only its own when a run carries no confirmation.
WRITTEN_BY = "portal material confirmation"

_FIELDS = ("material", "thickness_mm", "finish")
# A render has no text layer and no title block to read, so nothing here can say what an image
# states. Named in `unread` rather than silently skipped, so a PNG-only pack shows the estimator
# that only the job default can apply to it.
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def _lexicon() -> Dict[str, str]:
    try:
        from json_normaliser import MATERIAL_NORMALISATION
        return dict(MATERIAL_NORMALISATION)
    except Exception:                                                # noqa: BLE001
        return {}


def material_codes() -> List[str]:
    """The engine's material codes a person may choose — never BOUGHT_IN, which is a
    make-or-buy ruling, not a material."""
    return sorted({v for v in _lexicon().values() if v and v != "BOUGHT_IN"})


def material_label(code: str) -> str:
    return str(code or "").replace("_", " ").title().replace("Mdf", "MDF").replace(
        "Mfc", "MFC").replace("Hdpe", "HDPE").replace("Hips", "HIPS").replace(
        "Spcc", "SPCC").replace("Mfmdf", "MFMDF")


def normalise_material(text: Any) -> Optional[str]:
    try:
        from json_normaliser import normalise_material as _nm
        return _nm(text)
    except Exception:                                                # noqa: BLE001
        return None


def _refused_keys() -> Tuple[str, ...]:
    try:
        from estimator_confirmed import _REFUSED_KEYS
        return tuple(_REFUSED_KEYS)
    except Exception:                                                # noqa: BLE001
        return ("price", "cost", "rate", "gbp", "price_gbp", "cost_gbp", "unit_price",
                "material_cost", "labour_cost")


# ── reading the pack ──────────────────────────────────────────────────────────────────────
#
# THE DXF FILE NAME IS THE SHOP'S OWN LABEL. SDI exports each flat as
# "<part>-<thickness>MM <material>_REV<x>.DXF" — 12645-01-01M-4MM MS_REVA.DXF — which is the
# thickness the laser is set to and the stock it is cut from.
_DXF_NAME = re.compile(r"^(?P<pn>.+?)-(?P<t>\d+(?:\.\d+)?)\s*MM(?:[\s_\-]+(?P<mat>[A-Z]{2,}))?",
                       re.IGNORECASE)
# The SDI title block reads its three boxes in order and the text layer runs them together:
# "MATERIAL: COLOUR: SURFACE FINISH: PLAIN CARBON STEEL POWDER COATED WEIGHT: 98.6kg".
_TITLE_BLOCK = re.compile(r"MATERIAL:\s*COLOUR:\s*SURFACE FINISH:\s*(?P<blob>.+?)\s*WEIGHT:",
                          re.IGNORECASE | re.DOTALL)
# The sheet's number sits before its revision letter and date: "12645-01-01M A 22/09/2026".
_NUMBER_BEFORE_REV = re.compile(
    r"(?P<pn>\d{3,}[0-9A-Z]*(?:-[0-9A-Z]+)+)\s+[A-Z]{1,2}\s+"
    r"(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}/\d{1,2}/\d{1,2})")
_REFERS_ELSEWHERE = re.compile(r"SEE\s+(?:ASSEMBLY|GA|DRAWING)", re.IGNORECASE)


def _split_title_blob(blob: str) -> Tuple[str, str]:
    """(material as written, finish) out of the run-together title-block boxes."""
    text = " ".join(str(blob or "").split()).upper()
    finish = ""
    for f in sorted(FINISHES, key=len, reverse=True):
        if f in text:
            finish = finish or f
            text = text.replace(f, " ")
    material = " ".join(text.split())
    return material, finish


def _files_in(paths: Iterable[Any]) -> List[Path]:
    out: List[Path] = []
    for raw in paths or []:
        p = Path(str(raw))
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file():
                    out.append(child)
                elif child.is_dir():
                    out.extend(g for g in sorted(child.iterdir()) if g.is_file())
        elif p.is_file():
            out.append(p)
    return out


def read_dxf_name(name: str) -> Optional[Dict[str, Any]]:
    """What a DXF's own file name states, or None."""
    stem = Path(str(name)).stem
    m = _DXF_NAME.match(stem)
    if not m:
        return None
    mat_abbr = (m.group("mat") or "").upper()
    if mat_abbr.startswith("REV"):
        mat_abbr = ""
    return {"part": m.group("pn").strip().upper(), "thickness_mm": float(m.group("t")),
            "material_text": mat_abbr, "material": normalise_material(mat_abbr) if mat_abbr
            else None, "source": f"{Path(str(name)).name} (DXF file name)"}


def read_pdf_pages(path: Path) -> List[Dict[str, Any]]:
    """What each sheet's title block states. Needs PyMuPDF: run with the engine's python."""
    try:
        import pymupdf as fitz                                       # type: ignore
    except Exception:                                                # noqa: BLE001
        import fitz                                                  # type: ignore
    out: List[Dict[str, Any]] = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc):
            text = " ".join(page.get_text().split())
            tb = _TITLE_BLOCK.search(text)
            num = _NUMBER_BEFORE_REV.search(text)
            if not tb or not num:
                continue
            blob = tb.group("blob")
            if _REFERS_ELSEWHERE.search(blob):
                continue                          # "SEE ASSEMBLY DRAWING": states nothing
            material_text, finish = _split_title_blob(blob)
            out.append({"part": num.group("pn").upper(), "material_text": material_text,
                        "material": normalise_material(material_text) if material_text
                        else None, "finish": finish,
                        "source": f"{path.name} p{i + 1} title block"})
    return out


def read_pack(paths: Iterable[Any]) -> Dict[str, Any]:
    """Per part, what the pack states — and the questions it raises for the estimator."""
    parts: Dict[str, Dict[str, Any]] = {}

    def _slot(pn: str) -> Dict[str, Any]:
        return parts.setdefault(pn, {"part": pn, "stated": {}, "sources": {}})

    unread: List[str] = []
    for f in _files_in(paths):
        suffix = f.suffix.lower()
        if suffix == ".dxf":
            d = read_dxf_name(f.name)
            if not d:
                continue
            s = _slot(d["part"])
            s["stated"].setdefault("thickness_mm", d["thickness_mm"])
            s["sources"].setdefault("thickness_mm", d["source"])
            if d["material"]:
                s["stated"].setdefault("material", d["material"])
                s["stated"].setdefault("material_text", d["material_text"])
                s["sources"].setdefault("material", d["source"])
        elif suffix in _IMAGE_SUFFIXES:
            unread.append(f"{f.name} (an image has no title block to read — only the job "
                          f"default can apply to its parts)")
        elif suffix == ".pdf":
            try:
                pages = read_pdf_pages(f)
            except Exception as exc:                                 # noqa: BLE001
                unread.append(f"{f.name} ({type(exc).__name__})")
                continue
            for pg in pages:
                s = _slot(pg["part"])
                # THE SHEET'S WORDS ARE KEPT EVEN WHERE THE DXF NAME ALREADY GAVE A CODE:
                # "PLAIN CARBON STEEL" is the question, "MS" is only the shop's shorthand.
                if pg["material_text"]:
                    s["stated"]["material_text"] = pg["material_text"]
                    s["stated"]["material"] = pg["material"] or s["stated"].get("material")
                    s["sources"]["material"] = pg["source"]
                if pg["finish"]:
                    s["stated"].setdefault("finish", pg["finish"])
                    s["sources"].setdefault("finish", pg["source"])
    return {"parts": [parts[k] for k in sorted(parts)], "questions": questions(parts),
            "unread": unread}


def questions(parts: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One question per distinct material wording the engine reads as something it is not
    called — "PLAIN CARBON STEEL" costed as MILD STEEL — and per wording it cannot read.

    Grouped by the words on the drawing, so forty sheets saying the same thing are one
    question, answered once, applying only to the parts that state those words."""
    groups: Dict[str, Dict[str, Any]] = {}
    for p in parts.values():
        st = p.get("stated") or {}
        text = str(st.get("material_text") or "").strip()
        if not text:
            continue
        code = st.get("material")
        plain = material_label(code).upper() if code else ""
        if code and (text.upper() == plain or text.upper() == str(code).upper()
                     or len(text) <= 3):
            continue                                 # the drawing says what the engine costs
        g = groups.setdefault(text, {"stated": text, "engine_reads_as": code,
                                     "parts": []})
        g["parts"].append(p["part"])
    out = []
    for text, g in sorted(groups.items()):
        if g["engine_reads_as"]:
            ask = (f"The drawings say '{text}'. Cost it as "
                   f"{material_label(g['engine_reads_as'])}? The exact grade stays open.")
        else:
            ask = f"The drawings say '{text}', which the engine does not recognise. What is it?"
        out.append(dict(g, key=f"material:{text}", ask=ask))
    return out


def vocabulary(reading: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The dropdowns. Every list carries "unknown" first."""
    stated_t = sorted({float(p["stated"]["thickness_mm"])
                       for p in (reading or {}).get("parts") or []
                       if (p.get("stated") or {}).get("thickness_mm") is not None})
    thick = sorted(set(THICKNESSES_MM) | set(stated_t))
    return {"material": [UNKNOWN] + material_codes(),
            "material_labels": {c: material_label(c) for c in material_codes()},
            "thickness_mm": [UNKNOWN] + thick,
            "finish": [UNKNOWN] + list(FINISHES)}


# ── checking the answers and writing the file ─────────────────────────────────────────────

def _given(value: Any) -> bool:
    return value is not None and str(value).strip() not in ("", UNKNOWN)


def _same(field: str, a: Any, b: Any) -> bool:
    if field == "thickness_mm":
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return False
    return str(a or "").strip().upper() == str(b or "").strip().upper()


def _find_refused(obj: Any, where: str, refused: Tuple[str, ...], out: List[str]) -> None:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            kl = str(k).strip().lower()
            if kl in refused or any(w in kl for w in ("price", "cost", "gbp")):
                out.append(f"{where}{k}: REFUSED — this step records what a part is made of, "
                           f"never what it costs. Price it on the sheet, where it shows as "
                           f"your decision")
            else:
                _find_refused(v, f"{where}{k}.", refused, out)


def build_answers(reading: Mapping[str, Any], answers: Mapping[str, Any],
                  drawing_number: str, today: Optional[str] = None
                  ) -> Tuple[Dict[str, Any], List[str]]:
    """(answers file, errors). Any error means nothing is written.

    answers = {
      "confirmed_by": "Dave Wright",
      "default":      {"material": code|unknown, "thickness_mm": n|unknown, "finish": f|unknown},
      "by_stated_material": {"PLAIN CARBON STEEL": "MILD_STEEL"},    # a question, answered
      "parts": {"12645-01-22M": {"material": ..., "thickness_mm": ..., "finish": ...,
                                  "reason": "..."}},
    }
    """
    errors: List[str] = []
    _find_refused(answers, "", _refused_keys(), errors)
    who = str(answers.get("confirmed_by") or "").strip()
    if not who:
        errors.append("confirmed_by: say who is confirming — a confirmation with no name on "
                      "it cannot be trusted or asked about")
    vocab = vocabulary(reading)
    allowed = {"material": set(vocab["material"]), "finish": set(vocab["finish"]),
               "thickness_mm": {str(x) for x in vocab["thickness_mm"]}}

    def _check(field: str, value: Any, where: str) -> Any:
        if not _given(value):
            return None
        if field == "thickness_mm":
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors.append(f"{where}thickness_mm {value!r} is not a thickness")
                return None
            if str(num) not in allowed["thickness_mm"]:
                errors.append(f"{where}thickness_mm {num:g} is not on the list")
                return None
            return num
        v = str(value).strip().upper()
        if v not in allowed[field]:
            errors.append(f"{where}{field} {value!r} is not on the list")
            return None
        return v

    default = {f: _check(f, (answers.get("default") or {}).get(f), "default.") for f in _FIELDS}
    by_text = {str(k).strip().upper(): _check("material", v, f"by_stated_material['{k}'].")
               for k, v in (answers.get("by_stated_material") or {}).items()}
    part_ans = answers.get("parts") or {}
    if not isinstance(part_ans, Mapping):
        errors.append("parts must be an object of {part: answers}")
        part_ans = {}

    read_parts = {str(p["part"]).upper(): p for p in (reading.get("parts") or [])}
    # A PART THE PACK DOES NOT SHOW IS NOT A PART THIS CHECK CAN VOUCH FOR. Treating an unread
    # code as "the drawing states nothing" let any code through as a fill, unchecked against
    # the drawings the run is about to cost — the one safeguard this step exists to give.
    for _k in part_ans:
        if str(_k).strip().upper() not in read_parts:
            errors.append(f"{_k}: not a part read from this pack — only parts the drawings "
                          f"show can be confirmed here; use the job default for the rest")
    names = sorted(read_parts)
    out_parts: Dict[str, Dict[str, Any]] = {}
    for pn in names:
        rp = read_parts.get(pn) or {"stated": {}, "sources": {}}
        stated, sources = rp.get("stated") or {}, rp.get("sources") or {}
        pa = next((v for k, v in part_ans.items() if str(k).strip().upper() == pn), {}) or {}
        reason = str(pa.get("reason") or "").strip()
        entry: Dict[str, Any] = {}
        conflicts, fills, agreed, notes = [], [], [], []
        for f in _FIELDS:
            own = _check(f, pa.get(f), f"{pn}.")
            val, how = None, ""
            if own is not None:
                val, how = own, "part"
            elif f == "material" and stated.get("material_text") \
                    and by_text.get(str(stated["material_text"]).upper()):
                val, how = by_text[str(stated["material_text"]).upper()], "question"
            elif stated.get(f) is None and default.get(f) is not None:
                val, how = default[f], "default"
            if val is None:
                continue
            entry[f] = val
            if stated.get(f) is None:
                fills.append(f)
                notes.append(f"{f} {val} from the job {'default' if how == 'default' else 'answer'}"
                             f" — the drawings state none")
            elif _same(f, val, stated[f]):
                agreed.append(f)
                _as = stated.get("material_text") if f == "material" else stated[f]
                notes.append(f"{f} {val} confirmed against {sources.get(f, 'the drawing')}"
                             + (f" (stated '{_as}')" if f == "material" and _as else ""))
            else:
                conflicts.append(f)
                notes.append(f"{f} {val} in place of {stated[f]} stated on "
                             f"{sources.get(f, 'the drawing')}")
        if not entry:
            continue
        if conflicts and not reason:
            errors.append(f"{pn}: {', '.join(conflicts)} "
                          f"{'differs' if len(conflicts) == 1 else 'differ'} from the drawing "
                          f"({'; '.join(n for n in notes if 'in place of' in n)}) — give a "
                          f"reason to override it")
            continue
        basis = "corrected" if conflicts else ("inferred" if fills else "read")
        text = "; ".join(notes) + f" — {who} in the portal"
        if reason:
            text += f". Reason: {reason}"
        entry["basis"] = basis
        entry["note" if basis != "read" else "read_from"] = text
        out_parts[pn] = entry

    if errors:
        return {}, errors
    return {
        "drawing_number": str(drawing_number or "").strip(),
        "written_by": WRITTEN_BY,
        "confirmed_by": who,
        "confirmed_on": today or date.today().isoformat(),
        "note": ("Materials, thicknesses and finishes confirmed before the run in the "
                 "estimating portal. A job default fills only what the drawings leave "
                 "unstated; an override of a drawing carries its reason."),
        "parts": out_parts,
    }, []


def answers_file_name(drawing: str) -> str:
    return f"{drawing}_confirmed.json"


def write_answers(folder: Any, drawing: str, data: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Write the portal's answers file into the staged job folder, or — with no answers —
    remove one the portal wrote on an earlier run, so a stale confirmation never governs a
    later job. A file a person wrote by hand is never touched."""
    target = Path(str(folder)) / answers_file_name(drawing)
    if data and data.get("parts"):
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(target)
    if target.is_file():
        try:
            prior = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = {}
        if isinstance(prior, Mapping) and prior.get("written_by") == WRITTEN_BY:
            target.unlink()
    return None


def _main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--read":
        paths = [a for a in argv[1:] if a != "--json"]
        reading = read_pack(paths)
        print(json.dumps({"reading": reading, "vocabulary": vocabulary(reading)},
                         ensure_ascii=False))
        return 0
    print("usage: material_confirmation.py --read <files or folders...> --json",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
