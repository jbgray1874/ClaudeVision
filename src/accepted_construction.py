"""A member schedule a person checked against the drawing — priced in place of the model's read.

D-534: "verify the member schedule against the PDF, then replay that accepted construction
through pricing — not repeatedly ask Grok for another fresh design." The answers file corrects
a size, a count or a material on a line the read made; it cannot add the line the read missed,
remove one it invented, or change what a line is cut from. A schedule a person has checked is
a better read than the model's, so it is written in the read's own shape and every rule
downstream prices it exactly as it would have priced the model's answer.

D-535: the first way to file one was to hand-edit JSON in Notepad and copy it onto the share
with PowerShell — and a re-run's staging then deleted it, because it was not on the list of the
job's own files. So the schedule is made where every other estimator input is made: the
estimating portal's Member schedule panel loads the last read (or the schedule already on file)
into a table, the estimator corrects it against the drawing, ticks that they checked it and
names themselves, and the Run files it beside the pack. Staging keeps it across a re-stage, and
the next LLM run prices it without asking the model. Setting it aside renames it, so the model
reads the drawing again and the schedule is still there to start from.

PURE PYTHON — json, re and pathlib only. The portal's server checks a schedule before anything
is staged and does not carry the engine; concept_scan uses the same rules, so a schedule the
page accepts is a schedule the run accepts.

THE RULES, each one a way this could do harm:

  * A PERSON ACCEPTS IT, BY NAME. No name, or a name that still says DRAFT, is refused.
  * NO PRICE, EVER. A construction says what is made and bought; a money key anywhere in it
    is refused by name — a figure there would reach the sheet wearing the drawing's authority.
  * EVERY LINE IS PRICEABLE. A line with no name, kind or positive count is refused; a made
    section with no section size or cut length, a sheet part with no blank, an operation the
    engine cannot price — each is refused on its line, so a schedule never quietly costs less
    than it says.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SUFFIX = "_construction.json"
FILENAME = "construction.json"
SET_ASIDE_SUFFIX = "_construction_set_aside.json"
SET_ASIDE_FILENAME = "construction_set_aside.json"
WRITTEN_BY = "portal member schedule"

KINDS = ("fabricated", "bought_in", "graphic")
SECTION_FORMS = ("box_section", "tube", "oval_tube", "angle", "channel", "flat_bar", "round_bar")
FORMS = ("sheet", "board") + SECTION_FORMS + ("wire", "mesh")
# The work a line may name: concept_scan.SIGHTABLE_OPERATIONS, the words the engine can mint
# into a priced department (a fixture compares the two so they cannot drift).
OPERATIONS = ("saw", "cnc_routing", "edge_banding", "laminating", "glue", "wet_spray",
              "bench_work", "hole_machining", "assembly", "laser_cutting", "folding", "welding",
              "powder_coating", "deburring", "plating", "polishing", "rolling")
MONEY_KEYS = ("price", "cost", "rate", "gbp", "£")
# What the engine takes from the file as the read; everything else is the file's own record.
ANSWER_KEYS = ("product", "unit_operations", "parts", "not_visible", "sheet_facts")
# Fields the table edits. Anything else a line carried (banded_edges, flange_mm, seen) rides
# through untouched in "_orig", so correcting a count never loses what the read said.
_OWNED = {"name", "kind", "quantity", "material_guess", "sighted_material", "stock",
          "assumed_blank_mm", "operations", "folds", "cutouts", "why_size"}


def _num(value: Any) -> float:
    try:
        out = float(str(value).strip().lower().replace("mm", "").replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return out if out > 0 else 0.0


def _g(v: float) -> Any:
    return int(v) if float(v).is_integer() else round(float(v), 3)


def _money(obj: Any, where: str = "") -> List[str]:
    found: List[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if any(m in str(k).lower() for m in MONEY_KEYS):
                found.append(f"{where}{k}")
            found.extend(_money(v, f"{where}{k}."))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found.extend(_money(v, f"{where}{i}."))
    return found


def _strip_money(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: _strip_money(v) for k, v in obj.items()
                if not any(m in str(k).lower() for m in MONEY_KEYS)}
    if isinstance(obj, list):
        return [_strip_money(v) for v in obj]
    return obj


# ── the file, as the engine reads it ───────────────────────────────────────────────────

def problems_in(data: Any) -> List[str]:
    """Why this schedule would be refused, by name — [] when it would be priced."""
    if not isinstance(data, Mapping) or not isinstance(data.get("parts"), list) \
            or not data["parts"]:
        return ["it has no parts list"]
    problems: List[str] = []
    _m = _money(data)
    if _m:
        problems.append(f"it carries money ({', '.join(_m[:4])}) — a construction states what "
                        f"is made and bought, never a price; enter prices on the sheet")
    who = str(data.get("accepted_by") or "").strip()
    if not who or who.upper().startswith("DRAFT"):
        problems.append("nobody has accepted it — set \"accepted_by\" to the person who checked "
                        "it against the drawing")
    for i, p in enumerate(data["parts"], start=1):
        if not isinstance(p, Mapping):
            problems.append(f"line {i} is not a part")
            continue
        if not str(p.get("name") or "").strip() or not str(p.get("kind") or "").strip():
            problems.append(f"line {i} has no name or no kind")
        if not _num(p.get("quantity")) > 0:
            problems.append(f"line {i} ({p.get('name')}) has no positive quantity")
    return problems


def load(path: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """(answer, problems) from one schedule file — the answer None when it is refused."""
    try:
        # utf-8-sig: Windows Notepad and PowerShell 5's Set-Content write a byte-order mark,
        # and a schedule refused for an invisible character is a wasted run.
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception as exc:                                         # noqa: BLE001
        return None, [f"could not be read ({type(exc).__name__}: {exc})"]
    problems = problems_in(data)
    if problems:
        return None, problems
    answer = {k: data[k] for k in ANSWER_KEYS if k in data}
    answer["accepted_construction"] = {
        "file": str(path), "accepted_by": str(data.get("accepted_by") or "").strip(),
        "accepted_on": str(data.get("accepted_on") or ""),
        "basis": str(data.get("basis") or ""),
        "excluded": [str(x) for x in (data.get("excluded") or [])]}
    return answer, []


def _names(folder: Path, job: str) -> List[str]:
    out = ([f"{job}{SUFFIX}"] if job else []) + [f"{folder.name}{SUFFIX}", FILENAME]
    return list(dict.fromkeys(out))


def find(folders: Sequence[Any], job: str = "") -> Tuple[Optional[Dict[str, Any]], str, List[str]]:
    """(answer, file, problems) from the first schedule in the run's folders.

    "<job>_construction.json", then "<folder>_construction.json", then "construction.json".
    A file that is found and refused returns (None, file, problems) — said, never ignored."""
    seen = set()
    for folder in folders:
        if not folder or str(folder) in seen:
            continue
        seen.add(str(folder))
        p = Path(str(folder))
        for name in _names(p, job):
            f = p / name
            if f.is_file():
                ans, problems = load(f)
                return ans, str(f), problems
    return None, "", []


# ── the table the portal edits ─────────────────────────────────────────────────────────

def _form_of(p: Mapping[str, Any]) -> str:
    st = p.get("stock") if isinstance(p.get("stock"), Mapping) else {}
    form = str(st.get("form") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if form == "plate":
        form = "sheet"
    if form in FORMS:
        return form
    return "sheet" if str(p.get("kind") or "").strip().lower() == "fabricated" else ""


def _size_text(values: Any) -> str:
    vals = [v for v in (_num(x) for x in (values if isinstance(values, (list, tuple))
                                           else [values])) if v]
    if len(vals) == 2 and vals[0] == vals[1]:
        vals = vals[:1]
    return " x ".join(f"{_g(v)}" for v in vals)


def rows_from_parts(parts: Any) -> List[Dict[str, Any]]:
    """The read's (or a schedule's) lines as the table's rows — one flat row a line."""
    rows: List[Dict[str, Any]] = []
    for p in parts or []:
        if not isinstance(p, Mapping) or not str(p.get("name") or "").strip():
            continue
        st = p.get("stock") if isinstance(p.get("stock"), Mapping) else {}
        bl = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
        form = _form_of(p)
        section, wall = "", ""
        if form in SECTION_FORMS:
            section = _size_text(st.get("section_mm"))
            wall = _g(_num(st.get("wall_mm"))) if _num(st.get("wall_mm")) else ""
        elif form == "wire":
            section = _size_text(st.get("wire_mm"))
        elif form == "mesh":
            section = _size_text(st.get("aperture_mm"))
            wall = _g(_num(st.get("wire_mm"))) if _num(st.get("wire_mm")) else ""
        length = _num(st.get("length_mm")) or _num(bl.get("length"))
        cuts = [c for c in (p.get("cutouts") or []) if isinstance(c, Mapping)]
        holes = [c for c in cuts if str(c.get("what") or "").lower().startswith("hole")]
        # Slots and openings the table has no column for ride through untouched.
        orig = _strip_money({k: v for k, v in p.items() if k not in _OWNED})
        if len(holes) < len(cuts):
            orig["cutouts"] = [dict(c) for c in cuts if c not in holes]
        sheet_like = form in ("sheet", "board", "mesh") or form == ""
        rows.append({
            "name": str(p.get("name") or "").strip(),
            "kind": str(p.get("kind") or "").strip().lower().replace("-", "_"),
            "quantity": _g(_num(p.get("quantity"))) if _num(p.get("quantity")) else "",
            "material": str(p.get("material_guess") or "").strip(),
            "sighted": str(p.get("sighted_material") or "").strip(),
            "form": form, "section": section, "wall": wall,
            "length": _g(length) if length else "",
            "width": _g(_num(bl.get("width"))) if sheet_like and _num(bl.get("width")) else "",
            "thickness": (_g(_num(bl.get("thickness")))
                          if sheet_like and _num(bl.get("thickness")) else ""),
            "holes": int(sum(_num(c.get("count")) for c in holes)) or "",
            "hole_mm": (_g(_num(holes[0].get("length_mm")) or _num(holes[0].get("width_mm")))
                        if holes else ""),
            "folds": _g(_num(p.get("folds"))) if _num(p.get("folds")) else "",
            "operations": [str(o) for o in (p.get("operations") or []) if str(o).strip()],
            "note": str(p.get("why_size") or "").strip(),
            "_orig": orig,
        })
    return rows


def _a(form: str) -> str:
    words = form.replace("_", " ")
    return ("an " if words[:1] in "aeiou" else "a ") + words


def _section_values(text: Any) -> List[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(text or ""))][:3]


def _ops(value: Any) -> List[str]:
    if isinstance(value, str):
        value = re.split(r"[,;/\n]+", value)
    return [re.sub(r"[^a-z0-9]+", "_", str(o).strip().lower()).strip("_")
            for o in (value or []) if str(o).strip()]


def parts_from_rows(rows: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The table's rows back in the read's own shape, or why a row cannot be priced."""
    parts: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, r in enumerate(rows or [], start=1):
        if not isinstance(r, Mapping):
            errors.append(f"line {i}: not a line")
            continue
        name = " ".join(str(r.get("name") or "").split())
        label = f"line {i} ({name or 'no name'})"
        kind = str(r.get("kind") or "").strip().lower().replace("-", "_")
        qty = _num(r.get("quantity"))
        if not name:
            errors.append(f"line {i}: give the line a name")
        if kind not in KINDS:
            errors.append(f"{label}: kind must be made (fabricated), bought in or graphic")
        if not qty:
            errors.append(f"{label}: how many per unit?")
        ops = _ops(r.get("operations"))
        bad = [o for o in ops if o not in OPERATIONS]
        if bad:
            errors.append(f"{label}: {', '.join(bad)} is not work the engine can price — "
                          f"choose from {', '.join(OPERATIONS)}")
        orig = r.get("_orig") if isinstance(r.get("_orig"), Mapping) else {}
        part: Dict[str, Any] = {k: v for k, v in dict(orig).items() if k not in _OWNED}
        part.update({"name": name, "kind": kind, "quantity": _g(qty) if qty else 0,
                     "material_guess": " ".join(str(r.get("material") or "").split()),
                     "sighted_material": " ".join(str(r.get("sighted") or "").split()),
                     "operations": [o for o in ops if o in OPERATIONS]})
        if _num(r.get("folds")):
            part["folds"] = _g(_num(r.get("folds")))
        note = " ".join(str(r.get("note") or "").split())
        if note:
            part["why_size"] = note
        L, W, T = _num(r.get("length")), _num(r.get("width")), _num(r.get("thickness"))
        sec, wall = _section_values(r.get("section")), _num(r.get("wall"))
        form = str(r.get("form") or "").strip().lower() or ("sheet" if kind == "fabricated" else "")
        if kind == "fabricated":
            if form not in FORMS:
                errors.append(f"{label}: '{form}' is not a stock form — choose one of "
                              f"{', '.join(FORMS)}")
            elif form in SECTION_FORMS:
                if not sec:
                    errors.append(f"{label}: {_a(form)} needs its section size, e.g. 40 x 20")
                if not L:
                    errors.append(f"{label}: {_a(form)} needs its cut length")
                if sec and len(sec) == 3 and not wall:
                    wall = sec[2]
                sec = sec[:2]
                if sec and L:
                    part["stock"] = {"form": form, "section_mm": [_g(v) for v in sec],
                                     "wall_mm": _g(wall) if wall else 0, "length_mm": _g(L)}
                    part["assumed_blank_mm"] = {"length": _g(L), "width": _g(sec[0]),
                                                "thickness": _g(sec[-1])}
            elif form == "wire":
                d = (sec[0] if sec else 0.0) or wall
                if not d or not L:
                    errors.append(f"{label}: a wire needs its diameter (section) and its "
                                  f"developed length")
                else:
                    part["stock"] = {"form": "wire", "wire_mm": _g(d), "length_mm": _g(L)}
                    part["assumed_blank_mm"] = {"length": _g(L), "width": _g(d),
                                                "thickness": _g(d)}
            elif form == "mesh":
                if not L or not W:
                    errors.append(f"{label}: a mesh panel needs its length and width")
                else:
                    part["stock"] = {"form": "mesh", "aperture_mm": [_g(v) for v in sec[:2]],
                                     "wire_mm": _g(wall) if wall else 0, "length_mm": 0}
                    part["assumed_blank_mm"] = {"length": _g(L), "width": _g(W), "thickness": 0}
            else:
                if not (L and W and T):
                    errors.append(f"{label}: {_a(form)} part needs its blank length, width "
                                  f"and thickness")
                else:
                    part["stock"] = {"form": form}
                    part["assumed_blank_mm"] = {"length": _g(L), "width": _g(W),
                                                "thickness": _g(T)}
            holes, hole_mm = int(_num(r.get("holes"))), _num(r.get("hole_mm"))
            cuts = [c for c in (orig.get("cutouts") or [])
                    if isinstance(c, Mapping)
                    and not str(c.get("what") or "").lower().startswith("hole")]
            if holes and not hole_mm:
                errors.append(f"{label}: give the hole diameter for its {holes} hole(s)")
            elif holes:
                cuts.append({"what": "hole", "count": holes, "length_mm": _g(hole_mm),
                             "width_mm": _g(hole_mm)})
            part["cutouts"] = cuts
        elif L or W:
            # A bought item or a graphic keeps a stated size (an ID plate 20 x 10; a print).
            part["assumed_blank_mm"] = {"length": _g(L), "width": _g(W), "thickness": _g(T)}
        parts.append(part)
    return parts, errors


def build_file(submitted: Mapping[str, Any], drawing: str,
               today: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
    """(the file, errors) from the portal's panel. Any error means nothing is written.

    submitted = {"accepted_by", "checked": true, "basis", "product": {...},
                 "unit_operations": [...], "parts": [table rows], "excluded": [...],
                 "not_visible": [...]}"""
    if not isinstance(submitted, Mapping):
        return {}, ["the member schedule must be an object"]
    errors: List[str] = []
    _m = _money({k: v for k, v in submitted.items() if k != "parts"}) + _money(
        [{k: v for k, v in (r or {}).items()} for r in (submitted.get("parts") or [])
         if isinstance(r, Mapping)])
    if _m:
        errors.append(f"it carries money ({', '.join(_m[:4])}) — a member schedule states what "
                      f"is made and bought, never a price; enter prices on the sheet")
    who = " ".join(str(submitted.get("accepted_by") or "").split())
    if not who or who.upper().startswith("DRAFT"):
        errors.append("say who checked this schedule against the drawing")
    if not submitted.get("checked"):
        errors.append("tick that every line was checked against the drawing")
    parts, perrs = parts_from_rows(submitted.get("parts"))
    errors.extend(perrs)
    if not parts:
        errors.append("the schedule has no lines")
    unit_ops = _ops(submitted.get("unit_operations"))
    bad = [o for o in unit_ops if o not in OPERATIONS]
    if bad:
        errors.append(f"unit work: {', '.join(bad)} is not work the engine can price")
    product = submitted.get("product") if isinstance(submitted.get("product"), Mapping) else {}
    ov = product.get("assumed_overall_mm") if isinstance(
        product.get("assumed_overall_mm"), Mapping) else {}
    prod: Dict[str, Any] = {"name": " ".join(str(product.get("name") or "").split()),
                            "assumed_overall_mm": {k: _g(_num(ov.get(k))) for k in
                                                   ("height", "width", "depth")}}
    if _num(product.get("stated_weight_kg")):
        prod["stated_weight_kg"] = _g(_num(product.get("stated_weight_kg")))
    lines = lambda v: [" ".join(str(x).split()) for x in (                      # noqa: E731
        v.splitlines() if isinstance(v, str) else (v or [])) if str(x).strip()]
    if errors:
        return {}, errors
    data = {
        "written_by": WRITTEN_BY,
        "drawing_number": str(drawing or "").strip(),
        "accepted_by": who,
        "accepted_on": today or date.today().isoformat(),
        "basis": (" ".join(str(submitted.get("basis") or "").split())
                  or "member schedule checked against the drawing in the estimating portal"),
        "product": prod,
        "unit_operations": [o for o in unit_ops if o in OPERATIONS],
        "parts": parts,
        "not_visible": lines(submitted.get("not_visible")),
        "excluded": lines(submitted.get("excluded")),
    }
    return data, problems_in(data)


def schedule_view(data: Mapping[str, Any], file: str = "") -> Dict[str, Any]:
    """A schedule file as the panel shows it: who, when, the rows, and any refusal."""
    product = data.get("product") if isinstance(data.get("product"), Mapping) else {}
    return {"file": file, "written_by": str(data.get("written_by") or ""),
            "accepted_by": str(data.get("accepted_by") or ""),
            "accepted_on": str(data.get("accepted_on") or ""),
            "basis": str(data.get("basis") or ""),
            "product": _strip_money(dict(product)),
            "unit_operations": [str(o) for o in (data.get("unit_operations") or [])],
            "not_visible": [str(x) for x in (data.get("not_visible") or [])],
            "excluded": [str(x) for x in (data.get("excluded") or [])],
            "rows": rows_from_parts(data.get("parts")),
            "problems": problems_in(data)}


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def on_file(folder: Any, drawing: str) -> Dict[str, Any]:
    """What the panel offers for a job: the schedule the next run would price, one set aside,
    and the last read's lines to start from. Reads only."""
    f = Path(str(folder))
    out: Dict[str, Any] = {"folder": str(f), "on_file": None, "set_aside": None,
                           "last_read": None}
    for name in _names(f, drawing):
        data = _read_json(f / name) if (f / name).is_file() else None
        if data is not None:
            out["on_file"] = schedule_view(data, str(f / name))
            break
    for name in ([f"{drawing}{SET_ASIDE_SUFFIX}"] if drawing else []) + [SET_ASIDE_FILENAME]:
        data = _read_json(f / name) if (f / name).is_file() else None
        if data is not None:
            out["set_aside"] = schedule_view(data, str(f / name))
            break
    safe = re.sub(r"[^\w\-. ]", "", str(drawing or "concept")).strip() or "concept"
    bill = _read_json(f / f"{safe}_concept_bill.json")
    if bill:
        read = bill.get("read") if isinstance(bill.get("read"), Mapping) else None
        if read and read.get("parts"):
            out["last_read"] = {"complete": True,
                                "source": str(read.get("source") or "model"),
                                "product": _strip_money(dict(read.get("product") or {})),
                                "unit_operations": list(read.get("unit_operations") or []),
                                "not_visible": list(read.get("not_visible") or []),
                                "rows": rows_from_parts(read.get("parts"))}
        elif bill.get("parts"):
            # A bill saved before D-535 kept a summary of each line — no stock form, section or
            # work. Offered as a start, and said to be one.
            rows = []
            for b in bill["parts"]:
                if not isinstance(b, Mapping) or not b.get("name"):
                    continue
                rows.append({"name": str(b["name"]), "kind": str(b.get("kind") or ""),
                             "quantity": _g(_num(b.get("quantity"))) if _num(b.get("quantity")) else "",
                             "material": str(b.get("material") or ""), "sighted": "",
                             "form": "sheet" if b.get("kind") == "fabricated" else "",
                             "section": "", "wall": "",
                             "length": _g(_num(b.get("length"))) if _num(b.get("length")) else "",
                             "width": _g(_num(b.get("width"))) if _num(b.get("width")) else "",
                             "thickness": (_g(_num(b.get("thickness")))
                                           if _num(b.get("thickness")) else ""),
                             "holes": "", "hole_mm": "",
                             "folds": _g(_num(b.get("folds"))) if _num(b.get("folds")) else "",
                             "operations": [], "note": str(b.get("why") or ""), "_orig": {}})
            out["last_read"] = {"complete": False, "source": "model", "product": {},
                                "unit_operations": [], "not_visible": [], "rows": rows}
    return out


def file_name(drawing: str) -> str:
    return f"{drawing}{SUFFIX}"


def write(folder: Any, drawing: str, data: Mapping[str, Any]) -> str:
    """File the accepted schedule beside the pack, replacing any set-aside copy's role."""
    target = Path(str(folder)) / file_name(drawing)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(target)


def set_aside(folder: Any, drawing: str) -> Optional[str]:
    """Rename the schedule the next run would price, so the model reads the drawing again and
    the schedule is still there to start from. Returns the new name, or None if none was on
    file."""
    f = Path(str(folder))
    for name in _names(f, drawing):
        src = f / name
        if src.is_file():
            dst = f / (name[:-len(".json")] + "_set_aside.json")
            src.replace(dst)
            return str(dst)
    return None


def vocabulary() -> Dict[str, Any]:
    return {"kinds": list(KINDS), "forms": list(FORMS), "section_forms": list(SECTION_FORMS),
            "operations": list(OPERATIONS)}
