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

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

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
    t = re.sub(r"(?:[ _]+V\d{1,2})+$", "", t)          # a version mark, as the BOM link drops it
    t = strip_assembly_role(t.strip())
    # "12645-01GA": the role glued to the sheet number names the same sheet as "12645-01".
    t = re.sub(r"(\d)(GA|ASSY)$", r"\1", t)
    return re.sub(r"[\s\-_]+", "", t)


# A JOB NUMBER ON ITS OWN, and the word that starts a title after it. 12645's shelter sheet is
# numbered in its title block "12645 - DRS EXTERNAL SHELTER V2" and its file is
# "12645 - DRS External Shelter V2 REVA.PDF": the drawing number IS the job number, followed by
# the product's name. Numbered sub-sheets ("12645-01GA") continue with a digit, a title with a
# word of three or more letters — which is how the two are told apart.
_BARE_JOB_NUMBER = re.compile(r"^\d{4,6}$")
_TITLE_AFTER_NUMBER = re.compile(r"^\s*[-_\s]\s*([A-Z]{3,})\b", re.IGNORECASE)


def _job_number_with_title(identity: Any) -> str:
    """The bare job number when an identity is "<job number> <separator> <title words>", else ""."""
    text = str(identity or "").strip()
    m = re.match(r"^(\d{4,6})(.*)$", text)
    if not m or not _TITLE_AFTER_NUMBER.match(m.group(2) or ""):
        return ""
    return m.group(1)


def names_the_product(declared: Any, identity: Any) -> bool:
    """Does the Drawing Number the estimator typed name this drawing?

    One sheet, several spellings: "11650-06", "11650-06-GA", "11650-06 GA Rev B" all name
    the kit's general arrangement. A trailing revision and ONE sheet-role token are set
    aside on both sides and the rest must match exactly, ignoring spaces and dashes. Nothing
    looser: "11650-06" must never name 11650-06-SA01, which is a part OF the product."""
    d, i = _key(declared), _key(identity)
    if bool(d) and d == i:
        return True
    # "12645" names the sheet whose number is "12645 - DRS EXTERNAL SHELTER V2" — the job
    # number with the product's title after it — and never a numbered sub-sheet of the job.
    ds = str(declared or "").strip()
    if _BARE_JOB_NUMBER.match(ds):
        return _job_number_with_title(identity) == ds
    return False


def job_number_only(declared: Any) -> str:
    """The job number when the Drawing Number typed is a job number alone ("12173"), else ""."""
    ds = str(declared or "").strip()
    return ds if _BARE_JOB_NUMBER.match(ds) else ""


def is_of_the_job(job: Any, identity: Any) -> bool:
    """Is this drawing one of the job's own numbered sheets ("12173-02-GA" of job 12173)?

    The job number, then a separator, then the rest of the drawing number. "121730-01" is
    not job 12173's; "12173 - Card Spinner" (the job's number with its title) is."""
    j = str(job or "").strip()
    t = str(identity or "").strip()
    if not j or not _BARE_JOB_NUMBER.match(j):
        return False
    return bool(re.match(rf"^{re.escape(j)}(?:$|[\s\-_])", t, re.IGNORECASE))


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
    top_sheet = False
    # THE CUSTOMER'S FILING, NUMBER NOT FIRST. M&S packs arrive as
    # "0359887_TSE FOOTWEAR RISER_12527-22-GA_REV A.pdf": their enquiry number, the title,
    # then the drawing number. Read number-first, that is no drawing at all, so the product's
    # own sheet named nothing and 12527-22's header took a title block read off another page
    # ("RISER WELMENT"). Where the first token is not a drawing number, an underscore-separated
    # segment that IS one is the number, and the words around it — less the revision and any
    # all-digit reference — are the title.
    if not looks_like_a_drawing_number(number) and "_" in stem:
        segs = [s.strip() for s in stem.split("_") if s.strip()]
        hit = next((s for s in segs if looks_like_a_drawing_number(s)), "")
        if hit:
            words = [s for s in segs if s != hit and not s.isdigit()
                     and not _REV_TAIL.fullmatch("_" + s) and not re.fullmatch(
                         r"(?i)rev\.?\s*[A-Z0-9]{1,3}", s)]
            number, parts = hit, [hit, " ".join(words)]
    if not looks_like_a_drawing_number(number):
        # A job's own top sheet is filed "<job number> - <title>" (12645's shelter). The bare
        # number is accepted only with a title after it; a lone number is not a drawing.
        if not (_BARE_JOB_NUMBER.match(number)
                and _TITLE_AFTER_NUMBER.match(parts[1] if len(parts) > 1 else "")):
            return {}
        top_sheet = True
    rest = parts[1] if len(parts) > 1 else ""
    rev_m = _REV_IN_NAME.search(stem.upper())
    title = _REV_TAIL.sub("", rest).strip(" _-") if rest else ""
    is_assembly = (strip_assembly_role(number) != number
                   or ext in (".sldasm",)
                   # "GA2" is a job's second general arrangement (7332-01-GA2, 12392-01-GA5):
                   # the numbered role is still the role. One digit; _key keeps GA and GA2
                   # distinct products, which is a different question.
                   or bool(re.search(r"(?:^|[\s_\-])(GA\d?|ASSY|ASSEMBLY)(?:$|[\s_\-])",
                                     stem.upper()))
                   # "12645-01GA": the role glued to the sheet number, no separator.
                   or bool(re.search(r"\d(GA|ASSY)$", number.upper())))
    return {"number": number, "title": title,
            "revision": rev_m.group(1) if rev_m else "",
            "is_assembly": is_assembly, "file": base, "top_sheet": top_sheet}


def _mention(number: Any) -> "re.Pattern[str]":
    """A drawing number as another sheet would print it: its own tokens, any separator, and
    not running on into a longer number ("12173-07" is not "12173-07-1-GA")."""
    toks = [t for t in re.split(r"[\s\-_]+", str(number or "").strip().upper()) if t]
    body = r"[\s\-_]*".join(re.escape(t) for t in toks)
    # A dash or underscore then a digit continues the number; a space then a digit is the
    # QTY column ("12173-07-GA 1").
    return re.compile(rf"(?<![A-Z0-9]){body}(?![A-Z0-9])(?![\-_]\d)", re.IGNORECASE)


def tops_of_the_job(assemblies: Sequence[Mapping[str, Any]],
                    texts: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Of these assemblies, the ones no OTHER drawing in the pack lists.

    `texts` is each drawing file's own words (file name -> text of its pages). A GA that
    appears in another sheet's parts list is detail to that sheet; the one that appears in
    none is what ships. 12173: 02-GA's table lists 03-, 04-, 05-, 06- and 07-GA, 07-GA's
    lists 07-1 and 07-2, and nothing lists 02-GA. Read from the drawings, not from a name:
    no suffix, sheet number or wording decides it."""
    own = {str(f): _key((drawing_of_file(f) or {}).get("number") or "") for f in texts}
    out: List[Dict[str, Any]] = []
    for a in assemblies:
        k = _key(a["number"])
        pat = _mention(a["number"])
        listed_by = sorted(f for f, t in texts.items() if own.get(f) != k and pat.search(t or ""))
        if not listed_by:
            out.append(a)
    return out


def read_texts(paths: Sequence[Any]) -> Dict[str, str]:
    """Each PDF's words, keyed by file name — folders as their contents, one level down as
    well. Needs PyMuPDF, so the service runs it with the ENGINE's python (see __main__)."""
    try:
        import pymupdf as fitz                                       # type: ignore
    except Exception:                                                # noqa: BLE001
        import fitz                                                  # type: ignore
    files: List[Path] = []
    for raw in paths or []:
        p = Path(str(raw))
        if p.is_dir():
            for c in sorted(p.iterdir()):
                files.extend([c] if c.is_file() else
                             sorted(g for g in c.iterdir() if g.is_file()) if c.is_dir() else [])
        elif p.is_file():
            files.append(p)
    out: Dict[str, str] = {}
    for f in files:
        if f.suffix.lower() != ".pdf" or not drawing_of_file(f.name):
            continue
        try:
            with fitz.open(str(f)) as doc:
                out[f.name] = " ".join(" ".join(pg.get_text().split()) for pg in doc)
        except Exception:                                            # noqa: BLE001
            continue
    return out


def resolve_product(declared: Any, file_names: Sequence[Any],
                    texts: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The product a Drawing Number names among these files, said the way the engine will.

    status:
      "ok"         exactly one drawing matches, and it is an assembly
      "not_an_assembly"  one drawing matches and nothing says it is an assembly — a single
                   part drawing, which is a legitimate one-drawing job
      "none"       drawing numbers were read from the files and none matches
      "many"       more than one DIFFERENT drawing matches — the estimator must choose
      "unchecked"  no file name carries a drawing number, so nothing can be said
      "job"        the job number alone ("12173"): the product is the job's assembly no
                   other drawing lists, read from `texts` (the drawings' own words) when
                   given — `match` is it — and left to the run's parts lists when not
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
    # A job's top sheet is an assembly when the pack holds the job's numbered sheets under it:
    # "12645 - DRS External Shelter" over 12645-01GA, -02GA and -03GA. Evidence from the pack,
    # not from the name.
    for d in drawings.values():
        if d.get("top_sheet") and not d["is_assembly"]:
            d["is_assembly"] = any(str(o["number"]).startswith(d["number"] + "-")
                                   for o in drawings.values() if o is not d)
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
    # THE JOB NUMBER ON ITS OWN IS THE JOB, AND THE JOB SHIPS ITS TOP ASSEMBLY. James Gray,
    # 29 Sep 2026, on 12173 Card Spinner: "it is 02 but we need to be able to run against the
    # top level 12173." The pack holds 12173-02-GA (the spinner) and the GAs it is built from
    # (03, 04, 05, 06, 07...). Which is on top is written in the parts lists — 02's table
    # takes the others — so it is read from them: the drawings' own words (`texts`), the one
    # job GA no other sheet lists. Then: "It needs to accept a job number without needing a
    # version number and work out from the PDF GAs what needs to be analysed" — no suffix or
    # name decides it. Without the words (a machine with no PDF reader) the check lets the run
    # go, and the run takes the same answer from its parsed tables (route_compiler). Two tops
    # are a choice, and a choice is the estimator's.
    job = job_number_only(declared_s)
    job_assemblies = [a for a in assemblies if is_of_the_job(job, a["number"])] if job else []
    if not matches and job_assemblies:
        listing = "; ".join(_label(a) for a in job_assemblies)
        tops = tops_of_the_job(job_assemblies, texts) if texts else []
        if len(tops) == 1:
            top = tops[0]
            rest = [a for a in job_assemblies if a is not top]
            return {"status": "job", "declared": declared_s, "match": top, "matches": [top],
                    "others": rest,
                    "message": f"{declared_s} is the job number. Read from the drawings' own "
                               f"parts lists, the product is {_label(top)} — no other drawing "
                               f"in the pack lists it. This run prices it, and "
                               + ("; ".join(_label(a) for a in rest) or "nothing else")
                               + " only where its parts list reaches them."}
        if len(tops) > 1:
            return {"status": "many", "declared": declared_s, "match": None, "matches": tops,
                    "others": job_assemblies,
                    "message": f"{declared_s} is the job number, and {len(tops)} of its "
                               f"drawings are listed by no other drawing in the pack ("
                               + "; ".join(_label(t) for t in tops)
                               + "), so there is more than one thing on top. Type the one "
                                 "that is the product, or add the drawing that lists them."}
        return {"status": "job", "declared": declared_s, "match": None, "matches": [],
                "others": job_assemblies,
                "message": f"{declared_s} is the job number, not a drawing: the run reads the "
                           f"parts lists and prices the assembly no other drawing lists, and "
                           f"the book names it. Assemblies in the pack: {listing}."}
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


def product_sheets(product: Any, file_names: Sequence[Any]) -> List[Dict[str, Any]]:
    """The product's own drawing files, as drawing_of_file reads each one.

    A JOB'S TOP SHEET IS ITS NUMBER WITH ITS TITLE. 12645's shelter is filed "12645 - DRS
    External Shelter V2_REVA.PDF", which reads as number "12645" and title "DRS External
    Shelter V2", while the graph's product root is the whole "12645-DRS EXTERNAL SHELTER V2"
    (the title block's own number). Compared on the number alone, the product's own sheet
    never named the product, and the 19:17 book's Description box fell through to a sibling:
    "DOOR FRAME" (D-319). So a top sheet is compared on its whole identity as well, by the
    same resolver."""
    out: List[Dict[str, Any]] = []
    for name in file_names or []:
        d = drawing_of_file(name)
        if not d:
            continue
        ids = [d["number"]]
        if d.get("top_sheet") and d.get("title"):
            ids.append(f"{d['number']} {d['title']}")
        if any(names_the_product(product, i) for i in ids):
            out.append(d)
    return out


def title_from_files(product: Any, file_names: Sequence[Any]) -> str:
    """The product's title as its own drawing file names it ("11650-06-GA COFFRET HOSPITAL
    KIT_REVB.PDF" -> "COFFRET HOSPITAL KIT"), or "" when no file names it.

    11650-06's header read "END PANEL GF CONVERSION PANEL SET" — the extender set's title
    block, read by the model off another page of the same pack — and the report's scope line
    read "assembly (from the SolidWorks model's own tree)", an engine note. The file name is
    the drawing office's own label for the product's sheet, and it does not move."""
    return max((d.get("title") or "" for d in product_sheets(product, file_names)),
               key=len, default="")


def _main(argv: List[str]) -> int:
    """`--texts <file or folder>... --json`: each drawing PDF's words, for the service, which
    has no PDF library of its own."""
    if not argv or argv[0] != "--texts":
        print("usage: product_identity.py --texts <file or folder>... [--json]", file=sys.stderr)
        return 2
    paths = [a for a in argv[1:] if a != "--json"]
    print(json.dumps({"texts": read_texts(paths)}))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
