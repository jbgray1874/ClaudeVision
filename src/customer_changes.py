"""A change the customer asked for after the drawings were issued — accepted, costed, on the record.

"It happens sometimes and we don't have time to change the drawing pack." An e-mail arrives:
the side panels in 2 mm, not 1.5; stainless, not mild steel; 250 off, not 100. The drawings
still say what they said, and until now there were only two ways to cost the change: redraw
the pack, or overtype the workbook — which dies with that workbook, and says nothing about why.

THREE STEPS, THE SAME SHAPE AS THE MATERIAL CONFIRMATION (D-313):

  propose_changes(email, index)   the e-mail read against the pack's own part list: per change,
                                  the part, the field, what the drawing states, what is asked,
                                  and the e-mail's own words. Run out of process with the
                                  engine's python, like the material read:
                                      python src/customer_changes.py --read <files> < email.txt
  build_changes_file(...)         the estimator's ticks checked and turned into the job's
                                  `<drawing>_customer_changes.json`.
  apply_customer_changes(...)     the engine stamps the accepted changes onto the parts, last and
                                  highest, and puts both values on the book.

THE RULES, each one a way this could do harm:

  * NOTHING IS APPLIED WITHOUT A TICK. The read proposes; a person accepts, by name.
  * EVERY CHANGE CARRIES ITS EVIDENCE. A change read from the e-mail quotes the e-mail's own
    words, and a quote that is not in the e-mail is refused — a model's paraphrase is not the
    customer's instruction. A change typed by hand (the "prompt override" for a drawing pack)
    carries a reason: a phone call, a site visit, a revised spec.
  * THE BOOK SHOWS BOTH VALUES. "the drawings: 1.5 mm; customer e-mail: 2 mm — COSTED AT 2 mm".
    A quote costed on a value the drawings do not state has to say so wherever it is read.
  * WHAT THIS CANNOT APPLY IS ASKED, NEVER DROPPED. A new part, an extra hole, a reshaped
    bend, a price: none of those is a field this can change, and each becomes a question on
    the book naming the e-mail's words, so the estimate is a visible draft until it is priced.
  * NO PRICE, EVER — the same refusal as the answers file, by the same list of names.
  * A CODE THAT MATCHES NO PART IS REPORTED, so a typo never quietly does nothing.

WHERE IT RANKS. `customer_change`, 101 in source_precedence: above a person reading or correcting
the drawing (100), because it is not a reading of the drawing at all — the drawing is right
about what was drawn and the customer has since changed what is wanted.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SOURCE = "customer_change"
WRITTEN_BY = "portal customer changes"
FILE_SUFFIX = "_customer_changes.json"

# What a change may set on a part, and the record field the estimator reads it from. The same
# names the answers file uses, so the two can never mean different things by one word.
PART_FIELDS: Dict[str, str] = {
    "material": "normalized_material",
    "thickness_mm": "normalized_thickness_mm",
    "finish": "normalized_finish",
    "quantity": "quantity",
    "blank_length_mm": "blank_length_mm",
    "blank_width_mm": "blank_width_mm",
}
# A SIZE AS THE CUSTOMER STATES IT: an overall dimension, from -> to. Mapped onto the blank by
# the engine, which holds the blank; see _apply_size for exactly when it can and cannot.
SIZE_FIELD = "size_mm"
# Decisions about a part rather than facts of it.
DECISION_FIELDS = ("operation_off", "make_or_buy")
# About the order, not a part.
JOB_FIELDS = ("order_quantity",)
FIELDS = tuple(PART_FIELDS) + (SIZE_FIELD,) + DECISION_FIELDS + JOB_FIELDS

LABELS = {"material": "material", "thickness_mm": "thickness", "finish": "finish",
          "quantity": "quantity per assembly", "blank_length_mm": "blank length",
          "blank_width_mm": "blank width", SIZE_FIELD: "size",
          "operation_off": "operation taken off", "make_or_buy": "make or buy",
          "order_quantity": "order quantity"}

# FINISH WORDS AS PEOPLE WRITE THEM, onto the finishes the engine prices. Longest and most
# specific first: "zinc plated" must not stop at "plat", "powder" must win over "coat".
_FINISH_WORDS: Tuple[Tuple[str, str], ...] = (
    (r"POWDER", "POWDER COATED"),
    (r"ZINC", "ZINC PLATED"),
    (r"GALV", "GALVANISED"),
    (r"ANODI[SZ]", "ANODISED"),
    (r"POLISH", "POLISHED"),
    (r"BRUSH|SATIN", "BRUSHED"),
    (r"WET\s*SPRAY|PAINT|SPRAY", "PAINTED"),
    (r"PLAT", "PLATED"),
    (r"\bRAW\b|SELF[\s-]*FINISH|UNFINISHED|NO\s+FINISH|UNCOATED|UNPAINTED|BARE", "RAW"),
)


def _cfg() -> Dict[str, Any]:
    try:
        import config as _c
        return dict(getattr(_c, "CUSTOMER_CHANGES", {}) or {})
    except Exception:                                                # noqa: BLE001
        return {}


def _num(value: Any) -> Optional[float]:
    try:
        out = float(str(value).strip().lower().replace("mm", "").replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return None
    return out if out > 0 else None


def _plain(text: Any) -> str:
    """Words only, one space, one case — how a quote is found in the e-mail it came from."""
    t = str(text or "").replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    return " ".join(re.sub(r"[^\w\s.'/%-]", " ", t).split()).casefold()


def quote_in_email(quote: Any, email: Any) -> bool:
    """Is this the customer's own wording? Ignores case, spacing and punctuation only."""
    q = _plain(quote).strip(" .'\"")
    return bool(q) and len(q) >= 4 and q in _plain(email)


def _bare(code: Any) -> str:
    try:
        from part_code_conventions import bare_code
        return bare_code(str(code or ""))
    except Exception:                                                # noqa: BLE001
        return re.sub(r"[\s\-]+", "", str(code or "").upper())


def _refused_keys() -> Tuple[str, ...]:
    try:
        from estimator_confirmed import _REFUSED_KEYS
        return tuple(_REFUSED_KEYS)
    except Exception:                                                # noqa: BLE001
        return ("price", "cost", "rate", "gbp", "price_gbp", "cost_gbp", "unit_price",
                "material_cost", "labour_cost")


def _find_refused(obj: Any, where: str, out: List[str]) -> None:
    """A price anywhere in what was sent is refused by name, like the answers file."""
    refused = _refused_keys()
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            kl = str(k).strip().lower()
            if kl in refused or any(w in kl for w in ("price", "cost", "gbp")):
                out.append(f"{where}{k}: REFUSED — a customer change states what the product "
                           f"is, never what it costs. Price it on the sheet, where it shows "
                           f"as your decision")
            else:
                _find_refused(v, f"{where}{k}.", out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _find_refused(v, f"{where}[{i}].", out)


# ── the vocabulary a value must come from ───────────────────────────────────────────────

def material_codes() -> List[str]:
    try:
        from material_confirmation import material_codes as _mc
        return list(_mc())
    except Exception:                                                # noqa: BLE001
        return []


def finishes() -> List[str]:
    try:
        from material_confirmation import FINISHES
        return list(FINISHES)
    except Exception:                                                # noqa: BLE001
        return [f for _, f in _FINISH_WORDS]


def operations() -> List[str]:
    """The route words the engine costs — the only operations a change may take off."""
    try:
        from llm_full_extract import ROUTE_OPERATIONS
        return list(ROUTE_OPERATIONS)
    except Exception:                                                # noqa: BLE001
        return []


def vocabulary() -> Dict[str, Any]:
    try:
        from material_confirmation import material_label
    except Exception:                                                # noqa: BLE001
        def material_label(c: str) -> str:                           # type: ignore
            return str(c).replace("_", " ").title()
    codes = material_codes()
    return {"fields": list(FIELDS), "labels": dict(LABELS), "material": codes,
            "material_labels": {c: material_label(c) for c in codes},
            "finish": finishes(), "operation_off": operations(),
            "make_or_buy": ["buy", "make"]}


def normalise_material(text: Any) -> Optional[str]:
    """The engine's material code for these words, or None. Never a guess: the lexicon
    answers, or nobody does."""
    raw = str(text or "").strip()
    if not raw:
        return None
    codes = set(material_codes())
    up = re.sub(r"[\s\-]+", "_", raw.upper())
    if up in codes:
        return up
    try:
        from material_confirmation import normalise_material as _nm
        code = _nm(raw)
    except Exception:                                                # noqa: BLE001
        code = None
    if code and (not codes or code in codes):
        return code
    return None


def normalise_finish(text: Any) -> Optional[str]:
    up = " ".join(str(text or "").upper().split())
    if not up:
        return None
    for f in sorted(finishes(), key=len, reverse=True):
        if f in up:
            return f
    for pattern, f in _FINISH_WORDS:
        if re.search(pattern, up):
            return f
    return None


def _operation(text: Any) -> Optional[str]:
    """A route word, matched on its letters, so 'powder coating' and 'powder_coating' agree."""
    letters = re.sub(r"[^a-z]", "", str(text or "").lower())
    if not letters:
        return None
    known = operations()
    if not known:
        return str(text).strip().lower().replace(" ", "_")
    for op in known:
        if re.sub(r"[^a-z]", "", op) == letters:
            return op
    # A word the shop uses for one of them: "weld" -> welding, "fold" -> folding.
    hits = [op for op in known if re.sub(r"[^a-z]", "", op).startswith(letters)
            or letters.startswith(re.sub(r"[^a-z]", "", op))]
    return hits[0] if len(hits) == 1 else None


# ── one change, checked ──────────────────────────────────────────────────────────────────

def clean_change(raw: Mapping[str, Any], *, email: str = "",
                 index_codes: Optional[Iterable[str]] = None
                 ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the change in its checked form, or None; why not, or None).

    The same check runs on what the read proposed, on what the page sends at Run, and on the
    file the engine loads — so a hand-written file gets no easier ride than a ticked box.
    """
    if not isinstance(raw, Mapping):
        return None, "a change must be an object"
    field = str(raw.get("field") or "").strip().lower()
    if field not in FIELDS:
        return None, (f"'{raw.get('field')}' is not something this box can change "
                      f"(it can change: {', '.join(LABELS[f] for f in FIELDS)})")
    origin = str(raw.get("origin") or ("email" if raw.get("quote") else "manual")).lower()
    quote = " ".join(str(raw.get("quote") or "").split())
    reason = " ".join(str(raw.get("reason") or "").split())
    if origin == "email":
        if not quote:
            return None, "a change read from the e-mail must quote the e-mail's own words"
        if email and not quote_in_email(quote, email):
            return None, (f"the words \"{quote[:120]}\" are not in the e-mail — a paraphrase is "
                          f"not the customer's instruction")
    elif not reason:
        return None, ("a change typed by hand needs a reason — who asked, and how (a call, a "
                      "revised spec) — or it is a guess wearing the customer's authority")
    part = str(raw.get("part") or "").strip()
    if field in JOB_FIELDS:
        part = ""
    elif not part:
        return None, f"a {LABELS[field]} change must name the part it applies to"

    value: Any = raw.get("value")
    note = " ".join(str(raw.get("note") or "").split())
    if field == "material":
        code = normalise_material(value)
        if not code:
            return None, (f"'{value}' is not a material the engine prices — choose one from the "
                          f"list")
        value = code
    elif field == "finish":
        fin = normalise_finish(value)
        if not fin:
            return None, f"'{value}' is not a finish the engine prices — choose one from the list"
        # The colour is kept as words: a RAL number changes nothing that is costed.
        if not note and str(value).strip().upper() != fin:
            note = str(value).strip()
        value = fin
    elif field in ("thickness_mm", "blank_length_mm", "blank_width_mm"):
        n = _num(value)
        if n is None:
            return None, f"{LABELS[field]} {value!r} is not a size in mm"
        value = n
    elif field in ("quantity", "order_quantity"):
        n = _num(value)
        if n is None or n != int(n):
            return None, f"{LABELS[field]} {value!r} is not a whole number of 1 or more"
        value = int(n)
    elif field == SIZE_FIELD:
        v = value if isinstance(value, Mapping) else {}
        to = _num(v.get("to"))
        frm = _num(v.get("from")) if v.get("from") not in (None, "") else None
        if to is None:
            return None, "a size change needs the new size in mm"
        if frm is None:
            return None, ("a size change needs the size it replaces as well as the new one — "
                          "\"1800 to 2000\" — so the right side of the blank is changed")
        if abs(frm - to) < 1e-9:
            return None, "the new size is the same as the old one"
        value = {"from": frm, "to": to}
    elif field == "operation_off":
        op = _operation(value)
        if not op:
            return None, (f"'{value}' is not an operation the route costs — choose one from "
                          f"the list")
        value = op
    elif field == "make_or_buy":
        a = str(value or "").strip().lower()
        if a in ("buy", "bought", "bought in", "bought-in", "purchase", "purchased"):
            value = "buy"
        elif a in ("make", "made", "fabricate", "fabricated"):
            value = "make"
        else:
            return None, f"make or buy must be 'buy' or 'make', not {value!r}"

    out: Dict[str, Any] = {"part": part, "field": field, "value": value, "origin": origin}
    if quote:
        out["quote"] = quote
    if reason:
        out["reason"] = reason
    if note:
        out["note"] = note
    if raw.get("drawing_value") not in (None, ""):
        out["drawing_value"] = raw.get("drawing_value")
    if part and index_codes is not None:
        if _bare(part) not in {_bare(c) for c in index_codes}:
            out["not_read_from_pack"] = True
    return out, None


def describe(value: Any, field: str) -> str:
    if value in (None, ""):
        return "not stated"
    if field in ("thickness_mm", "blank_length_mm", "blank_width_mm"):
        try:
            return f"{float(value):g} mm"
        except (TypeError, ValueError):
            return str(value)
    if field == SIZE_FIELD and isinstance(value, Mapping):
        return f"{float(value['from']):g} mm -> {float(value['to']):g} mm"
    if field == "material":
        try:
            from material_confirmation import material_label
            return material_label(str(value))
        except Exception:                                            # noqa: BLE001
            return str(value)
    return str(value)


# ── reading the e-mail ──────────────────────────────────────────────────────────────────

def part_index(paths: Iterable[Any]) -> Dict[str, Any]:
    """The pack's own part list — codes, what each sheet states — and its words, for the read
    to map "the side panels" onto codes. Needs PyMuPDF: run with the engine's python."""
    import material_confirmation as mc
    reading = mc.read_pack(paths)
    context: List[str] = []
    budget = int(_cfg().get("pack_context_chars", 30000))
    try:
        from llm_full_extract import build_document_context
        for f in mc._files_in(paths):
            if f.suffix.lower() == ".pdf" and budget > 0:
                text = build_document_context(f, max_chars=budget)
                if text:
                    context.append(f"##### {f.name}\n{text}")
                    budget -= len(text)
    except Exception as exc:                                         # noqa: BLE001
        context.append(f"(the pack's text could not be read: {type(exc).__name__})")
    return {"parts": reading.get("parts") or [], "unread": reading.get("unread") or [],
            "context": "\n".join(context)}


_PROMPT = """You are an estimator at a sheet-metal and display fabricator. A customer has e-mailed
changes to a product AFTER its drawings were issued. Read the e-mail and list every change it
asks for, so the estimate can be costed on the changed product.

Return STRICT JSON only, no prose:
{"changes": [{"parts": ["<part code from the PART INDEX>", ...],
              "field": "<one of: %(fields)s>",
              "value": <see below>,
              "quote": "<the customer's words, copied EXACTLY from the e-mail>"}],
 "questions": [{"quote": "<the customer's words, copied exactly>",
                "ask": "<what the estimator must decide, in one sentence>"}]}

Fields and values:
  material        the material asked for, in the e-mail's words ("304 stainless", "aluminium")
  thickness_mm    a number, in mm
  finish          the finish in the e-mail's words ("powder coat RAL 9005", "zinc plated", "raw")
  quantity        a whole number — how many of THAT part go into one product
  size_mm         {"from": <the size it replaces, mm, or null>, "to": <the new size, mm>}
  operation_off   the operation the customer no longer wants (e.g. "powder_coating", "welding")
  make_or_buy     "buy" or "make"
  order_quantity  a whole number — how many products are ordered (parts: [])

Rules:
  - Only what the e-mail ASKS FOR. Never infer a change it does not state.
  - "parts" must use codes exactly as written in the PART INDEX. Where the e-mail names parts
    by description ("the side panels"), use the PACK TEXT to find their codes. Where it says
    "all" of something, list every matching code. If you cannot tell which parts, it is a
    question, not a change.
  - "quote" is copied character for character from the e-mail; never paraphrase.
  - Anything that is not one of the fields above — a new or removed part, a hole, a change of
    shape, a delivery date, a price — goes in "questions".
  - Ignore greetings, signatures, disclaimers and quoted earlier messages.
"""


def build_prompt(email: str, index: Mapping[str, Any]) -> str:
    rows = []
    for p in (index.get("parts") or []):
        st = p.get("stated") or {}
        said = ", ".join(x for x in (
            st.get("material_text") or st.get("material") or "",
            f"{st['thickness_mm']:g} mm" if st.get("thickness_mm") is not None else "",
            st.get("finish") or "") if x)
        rows.append(f"{p.get('part')}" + (f" | drawing states: {said}" if said else ""))
    cap = int(_cfg().get("email_max_chars", 20000))
    return (_PROMPT % {"fields": ", ".join(FIELDS)}
            + "\n--- PART INDEX ---\n" + ("\n".join(rows) or "(no part codes were read)")
            + "\n--- PACK TEXT ---\n" + str(index.get("context") or "(none)")
            + "\n--- E-MAIL ---\n" + str(email or "")[:cap])


def _default_call(prompt: str) -> Optional[str]:
    if str(os.environ.get("SDI_OFFLINE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("offline (SDI_OFFLINE is set)")
    try:
        import config  # noqa: F401  — loads .env, where the xAI key lives
    except Exception:                                                # noqa: BLE001
        pass
    from llm_full_extract import DEFAULT_MODEL, SYSTEM_INFER, _call_llm
    return _call_llm(prompt, str(_cfg().get("model") or DEFAULT_MODEL), system=SYSTEM_INFER)


def _parse(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        from llm_full_extract import _parse as _p
        return _p(str(raw or ""))
    except Exception:                                                # noqa: BLE001
        try:
            obj = json.loads(str(raw or ""))
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None


def propose_changes(email: str, index: Mapping[str, Any],
                    call: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """What the e-mail asks for, as checked changes and open questions. Nothing is written.

    A proposal that fails its check is NOT dropped: it becomes a question carrying the reason,
    so the estimator sees everything the e-mail asked for and decides what to do with it.
    """
    if not str(email or "").strip():
        return {"status": "empty", "message": "Paste the customer's e-mail first.",
                "changes": [], "questions": []}
    try:
        raw = (call or _default_call)(build_prompt(email, index))
    except Exception as exc:                                         # noqa: BLE001
        return {"status": "unavailable", "changes": [], "questions": [],
                "message": f"the e-mail could not be read ({type(exc).__name__}: {exc}). "
                           f"Add the changes by hand below."}
    obj = _parse(raw)
    if not obj:
        return {"status": "unavailable", "changes": [], "questions": [],
                "message": "the read returned nothing usable. Add the changes by hand below."}
    stated = {_bare(p.get("part")): p for p in (index.get("parts") or [])}
    codes = [str(p.get("part")) for p in (index.get("parts") or [])]
    changes: List[Dict[str, Any]] = []
    questions: List[Dict[str, Any]] = []
    for item in (obj.get("changes") or []):
        if not isinstance(item, Mapping):
            continue
        parts = item.get("parts")
        if isinstance(parts, str):
            parts = [parts]
        if not isinstance(parts, (list, tuple)):
            parts = []
        field = str(item.get("field") or "").strip().lower()
        targets = [""] if field in JOB_FIELDS else [str(p).strip() for p in parts
                                                   if str(p).strip()]
        if not targets:
            questions.append({"quote": str(item.get("quote") or ""),
                              "ask": f"The e-mail asks for a {LABELS.get(field, field)} change "
                                     f"but the read could not tell which parts — name them"})
            continue
        for part in targets:
            dv = None
            if part and field in ("material", "thickness_mm", "finish"):
                st = (stated.get(_bare(part)) or {}).get("stated") or {}
                dv = ((st.get("material_text") or st.get("material")) if field == "material"
                      else st.get(field))
            ch, why = clean_change({"part": part, "field": field, "value": item.get("value"),
                                    "quote": item.get("quote"), "origin": "email",
                                    "drawing_value": dv},
                                   email=email, index_codes=codes)
            if ch is None:
                questions.append({"quote": str(item.get("quote") or ""), "part": part,
                                  "ask": f"Not proposed as a change: {why}"})
                continue
            if ch["field"] in ("material", "thickness_mm", "finish") and dv is not None \
                    and _same(ch["value"], dv, ch["field"]):
                ch["already_drawn"] = True
            changes.append(ch)
    for q in (obj.get("questions") or []):
        if isinstance(q, Mapping) and (q.get("ask") or q.get("quote")):
            questions.append({"quote": " ".join(str(q.get("quote") or "").split()),
                              "ask": " ".join(str(q.get("ask") or "").split())})
    return {"status": "ok", "changes": changes, "questions": questions}


def _same(a: Any, b: Any, field: str) -> bool:
    if field == "thickness_mm":
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return False
    if field == "material":
        return str(a).upper() == str(normalise_material(b) or b).upper()
    return str(a or "").strip().upper() == str(b or "").strip().upper()


# ── the estimator's ticks, written as the job's file ────────────────────────────────────

def build_changes_file(submitted: Mapping[str, Any], drawing_number: str,
                       today: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
    """(the file, errors). Any error means nothing is written and nothing is queued.

    submitted = {
      "accepted_by": "James Gray",
      "email": "<the pasted e-mail>",
      "changes":   [{"part", "field", "value", "quote" | "reason", "origin", "accepted"}],
      "questions": [{"quote", "ask", "keep"}],
    }
    """
    errors: List[str] = []
    if not isinstance(submitted, Mapping):
        return {}, ["customer changes must be an object"]
    _find_refused(submitted, "", errors)
    who = str(submitted.get("accepted_by") or "").strip()
    if not who:
        errors.append("accepted_by: say who accepted these changes — a change with no name on "
                      "it cannot be trusted or asked about")
    email = str(submitted.get("email") or "")
    accepted: List[Dict[str, Any]] = []
    declined: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, str], Any] = {}
    for i, raw in enumerate(submitted.get("changes") or [], start=1):
        if not isinstance(raw, Mapping):
            errors.append(f"change {i}: not an object")
            continue
        ch, why = clean_change(raw, email=email)
        if ch is None:
            if raw.get("accepted"):
                errors.append(f"change {i} ({raw.get('part') or 'the order'}, "
                              f"{LABELS.get(str(raw.get('field')), raw.get('field'))}): {why}")
            continue
        if not raw.get("accepted"):
            declined.append(ch)
            continue
        key = (_bare(ch["part"]), ch["field"])
        if key in seen and seen[key] != ch["value"]:
            errors.append(f"{ch['part'] or 'the order'}: two different {LABELS[ch['field']]} "
                          f"values are ticked ({describe(seen[key], ch['field'])} and "
                          f"{describe(ch['value'], ch['field'])}) — untick one")
            continue
        seen[key] = ch["value"]
        accepted.append(ch)
    questions = [{"quote": " ".join(str(q.get("quote") or "").split()),
                  "ask": " ".join(str(q.get("ask") or "").split()),
                  **({"part": str(q["part"])} if q.get("part") else {})}
                 for q in (submitted.get("questions") or [])
                 if isinstance(q, Mapping) and q.get("keep", True)
                 and (q.get("ask") or q.get("quote"))]
    if errors:
        return {}, errors
    if not accepted and not questions and not declined:
        return {}, []
    cap = int(_cfg().get("email_max_chars", 20000))
    return {
        "drawing_number": str(drawing_number or "").strip(),
        "written_by": WRITTEN_BY,
        "accepted_by": who,
        "accepted_on": today or date.today().isoformat(),
        "note": ("Changes the customer asked for after the drawings were issued, accepted "
                 "before the run in the estimating portal. Each is costed in place of what "
                 "the drawings state, and the book shows both."),
        "changes": accepted,
        "declined": declined,
        "questions": questions,
        "email": email[:cap],
    }, []


def file_name(drawing: str) -> str:
    return f"{drawing}{FILE_SUFFIX}"


def write_changes(folder: Any, drawing: str, data: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Write the portal's file into the staged job folder — or, with nothing this run, remove
    the one the portal wrote last time, so an old e-mail never governs a new estimate. A file a
    person wrote by hand is never touched."""
    target = Path(str(folder)) / file_name(drawing)
    if data and (data.get("changes") or data.get("questions")):
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


# ── the engine's side ───────────────────────────────────────────────────────────────────

def find_changes_file(job_folder: Any, pdf_path: Any = None,
                      drawing_number: Any = None) -> Optional[Path]:
    """`<name>_customer_changes.json` beside the drawings, under any name the job answers to:
    the drawing number and its stems, the PDF's name, the folder's name. Exact names only —
    a customer's change to one job must never be found by another."""
    try:
        from estimator_confirmed import drawing_stems
    except Exception:                                                # noqa: BLE001
        def drawing_stems(d: Any) -> List[str]:                      # type: ignore
            return [str(d)] if d else []
    roots: List[Path] = []
    for cand in (job_folder, (Path(pdf_path).parent if pdf_path else None)):
        try:
            root = Path(cand) if cand else None
        except (TypeError, ValueError):
            root = None
        if root is not None and root.is_dir() and root not in roots:
            roots.append(root)
    names: List[str] = []
    for text in [drawing_number, (Path(pdf_path).stem if pdf_path else None)] + \
            [r.name for r in roots]:
        for stem in drawing_stems(text):
            if stem and stem not in names:
                names.append(stem)
    for root in roots:
        for name in names:
            path = root / file_name(name)
            if path.is_file():
                return path
    return None


def load_changes(path: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Read and re-check the file. Every line that cannot be used is reported, never skipped
    quietly: whoever wrote it believes the job is being costed from it."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [f"{path}: no such file"]
    except (OSError, ValueError) as err:
        return {}, [f"{path}: could not be read — {type(err).__name__}: {err}"]
    if not isinstance(raw, Mapping):
        return {}, [f"{path}: the top level must be an object"]
    problems: List[str] = []
    _find_refused({k: v for k, v in raw.items() if k != "email"}, "", problems)
    email = str(raw.get("email") or "")
    changes: List[Dict[str, Any]] = []
    for i, item in enumerate(raw.get("changes") or [], start=1):
        ch, why = clean_change(item, email=email) if isinstance(item, Mapping) else \
            (None, "not an object")
        if ch is None:
            problems.append(f"change {i}: {why} — not applied")
            continue
        changes.append(ch)
    questions = [q for q in (raw.get("questions") or []) if isinstance(q, Mapping)]
    declined = [d for d in (raw.get("declined") or []) if isinstance(d, Mapping)]
    return {"accepted_by": str(raw.get("accepted_by") or "").strip() or "an estimator",
            "accepted_on": str(raw.get("accepted_on") or "").strip(),
            "changes": changes, "questions": questions, "declined": declined,
            "problems": list(problems), "path": str(path)}, problems


def _root_part(parts: Sequence[Any], drawing_number: Any) -> Optional[Dict[str, Any]]:
    """The product's own record: where a job-level question is asked so the book counts it."""
    try:
        from estimator_confirmed import drawing_stems
        stems = {_bare(s) for s in drawing_stems(drawing_number)}
    except Exception:                                                # noqa: BLE001
        stems = {_bare(drawing_number)} if drawing_number else set()
    dicts = [p for p in parts if isinstance(p, dict)]
    for p in dicts:
        if _bare(p.get("part_number")) in stems:
            return p
    for p in dicts:
        if p.get("is_assembly_parent") or p.get("assembly_children"):
            return p
    return dicts[0] if dicts else None


def _blank_axes(part: Mapping[str, Any]) -> List[Tuple[str, float]]:
    import source_precedence as sp
    out = []
    for f in ("blank_length_mm", "blank_width_mm"):
        v = _num(sp.value_of(part, f)) if sp.value_of(part, f) is not sp.MISSING else None
        if v is None:
            v = _num(sp.value_of(part, f"normalized_geometry.{f}")) \
                if sp.value_of(part, f"normalized_geometry.{f}") is not sp.MISSING else None
        if v is not None:
            out.append((f, v))
    return out


def _write_blank(part: Dict[str, Any], field: str, value: float) -> bool:
    """The blank lives on the part and in its geometry record; the costing reads either, so
    both carry the changed size or the two would disagree about one part."""
    import source_precedence as sp
    wrote = sp.apply_field(part, field, round(float(value), 1), SOURCE)
    if isinstance(part.get("normalized_geometry"), dict):
        sp.apply_field(part, f"normalized_geometry.{field}", round(float(value), 1), SOURCE)
    return wrote


def _apply_size(part: Dict[str, Any], change: Mapping[str, Any]
                ) -> Tuple[Optional[str], Optional[str]]:
    """(what changed, or None; why not, or None).

    THE CUSTOMER STATES A FINISHED SIZE; THE ENGINE COSTS A BLANK. The two are the same only
    where nothing is formed along that side, so the change is mapped onto the blank in two
    cases and asked in every other:

      * one side of the blank IS the old size (to the millimetre) — a flat part, or a folded
        part changed along its folds' length. The side becomes the new size, exactly.
      * no side matches, and exactly one side is the old size plus no more than a configured
        allowance for its flanges — a folded part changed across a straight span. The same
        change in mm is made to the developed side, and the book says it was done that way.

    Two candidate sides, or none, or no blank on the record at all, is a question.
    """
    frm, to = float(change["value"]["from"]), float(change["value"]["to"])
    axes = _blank_axes(part)
    if not axes:
        return None, "the part has no blank on the record to change"
    exact = [(f, v) for f, v in axes if abs(v - frm) <= 1.0]
    if len(exact) > 1:
        return None, (f"both sides of the blank are {frm:g} mm, so the change could be either "
                      f"— say which")
    allowance = float(_cfg().get("size_span_allowance_mm", 200))
    if exact:
        field, held = exact[0]
        new, how = to, "the blank side that was that size"
    else:
        near = [(f, v) for f, v in axes if frm < v <= frm + allowance]
        if len(near) != 1:
            dims = " x ".join(f"{v:g}" for _, v in axes)
            return None, (f"the blank is {dims} mm and no single side of it is the drawn "
                          f"{frm:g} mm (or that plus its flanges) — the change may be to a "
                          f"formed feature; size the blank by hand")
        field, held = near[0]
        new, how = held + (to - frm), (f"the developed side ({held:g} mm), by the same "
                                       f"{to - frm:+g} mm — exact for a straight span; check if "
                                       f"the change is to a flange or a bend")
    if new <= 0:
        return None, f"the change would leave a blank side of {new:g} mm"
    _write_blank(part, field, new)
    return (f"{LABELS[field]} {held:g} -> {new:g} mm (customer: {frm:g} -> {to:g} mm, applied "
            f"to {how})"), None


def apply_customer_changes(parts: Any, data: Mapping[str, Any],
                           summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stamp the accepted changes onto the parts and put both values on the book.

    Returns {applied, agreed, not_applied, declined, questions, order_quantity}. Every change
    lands in exactly one of the first three, so nothing the estimator ticked can vanish.
    """
    import source_precedence as sp
    from estimator_confirmed import confirmation_match_keys
    report: Dict[str, Any] = {"applied": [], "agreed": [], "not_applied": [], "declined": [],
                              "questions": 0, "order_quantity": None}
    if not isinstance(parts, Sequence) or not isinstance(data, Mapping):
        return report
    who = str(data.get("accepted_by") or "an estimator")
    when = str(data.get("accepted_on") or "")
    stamp = f"accepted by {who}" + (f", {when}" if when else "")
    drawing = (summary or {}).get("drawing_number") or \
        ((summary or {}).get("document_analysis") or {}).get("drawing_number")
    root = _root_part(parts, drawing)

    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for p in parts:
        if isinstance(p, dict):
            for key in confirmation_match_keys(p):
                by_code.setdefault(key, []).append(p)

    def _evidence(ch: Mapping[str, Any]) -> str:
        if ch.get("origin") == "email":
            return f"customer e-mail ({stamp}): \"{ch.get('quote')}\""
        return f"instruction recorded by {who}" + (f", {when}" if when else "") + \
            f" — {ch.get('reason')}"

    def _ask(issue: str, why: str, part: Optional[Dict[str, Any]] = None) -> None:
        target = part or root
        if target is not None and sp.raise_manufacturing_question(
                target, issue, f"Costed as drawn — {why}",
                "price the change by hand, or update the drawings, or correct the change and "
                "re-run", "customer_changes"):
            report["questions"] += 1

    for ch in (data.get("changes") or []):
        field, value = ch["field"], ch["value"]
        said = "customer e-mail" if ch.get("origin") == "email" else "instruction"
        if field == "order_quantity":
            report["order_quantity"] = value
            asked = (summary or {}).get("requested_order_quantity")
            try:
                differs = asked not in (None, "") and int(asked) != int(value)
            except (TypeError, ValueError):
                differs = False
            entry = {"part": "", "field": field, "to": value, "evidence": _evidence(ch)}
            if differs:
                entry["why"] = (f"the run was asked for {asked} off; the {said} asks for "
                                f"{value} off")
                report["not_applied"].append(entry)
                _ask(f"Order quantity: the {said} asks for {value} off and this run was "
                     f"costed at {asked} off. {_evidence(ch)}", entry["why"])
            else:
                report["applied"].append(entry)
            continue
        targets = by_code.get(_bare(ch["part"])) or []
        if not targets:
            entry = {"part": ch["part"], "field": field, "to": value,
                     "evidence": _evidence(ch),
                     "why": "no part of this job carries that number"}
            report["not_applied"].append(entry)
            _ask(f"{ch['part']}: the {said} changes its {LABELS[field]} to "
                 f"{describe(value, field)}, but NO part of this job carries that number — "
                 f"the change did nothing. {_evidence(ch)}", entry["why"])
            continue
        for part in targets:
            pn = str(part.get("part_number") or ch["part"])
            if field == SIZE_FIELD:
                did, why = _apply_size(part, ch)
                if did is None:
                    entry = {"part": pn, "field": field, "to": value, "evidence": _evidence(ch),
                             "why": why}
                    report["not_applied"].append(entry)
                    _ask(f"{pn}: the {said} changes a size {describe(value, field)} and it "
                         f"could not be put on the blank — {why}. {_evidence(ch)}", why, part)
                    continue
                flag = (f"{pn}: CUSTOMER CHANGE — {did}. COSTED AT THE NEW SIZE. "
                        f"{_evidence(ch)}")
                part.setdefault("review_flags", []).append(flag)
                part.setdefault("customer_changes", []).append(
                    {"field": field, "to": value, "applied": did, "evidence": _evidence(ch)})
                report["applied"].append({"part": pn, "field": field, "to": value,
                                          "applied": did, "evidence": _evidence(ch)})
                continue
            if field == "operation_off":
                offs = part.setdefault("_estimator_operations_off", [])
                if value not in offs:
                    offs.append(value)
                part.setdefault("review_flags", []).append(
                    f"{pn}: CUSTOMER CHANGE — {value.replace('_', ' ')} taken OFF the route. "
                    f"{_evidence(ch)}")
                part.setdefault("customer_changes", []).append(
                    {"field": field, "to": value, "evidence": _evidence(ch)})
                report["applied"].append({"part": pn, "field": field, "to": value,
                                          "evidence": _evidence(ch)})
                continue
            if field == "make_or_buy":
                before = part.get("_estimator_make_or_buy")
                part["_estimator_make_or_buy"] = value
                part["_estimator_make_or_buy_by"] = who
                part.setdefault("review_flags", []).append(
                    f"{pn}: CUSTOMER CHANGE — {value.upper()}"
                    + (f" (was {str(before).upper()})" if before else "")
                    + f". {_evidence(ch)}")
                part.setdefault("customer_changes", []).append(
                    {"field": field, "to": value, "evidence": _evidence(ch)})
                report["applied"].append({"part": pn, "field": field, "to": value,
                                          "evidence": _evidence(ch)})
                continue

            rec_field = PART_FIELDS[field]
            held = sp.value_of(part, rec_field)
            before = None if held is sp.MISSING else held
            if field in ("blank_length_mm", "blank_width_mm"):
                other = "blank_width_mm" if field == "blank_length_mm" else "blank_length_mm"
                if not any(f == other for f, _ in _blank_axes(part)) and not any(
                        c.get("field") == other and _bare(c.get("part")) == _bare(ch["part"])
                        for c in (data.get("changes") or [])):
                    why = (f"only the {LABELS[field]} is given and the part holds no "
                           f"{LABELS[other]} — half a blank sizes nothing")
                    report["not_applied"].append({"part": pn, "field": field, "to": value,
                                                  "evidence": _evidence(ch), "why": why})
                    _ask(f"{pn}: the {said} gives a {LABELS[field]} of "
                         f"{describe(value, field)} and no {LABELS[other]}. {_evidence(ch)}",
                         why, part)
                    continue
                wrote = _write_blank(part, field, float(value))
            else:
                wrote = sp.apply_field(part, rec_field, value, SOURCE)
            if not wrote and before is not None and _same(sp.value_of(part, rec_field),
                                                          value, field):
                part.setdefault("review_flags", []).append(
                    f"{pn}: the {said} asks for {LABELS[field]} {describe(value, field)}, which "
                    f"is what the files already say — nothing changed. {_evidence(ch)}")
                report["agreed"].append({"part": pn, "field": field, "to": value,
                                         "evidence": _evidence(ch)})
                continue
            if not wrote:
                why = f"the record refused it (held: {describe(before, field)})"
                report["not_applied"].append({"part": pn, "field": field, "to": value,
                                              "evidence": _evidence(ch), "why": why})
                _ask(f"{pn}: the {said} asks for {LABELS[field]} {describe(value, field)} and "
                     f"it could not be applied — {why}. {_evidence(ch)}", why, part)
                continue
            # AN ANSWERED QUESTION COMES OFF THE LIST, as for the answers file: a "confirm
            # which is right" about a field the customer has now settled asks nothing.
            if isinstance(part.get("review_flags"), list):
                part["review_flags"] = [f for f in part["review_flags"]
                                        if not (rec_field in str(f)
                                                and "confirm" in str(f).lower())]
            extra = f" ({ch['note']})" if ch.get("note") else ""
            part.setdefault("review_flags", []).append(
                f"{pn}: {LABELS[field]} — the drawings: {describe(before, field)}; "
                f"{said}: {describe(value, field)}{extra} — COSTED AT "
                f"{describe(value, field).upper() if field == 'finish' else describe(value, field)}"
                f". {_evidence(ch)}")
            part.setdefault("customer_changes", []).append(
                {"field": field, "from": before, "to": value, "evidence": _evidence(ch)})
            report["applied"].append({"part": pn, "field": field, "from": before, "to": value,
                                      "evidence": _evidence(ch)})

    for q in (data.get("questions") or []):
        quote = str(q.get("quote") or "").strip()
        ask = str(q.get("ask") or "").strip() or "the customer asks for something this box " \
                                                 "cannot change"
        target = None
        if q.get("part"):
            target = (by_code.get(_bare(q["part"])) or [None])[0]
        _ask(f"Customer e-mail: " + (f"\"{quote}\" — " if quote else "") + ask,
             "the e-mail asks for this and nothing on the estimate has changed for it", target)
    # A LINE OF THE FILE THAT COULD NOT BE USED IS ON THE BOOK, not only in the log: whoever
    # ticked it believes the job is costed with it.
    for prob in (data.get("problems") or []):
        _ask(f"Customer changes file: {prob}",
             "this line of the customer's changes was not applied")
    report["declined"] = [{"part": d.get("part"), "field": d.get("field"),
                           "to": d.get("value"), "quote": d.get("quote")}
                          for d in (data.get("declined") or [])]
    return report


# ── command line, for the portal: the engine's python reads the pack ────────────────────

def _main(argv: List[str]) -> int:
    if argv and argv[0] == "--read":
        paths = [a for a in argv[1:] if not a.startswith("--")]
        email = sys.stdin.read()
        index = part_index(paths)
        out = propose_changes(email, index)
        out["index"] = {"parts": index.get("parts") or [], "unread": index.get("unread") or []}
        out["vocabulary"] = vocabulary()
        print(json.dumps(out, ensure_ascii=False))
        return 0
    print("usage: customer_changes.py --read <files or folders...> < email.txt",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
