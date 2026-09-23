"""Which drawing is the product: one resolver for the engine AND the portal.

James Gray, 23 Sep 2026: "we need to centre the job estimate around the drawing number
entered into the estimating portal." The engine takes the portal's Drawing Number as the
only root that ships (D-192). The 11650-02 run showed what that costs when the number is
the wrong one: the cabinet top was priced in full confidence and Tim's kit was set aside,
and nobody could see it until a forty-minute run had finished.

So the portal asks the same question BEFORE Run, with the same answer the engine will give:
this module is imported by route_compiler (which names the root) and by the service (which
checks the number against the files added). Two copies of "does this number name that
drawing" is how the page could approve a number the engine then refuses.

Pure: no config, no database, nothing but the text it is given — the service runs in a
different interpreter with a different `config`, and must be able to load this without it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from part_code_conventions import (looks_like_a_drawing_number,
                                       strip_assembly_role, ASSEMBLY_ROLE_TOKENS)
except Exception:                                                    # noqa: BLE001
    ASSEMBLY_ROLE_TOKENS = frozenset({"GA", "ASSY", "ASSEMBLY", "ARR", "ARRANGEMENT", "GEN"})

    def strip_assembly_role(identity: str) -> str:
        m = re.match(r"^(.*\S)[\s\-]+([A-Za-z]+)$", str(identity or "").strip())
        if m and m.group(2).upper() in ASSEMBLY_ROLE_TOKENS:
            return m.group(1)
        return str(identity or "").strip()

    def looks_like_a_drawing_number(text: str) -> bool:
        t = str(text or "").strip()
        return bool(re.search(r"\d", t)) and bool(re.search(r"[-_./]|\d{4,}", t))

_REV_TAIL = re.compile(r"[\s_\-]*REV(?:ISION)?[\s._()\-]*[A-Z0-9]{1,3}\]?\)?$", re.IGNORECASE)
_REV_IN_NAME = re.compile(r"REV(?:ISION)?[\s._()\[\-]*([A-Z]{1,2})\b")
_DRAWING_EXTENSIONS = (".pdf", ".dxf", ".dwg", ".sldasm", ".sldprt", ".slddrw", ".step",
                       ".stp", ".png", ".jpg", ".jpeg")


def _key(text: Any) -> str:
    t = str(text or "").strip().upper()
    t = _REV_TAIL.sub("", t)
    t = strip_assembly_role(t.strip())
    return re.sub(r"[\s\-_]+", "", t)


def names_the_product(declared: Any, identity: Any) -> bool:
    """Does the Drawing Number the estimator typed name this drawing?

    One sheet, several spellings: "11650-06", "11650-06-GA", "11650-06 GA Rev B" all name
    the kit's general arrangement. A trailing revision and ONE sheet-role token are set
    aside on both sides and the rest must match exactly, ignoring spaces and dashes. Nothing
    looser: "11650-06" must never name 11650-06-SA01, which is a part OF the product."""
    d, i = _key(declared), _key(identity)
    return bool(d) and d == i


def drawing_of_file(name: Any) -> Dict[str, Any]:
    """What a drawing file's own name says: number, title, revision, whether it is an
    assembly. Estimating names drawings "<number> <what it is>_rev<x>" — a convention, not
    prose — so the number is the first token and must LOOK like a drawing number."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    low = base.lower()
    ext = next((e for e in _DRAWING_EXTENSIONS if low.endswith(e)), "")
    stem = base[: len(base) - len(ext)] if ext else base
    parts = re.split(r"[\s_]+", stem.strip(), maxsplit=1)
    number = parts[0].strip() if parts else ""
    if not looks_like_a_drawing_number(number):
        return {}
    rest = parts[1] if len(parts) > 1 else ""
    rev_m = _REV_IN_NAME.search(stem.upper())
    title = _REV_TAIL.sub("", rest).strip(" _-") if rest else ""
    is_assembly = (strip_assembly_role(number) != number
                   or ext in (".sldasm",)
                   or bool(re.search(r"(?:^|[\s_\-])(GA|ASSY|ASSEMBLY)(?:$|[\s_\-])",
                                     stem.upper())))
    return {"number": number, "title": title,
            "revision": rev_m.group(1) if rev_m else "",
            "is_assembly": is_assembly, "file": base}


def resolve_product(declared: Any, file_names: Sequence[Any]) -> Dict[str, Any]:
    """The product a Drawing Number names among these files, said the way the engine will.

    status:
      "ok"         exactly one drawing matches, and it is an assembly
      "not_an_assembly"  one drawing matches and nothing says it is an assembly — a single
                   part drawing, which is a legitimate one-drawing job
      "none"       drawing numbers were read from the files and none matches
      "many"       more than one DIFFERENT drawing matches — the estimator must choose
      "unchecked"  no file name carries a drawing number, so nothing can be said
    `others` are the other assemblies in the pack: detail to this product, priced only where
    its BOM reaches them. Named so an estimator who meant one of THEM sees it before Run."""
    declared_s = str(declared or "").strip()
    drawings: Dict[str, Dict[str, Any]] = {}
    for name in file_names or []:
        d = drawing_of_file(name)
        if not d:
            continue
        k = _key(d["number"])
        have = drawings.get(k)
        if have is None:
            drawings[k] = dict(d, files=[d["file"]])
            continue
        have["files"].append(d["file"])
        have["is_assembly"] = have["is_assembly"] or d["is_assembly"]
        for f in ("title", "revision"):
            if not have.get(f) and d.get(f):
                have[f] = d[f]
        # The assembly spelling ("11650-06-GA") is the one to show, over "11650-06".
        if d["is_assembly"] and strip_assembly_role(have["number"]) == have["number"] \
                and strip_assembly_role(d["number"]) != d["number"]:
            have["number"] = d["number"]
    if not drawings:
        return {"status": "unchecked", "declared": declared_s, "match": None,
                "matches": [], "others": [],
                "message": "No file name here carries a drawing number, so the Drawing "
                           "Number cannot be checked before the run."}
    matches = [d for k, d in drawings.items() if names_the_product(declared_s, d["number"])]
    assemblies = sorted((d for d in drawings.values() if d["is_assembly"]),
                        key=lambda d: d["number"])

    def _label(d: Dict[str, Any]) -> str:
        return (d["number"] + (f" {d['title']}" if d.get("title") else "")
                + (f" (Rev {d['revision']})" if d.get("revision") else ""))

    if len(matches) > 1:
        return {"status": "many", "declared": declared_s, "match": None, "matches": matches,
                "others": [],
                "message": f"{declared_s} names {len(matches)} different drawings here ("
                           + "; ".join(_label(m) for m in matches)
                           + "). Type the one that is the product."}
    if not matches:
        return {"status": "none", "declared": declared_s, "match": None, "matches": [],
                "others": assemblies,
                "message": f"{declared_s} does not name any drawing added here. "
                           + (("Assemblies in the pack: " + "; ".join(_label(a) for a in
                                                                        assemblies)
                               + ". Type the one that is the product.")
                              if assemblies else
                              "Type the drawing number of the product.")}
    m = matches[0]
    others = [a for a in assemblies if _key(a["number"]) != _key(m["number"])]
    if not m["is_assembly"]:
        msg = (f"{_label(m)} is a single part drawing, not an assembly: this run prices that "
               f"part alone.")
        if others:
            msg += (" Assemblies in the pack: " + "; ".join(_label(o) for o in others)
                    + ". If the product is one of them, enter its number instead.")
        return {"status": "not_an_assembly", "declared": declared_s, "match": m,
                "matches": matches, "others": others, "message": msg}
    status = "ok"
    msg = f"This run prices {_label(m)}."
    if others:
        msg += (" Also in the pack: " + "; ".join(_label(o) for o in others)
                + f". They are detail to {m['number']} — priced only where its BOM reaches "
                  f"them, never as a second product. If one of them is what ships, enter "
                  f"its number instead.")
    return {"status": status, "declared": declared_s, "match": m, "matches": matches,
            "others": others, "message": msg}
