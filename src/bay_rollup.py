"""
bay_rollup.py — SDI Intelligence full-bay (assembly) estimating.

ADDITIVE layer over the per-part estimator. It does NOT change per-part costing.
Given the top-level GA's BOM (the bay parts list) plus the per-part fab estimates
already produced by estimate_document, it:

  * binds each BOM line to a cost:
      - a fabricated detail part  -> the matching per-part estimate, at BOM qty
      - a sub-assembly (-GA / -C)  -> the SUM of its costed detail parts
      - a catalogue token (FIXING*, ELECTRICS*, *TUBE*, RIVET, INSERT, ...) ->
        priced via the catalogue/bought-in pricer
  * when an assembly has no detail drawings in scope, rolls up orphan prefix
    parts (e.g. kick flat 1453-01C under 1453-GA) or falls back to a GA-BOM
    provisional blank estimate (flagged low confidence — no DXF/detail GA)
  * flags LOUDLY any line with no credible cost and contributes 0 to that line
  * adds standard template lines (packaging) that never appear on a fab drawing
  * rolls everything up to a bay total at the order quantity

Design principles carried from the per-part engine:
  * No confident wrong number. Implausible catalogue matches are rejected.
  * Provisional GA-only costs are allowed but never promoted to the headline total.
  * Cost each part once, at its BOM quantity.
  * Suppress the bay headline total when provisional / uncosted lines remain.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional

import config


# ── BOM line classification ──────────────────────────────────────────────────

_CATALOGUE_PATTERNS = [
    r"\bFIXING\d*", r"\bELECTRIC", r"\bLOOM\b", r"\bRIVET\b", r"\bINSERT\b",
    r"\bCABLE\s*TIE", r"\bGROMMET\b", r"\bSCREW\b", r"\bBOLT\b", r"\bNUT\b",
    r"\bWASHER\b", r"\bSLOTTED\s*TUBE", r"\bTUBE\d+", r"\bVINYL", r"\bSUBPLAS",
    r"\bOPAL\b", r"\bPERSPEX\b", r"\bACRYLIC\b", r"\bHIPS\b", r"\bFOAM\b",
    r"\bTAPE\b", r"\bCLIP\b", r"\bGUIDE", r"\bBOX\d*", r"\bPALLET\b",
]
_CATALOGUE_RE = re.compile("|".join(_CATALOGUE_PATTERNS), re.IGNORECASE)

_CONSUMABLE_RE = re.compile(r"\bPOWDER", re.IGNORECASE)
_ASSEMBLY_SUFFIX_RE = re.compile(r"-(GA|SA\d*)$", re.IGNORECASE)
_WELDMENT_PARENT_RE = re.compile(r"-101$", re.IGNORECASE)
_CATALOGUE_BOM_ROW_RE = re.compile(
    r"\b(\d+)\s+(ELECTRICS(?:[-\s][A-Z0-9]+)?|FIXING\s*\d+|SLOTTEDTUBE\s*\d+|VINYL\s*\d+|SUBPLAS\s*\d+|POWDER\s*\d+)\s+(.+?)\s+(\d+)\b",
    re.IGNORECASE,
)
_JUNK_ESTIMATE_CODES = frozenset({"C-001"})


def _norm_code(raw: Any) -> str:
    try:
        from part_identity import normalize_part_code

        return normalize_part_code(raw)
    except Exception:
        s = str(raw or "").strip().upper()
        if not s:
            return ""
        token = s.split()[0]
        token = re.sub(r"[^A-Z0-9\-]", "", token)
        return token


def _assembly_base(code: str) -> str:
    return _ASSEMBLY_SUFFIX_RE.sub("", code)


def classify_bom_line(code: str, description: str) -> str:
    blob = f"{code} {description}".upper()
    if _CONSUMABLE_RE.search(blob):
        return "consumable"
    if _CATALOGUE_RE.search(blob):
        return "catalogue"
    if code and code[0].isdigit():
        return "assembly" if _ASSEMBLY_SUFFIX_RE.search(code) else "detail"
    if code and code[0].isalpha():
        return "catalogue"
    return "detail"


# ── Field access (defensive: BOM rows vary by extractor) ─────────────────────

def _row_code(row: Dict[str, Any]) -> str:
    for k in ("part_number", "part_code", "code", "item", "description"):
        v = row.get(k)
        if v:
            c = _norm_code(v)
            if c:
                return c
    return ""


def _row_description(row: Dict[str, Any]) -> str:
    return str(row.get("description") or row.get("desc") or row.get("part_number") or "").strip()


def _row_qty(row: Dict[str, Any]) -> float:
    for k in ("quantity", "qty", "qty_per_bay", "qty_per_unit"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                continue
    return 1.0


def _row_parent(row: Dict[str, Any]) -> str:
    """WHICH ASSEMBLY THIS LINE BELONGS TO, as the reader recorded it — "" when unrecorded.

    A BOM line is not a part. It is the statement "this assembly uses N of that part", and
    the same part under two assemblies is two lines with two quantities and two owners.
    bom_pipeline knows this and says so in its own docstring: it deliberately does not
    deduplicate, "the same code legitimately recurs across parent BOMs", and it stamps every
    row with the parent page it came from.

    Nothing downstream ever read that field. Job 12392 is one enquiry with two GAs — 02 with
    16 M4x8 fixings, 04 with 4 more — and a dedupe keyed on the part number alone kept one
    FIXING line and dropped the other, along with its parent edge and its quantity. The
    reader had the tree; the merge threw it away.

    source_pdf is accepted as the fallback because the folder merge stamps it on every row,
    so even a reader that records no page label still distinguishes two drawings.
    """
    for key in ("bom_parent", "parent", "parent_code", "source_pdf"):
        v = str(row.get(key) or "").strip()
        if v:
            return v.upper()
    return ""


def _same_thing(a: str, b: str) -> bool:
    """Could these two descriptions be the same BOM line read twice?

    ONE PARENT CAN LIST A CODE TWICE. 12392-04-GA carries FIXING M4x8 and FIXING M4x10 —
    generic code, two different bolts, two quantities. Keyed on (parent, code) the second
    line vanished, which is the same loss the part-number key used to cause, one level in.

    But description cannot simply join the key either: the readers spell one line several
    ways. A deterministic table reads "SCREW" where vision reads "BUTTON HEAD SCREW M4x8",
    and keying on the text would split a single line into two and count the fastener twice.

    So the test is CONTAINMENT, not equality. One description that contains the other is one
    line described at two lengths; two that name different things — M4x8 and M4x10 — are two
    lines. An empty description tells us nothing and cannot be used to split, so it merges.
    """
    x, y = _norm_desc(a), _norm_desc(b)
    if not x or not y:
        return True
    return x in y or y in x


def _norm_desc(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _est_code(est: Dict[str, Any]) -> str:
    return _norm_code(est.get("part_number") or est.get("item_number") or "")


def _est_unit_cost(est: Dict[str, Any]) -> Optional[float]:
    for k in ("unit_total_cost_gbp", "unit_cost_gbp", "total_unit_cost_gbp"):
        v = est.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _est_is_provisional(est: Dict[str, Any]) -> bool:
    ds = est.get("data_sufficiency") or {}
    if ds.get("status") == "insufficient_data":
        return True
    if est.get("geometry_inferred"):
        return True
    flags = est.get("review_flags") or []
    markers = (
        "geometry_inferred_provisional",
        "no_geometry",
        "provisional",
        "insufficient_data",
    )
    for f in flags:
        fs = str(f).lower()
        if any(m in fs for m in markers):
            return True
    basis = str((est.get("cost_breakdown") or {}).get("costing_basis") or "").lower()
    return "provisional" in basis or "inferred" in basis


def _line_confidence(*, provisional: bool) -> str:
    return "low" if provisional else "high"


def _numeric_prefix(code: str) -> str:
    m = re.match(r"^(\d+)", code or "")
    return m.group(1) if m else ""


def provisional_cost_from_ga_bom(description: str) -> Optional[Dict[str, Any]]:
    """Infer a rough unit cost from the GA BOM description when no detail set exists."""
    try:
        from geometry_inference import provisional_blank_from_description
    except Exception:
        return None
    blank = provisional_blank_from_description(description)
    if not blank:
        return None
    uc = _rough_fab_unit_cost_gbp(blank["length_mm"], blank["width_mm"])
    return {
        "unit_cost_gbp": uc,
        "source": "ga_bom_provisional",
        "confidence": float(getattr(__import__("config"), "JACCARD_MIN_SCORE", 0.35)),
        "inference_basis": blank.get("basis") or "category_default",
        "family": blank.get("family"),
        "blank_mm": (blank["length_mm"], blank["width_mm"]),
        "note": (
            f"Provisional from GA BOM description ({blank.get('family') or 'typical'} blank) — "
            "no detail drawing/DXF in scope; verify dimensions"
        ),
    }


def _rough_fab_unit_cost_gbp(length_mm: float, width_mm: float, *, thickness_mm: float = 1.5) -> float:
    """Conservative GA-only blank estimate — material + basic laser, not a quote."""
    area_m2 = max(0.0, length_mm * width_mm) / 1_000_000.0
    material = area_m2 * 7.85 * thickness_mm * 4.0
    laser = area_m2 * 15.0
    return round(material + laser + 2.0, 2)


# Keywords that identify a BOM line as a bought-in item
_BOUGHT_IN_KW_RE = re.compile(
    # Code-bearing tokens first (capture the number with the stem): FIXING5, FIXING 236,
    # ELECTRICS, SUBPLAS72, VINYL03, SLOTTEDTUBE01. Then bare keywords as a fallback anchor.
    r"\b("
    r"FIXING\s*\d+|ELEC(?:TRIC)?S?\b|SUBPLAS\s*\d*|VINYL\s*\d*|SLOTTEDTUBE\s*\d*|"
    r"FIXING|LOOM|RIVET|INSERT|SCREW|BOLT|NUTSERT|NUT|WASHER|GROMMET|"
    r"CLIP|GUIDE|CASTOR|HINGE|LOCK|HANDLE|GLIDE|CABLE|FOAM|TAPE|"
    r"OPAL|HIPS|ACRYLIC|PERSPEX|BUSH|CLINCH|STUD|PEM|BUNG|DOWEL|SPRING|MAGNET|HOOK|BRACKET"
    r")\b",
    re.IGNORECASE,
)

# Loose BOM row scanner — item_no + code/description token + description + qty
# Handles: "4  FIXING 236  M8 FLANGED NUTSERT  2"
#          "3  ELECTRICS  50cm LOOM LIGHTING ELECTRICS  1"
_LOOSE_BOM_ROW_RE = re.compile(
    r"^\s*(\d{1,3})\s+"           # item number
    r"([A-Z][A-Z0-9./_ -]{1,40}?)"  # code/description token (loose)
    r"\s{2,}"                        # 2+ spaces separating code from description
    r"(.+?)"                         # rest of description
    r"\s+(\d{1,3})\s*$",          # qty at end of line
    re.IGNORECASE | re.MULTILINE,
)

# Tube section+length BOM pattern:
# "1  1  30 x 60 x 1.50mm TUBE  1125" or "30 x 60 x 1.5 TUBE 1125"
_TUBE_SECTION_RE = re.compile(
    r"\b(?:(\d+)\s+)?(\d+)\s*[xX]\s*(\d+)\s*[xX]\s*([\d.]+)\s*(?:mm)?\s*(?:ERW\s*)?(?:RECT\.?\s*)?(?:RHS\s*)?TUBE\b.{0,10}?(\d{3,4})\b",
    re.IGNORECASE,
)


# ── reaching UDEF ───────────────────────────────────────────────────────────────────
# BOTH LOOKUPS BELOW HAVE NEVER RETURNED A PRICE. They opened with
#     cs = _cfg.SQL_CONNECTION_STRING
# and config has never defined that name on any branch, so the first statement inside each
# try raised AttributeError, `except Exception: pass` swallowed it, and both returned None.
# From the caller that is indistinguishable from "UDEF holds no match for this line" — so
# every bought-in and every tube that came through bay_rollup went unpriced, on every job,
# for as long as the code has existed, and the console said nothing.
#
# Two changes, and the second matters more than the first: the connection now comes from
# config.get_connection(), the one place that knows how to reach SDILive; and a failure SAYS
# SO instead of passing. A pricing source that is switched off must never be indistinguishable
# from a pricing source that was asked and had no answer.
_UDEF_SAID = set()


def _udef_unreachable(what: str, exc: BaseException) -> None:
    """Say it once per kind of lookup. Per-part would print thousands of times on one job."""
    key = (what, type(exc).__name__)
    if key in _UDEF_SAID:
        return
    _UDEF_SAID.add(key)
    print(f"   [bay-rollup] UDEF {what} unavailable ({type(exc).__name__}: {exc}) — "
          f"lines it would have priced are left for the estimator, not priced at zero.",
          flush=True)


class _udef_connection:
    """config.get_connection() as a context manager that CLOSES.

    pyodbc's own `with` manages the transaction and leaves the connection open, which is what
    the previous code used; on a folder job with many bought-in lines that is one live SQL
    connection per line held until garbage collection.
    """

    def __init__(self, cfg):
        self._cfg = cfg
        self._cn = None

    def __enter__(self):
        timeout = int(getattr(self._cfg, "SQL_TIMEOUT_UDEF_SEC", 6))
        self._cn = self._cfg.get_connection(timeout=timeout)
        return self._cn

    def __exit__(self, *_exc):
        try:
            self._cn.close()
        except Exception:
            pass
        return False


def _udef_fuzzy_lookup(full_line: str, code_hint: str) -> Optional[Dict[str, Any]]:
    """Find a UDEF row for a loosely-identified bought-in line.

    Strategy, in order of confidence:
      1. Exact part-code match on the normalised code hint (e.g. FIXING236).
      2. Prefix match — drawing 'ELECTRICS' against UDEF codes starting 'ELEC'.
      3. Description token match — the 2-3 most distinctive words from the drawing
         line (e.g. '50CM', 'LOOM') matched against UDEF [Description].

    UDEF (20k rows, 15k priced) does the heavy lifting; the scanner only has to
    decide a line is PROBABLY bought-in. Returns {code, description,
    unit_cost_gbp, supplier_name} or None."""
    try:
        import config as _cfg
        line_u = str(full_line or "").upper()
        code_u = str(code_hint or "").upper().strip()

        with _udef_connection(_cfg) as cn:
            cur = cn.cursor()

            # 1. Exact code match
            if code_u:
                cur.execute(
                    """SELECT TOP 1 [Part code], [Description], [System cost per], [Supplier name]
                       FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                       WHERE [System cost per] > 0 AND UPPER(REPLACE([Part code],' ','')) = ?""",
                    (code_u.replace(" ", ""),),
                )
                row = cur.fetchone()
                if row:
                    return {"code": (row[0] or "").strip(), "description": (row[1] or "").strip(),
                            "unit_cost_gbp": float(row[2] or 0.0), "supplier_name": (row[3] or "").strip()}

            # 2. Prefix bridge — common where the drawing word is longer than the UDEF code stem.
            #    ELECTRICS -> ELEC, FIXINGS -> FIXING. Take the leading alpha run, min 4 chars.
            import re as _re
            alpha = _re.match(r"([A-Z]+)", code_u)
            if alpha and len(alpha.group(1)) >= 4:
                stem = alpha.group(1)[:4]   # ELEC, FIXI, SLOT, VINY, SUBP
                # pull any distinctive size/spec tokens from the line: 50CM, 4.0X10, M8 etc.
                tokens = _re.findall(r"\b(\d+(?:\.\d+)?(?:CM|MM|X\d+)?|M\d+)\b", line_u)
                like_clauses = " AND ".join("[Description] LIKE ?" for _ in tokens[:2])
                params = [f"{stem}%"] + [f"%{t}%" for t in tokens[:2]]
                sql = ("""SELECT TOP 1 [Part code], [Description], [System cost per], [Supplier name]
                          FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                          WHERE [System cost per] > 0 AND [Part code] LIKE ?""")
                if like_clauses:
                    sql += " AND " + like_clauses
                cur.execute(sql, params)
                row = cur.fetchone()
                if row:
                    return {"code": (row[0] or "").strip(), "description": (row[1] or "").strip(),
                            "unit_cost_gbp": float(row[2] or 0.0), "supplier_name": (row[3] or "").strip()}

            # 3. Description token match — distinctive words from the line, ignore filler.
            stop = {"THE","AND","FOR","TO","OF","A","X","MM","CM","WITH","LIGHTING","DOME"}
            words = [w for w in _re.findall(r"[A-Z0-9.]+", line_u)
                     if len(w) >= 3 and w not in stop]
            words = words[:3]
            if len(words) >= 2:
                like = " AND ".join("[Description] LIKE ?" for _ in words)
                cur.execute(
                    f"""SELECT TOP 1 [Part code], [Description], [System cost per], [Supplier name]
                        FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                        WHERE [System cost per] > 0 AND {like}
                        ORDER BY LEN([Description])""",
                    [f"%{w}%" for w in words],
                )
                row = cur.fetchone()
                if row:
                    return {"code": (row[0] or "").strip(), "description": (row[1] or "").strip(),
                            "unit_cost_gbp": float(row[2] or 0.0), "supplier_name": (row[3] or "").strip()}
    except Exception as exc:
        _udef_unreachable("bought-in lookup", exc)
    return None


def _lookup_tube_udef(w_mm: float, h_mm: float, t_mm: float, length_mm: int) -> Optional[Dict[str, Any]]:
    """Query UDEF for a slotted tube matching section (w×h×t) and length.
    Returns {code, description, unit_cost_gbp, supplier_name} or None."""
    try:
        import config as _cfg
        with _udef_connection(_cfg) as cn:
            cur = cn.cursor()
            # Tube stock in UDEF is keyed by SECTION (e.g. 60x30x1.5), not cut length —
            # length is a cut spec, so do NOT require it in the description. Match on the
            # two section dimensions in either orientation; the thickness narrows it further.
            wi, hi, ti = int(round(w_mm)), int(round(h_mm)), t_mm
            cur.execute(
                """SELECT TOP 5 [Part code], [Description], [System cost per], [Supplier name]
                   FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                   WHERE [System cost per] > 0
                     AND [Part code] LIKE 'SLOTTEDTUBE%'
                     AND (
                       ([Description] LIKE ? AND [Description] LIKE ?)
                       OR ([Description] LIKE ? AND [Description] LIKE ?)
                     )
                   ORDER BY LEN([Description])""",
                (f"%{wi}%", f"%{hi}%",
                 f"%{hi}%", f"%{wi}%"),
            )
            row = cur.fetchone()
            # Fallback: if section text didn't match, take the cheapest priced slotted tube
            # so the line is at least costed and flagged for review, not silently dropped.
            if not row:
                cur.execute(
                    """SELECT TOP 1 [Part code], [Description], [System cost per], [Supplier name]
                       FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                       WHERE [System cost per] > 0 AND [Part code] LIKE 'SLOTTEDTUBE%'
                       ORDER BY [System cost per]"""
                )
                row = cur.fetchone()
            if row:
                return {
                    "code": (row[0] or "").strip(),
                    "description": (row[1] or "").strip(),
                    "unit_cost_gbp": float(row[2] or 0.0),
                    "supplier_name": (row[3] or "").strip(),
                }
    except Exception as exc:
        _udef_unreachable("tube lookup", exc)
    return None


def extract_catalogue_bom_rows_from_pages(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse bought-in tokens from assembly page text (ELECTRICS, FIXING*, TUBE etc.)."""
    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for page in summary.get("pages") or []:
        text = f"{page.get('normalized_text') or ''} {page.get('pdfplumber_text') or ''}"

        # ── Standard catalogue tokens (ELECTRICS, FIXING*, SLOTTEDTUBE*, VINYL* etc.) ──
        for match in _CATALOGUE_BOM_ROW_RE.finditer(text):
            item_no, code_raw, desc, qty_raw = match.groups()
            try:
                from part_identity import split_catalogue_token
                code = _norm_code(split_catalogue_token(code_raw))
            except Exception:
                code = _norm_code(code_raw)
            if not code or code in seen:
                continue
            seen.add(code)
            try:
                qty = max(1, int(qty_raw))
            except (TypeError, ValueError):
                qty = 1
            # Price it via UDEF here — otherwise it lands unpriced and falls to a default,
            # AND blocks the keyword scanner (Tier 2) from creating a priced version because
            # the code is now in `seen`. Look the code/description up in UDEF immediately.
            udef = _udef_fuzzy_lookup(f"{code_raw} {desc}".strip(), code)
            row = {
                "item_number": item_no,
                "part_number": _norm_code(udef["code"]) if udef else code,
                "description": (udef["description"] if udef else desc.strip()) or desc.strip(),
                "quantity": qty,
            }
            if udef:
                row["source"] = "assembly_text_catalogue_udef"
                row["unit_cost_gbp"] = udef["unit_cost_gbp"]
                row["supplier"] = udef["supplier_name"]
                # If UDEF resolved to a different canonical code, reserve it too.
                if row["part_number"] != code:
                    seen.add(row["part_number"])
            else:
                row["source"] = "assembly_text_catalogue"
            rows.append(row)

        # ── Tier 2: Keyword-anchored bought-in scanner ──
        # PDF BOM tables come through pdfplumber as ONE concatenated run, not line by line
        # (e.g. "...3 ELECTRICS 50cm LOOM LIGHTING ELECTRICS 1 A 4 FIXING5 4.0x10mm DOME RIVET 2").
        # So a line-anchored (^...$) regex never matches. Instead: find each bought-in KEYWORD,
        # take the code token at the keyword (ELECTRICS, FIXING5, "FIXING 236" -> FIXING236),
        # grab a short description window after it, and let UDEF do the matching.
        for km in _BOUGHT_IN_KW_RE.finditer(text):
            kw = km.group(0).strip()
            # Build the code from the keyword: collapse "FIXING 236" -> "FIXING236", upper.
            code_l = _norm_code(re.sub(r"([A-Z]+)\s+(\d+)", r"\1\2", kw.upper()))
            if not code_l or code_l in seen:
                continue
            # Skip pure descriptive keywords with no code suffix that are too generic to
            # match a single UDEF row on their own (LOOM, RIVET, NUTSERT, GLIDE) — these
            # are caught as part of their parent code line (FIXING5, FIXING236, ELECTRICS).
            if code_l in {"LOOM", "RIVET", "NUTSERT", "GLIDE", "INSERT", "WASHER",
                          "SCREW", "BOLT", "CLIP", "CABLE", "FOAM", "TAPE", "BUSH",
                          "GROMMET", "CASTOR", "HINGE", "HANDLE", "SLOTTED"}:
                continue
            # Description window: from the keyword to the next ~40 chars (the spec text).
            desc_window = text[km.start(): km.start() + 60].strip()
            udef = _udef_fuzzy_lookup(desc_window, code_l)
            if not udef:
                continue
            final_code = _norm_code(udef["code"]) or code_l
            if final_code in seen:
                continue
            seen.add(final_code)
            # Quantity: look for a small integer right after the description window.
            qty_l = 1
            qm = re.search(r"\b(\d{1,2})\b", text[km.end(): km.end() + 50])
            if qm:
                try:
                    qty_l = max(1, min(int(qm.group(1)), 50))
                except (TypeError, ValueError):
                    qty_l = 1
            rows.append({
                "item_number": None,
                "part_number": final_code,
                "description": udef["description"] or desc_window,
                "quantity": qty_l,
                "source": "loose_bom_scanner_udef",
                "unit_cost_gbp": udef["unit_cost_gbp"],
                "supplier": udef["supplier_name"],
            })

        # ── Tier 3: Tube section+length pattern: "30 x 60 x 1.5mm TUBE 1125" ──
        for m in _TUBE_SECTION_RE.finditer(text):
            qty_raw, d1, d2, thick, length_raw = m.groups()
            try:
                d1f, d2f, tf, lf = float(d1), float(d2), float(thick), int(length_raw)
            except (TypeError, ValueError):
                continue
            # UDEF stores as 60x30 — try both orientations
            udef = _lookup_tube_udef(d1f, d2f, tf, lf) or _lookup_tube_udef(d2f, d1f, tf, lf)
            if not udef:
                continue
            code = _norm_code(udef["code"])
            if not code or code in seen:
                continue
            seen.add(code)
            qty = max(1, int(qty_raw)) if qty_raw else 1
            rows.append({
                "item_number": "",
                "part_number": code,
                "description": udef["description"],
                "quantity": qty,
                "source": "tube_section_length_udef",
                "unit_cost_gbp": udef["unit_cost_gbp"],
                "supplier": udef["supplier_name"],
            })
    return rows


_BOM_SOURCE_PRIORITY = {
    "bay_bom": 0,
    "bay_bom_stitch": 1,
    "loose_bom_scanner_udef": 2,   # carries a verified UDEF price + supplier — prefer it
    "tube_section_length_udef": 2, # tube matched to SLOTTEDTUBE* with a price
    "assembly_text_catalogue_udef": 2,  # catalogue token that resolved + priced in UDEF
    "document_analysis": 3,
    "assembly_text_catalogue": 4,  # plain token, no price yet — lowest of the real sources
    "folder_job_synthesized": 9,
}


def _assembly_child_codes(code: str, available: Iterable[str]) -> List[str]:
    """Detail part codes that a GA / assembly BOM line rolls up."""
    code = _norm_code(code)
    if not code:
        return []
    base = _assembly_base(code)
    prefix = _numeric_prefix(base or code)
    out: List[str] = []
    for raw in available:
        c = _norm_code(raw)
        if not c or c == code:
            continue
        if c.startswith(code + "-") or c == base or (base and c.startswith(base + "-")):
            if not _ASSEMBLY_SUFFIX_RE.search(c):
                out.append(c)
            continue
        if prefix and c.startswith(prefix + "-") and "-GA" not in c[5:]:
            if not _ASSEMBLY_SUFFIX_RE.search(c):
                out.append(c)
    return out


def codes_shadowed_by_parent_bom(bom_rows: List[Dict[str, Any]], est_codes: Iterable[str]) -> set:
    """Detail codes already costed via a parent GA / assembly BOM row — skip duplicate lines."""
    est_list = [_norm_code(c) for c in est_codes if _norm_code(c)]
    est_set = set(est_list)
    shadowed: set = set()
    for row in bom_rows:
        code = _row_code(row)
        if not code:
            continue
        desc = _row_description(row)
        kind = classify_bom_line(code, desc)
        if kind in ("catalogue", "consumable"):
            continue
        resolved = None
        try:
            from part_identity import resolve_estimate_code

            resolved = resolve_estimate_code(code, desc, est_list)
        except Exception:
            pass
        if resolved:
            shadowed.add(_norm_code(resolved))
            continue
        if _ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly":
            shadowed.update(_assembly_child_codes(code, est_set))
    return shadowed


def dedupe_bom_rows_for_bay_rollup(
    bom_rows: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One BOM row per LINE — (parent, code) — dropping synthesized rows already on a GA line.

    This was one row per part CODE, which is the same thing only while a job has a single
    assembly. Give it two GAs from one enquiry and it silently keeps whichever fixing line
    it met first; give it one GA whose sub-assemblies each use the same fastener and it does
    the same thing inside a single drawing. Both are ordinary, and both lost a real line, a
    real quantity and a real parent edge with nothing said.

    SPLITTING REQUIRES POSITIVE EVIDENCE, which is what makes this safe to turn on
    everywhere. Two rows become two lines only where the readers RECORDED two different
    parents. A row whose parent is unrecorded cannot be shown to be a separate line, so it
    collapses onto the code exactly as before — which means a job carrying no parent
    evidence at all behaves identically to the old code, by construction rather than by a
    flag. The change can add a line only where the drawing said there was one.
    """
    est_codes = {_est_code(e) for e in part_estimates if _est_code(e)}
    shadowed = codes_shadowed_by_parent_bom(bom_rows, est_codes)

    # Which codes were seen under a NAMED parent, and which parents. Collected first because
    # the floating rows below need to know whether a code has any parented line at all.
    parents_by_code: Dict[str, set] = {}
    for row in bom_rows:
        code, parent = _row_code(row), _row_parent(row)
        if code and parent:
            parents_by_code.setdefault(code, set()).add(parent)

    by_line: Dict[tuple, Dict[str, Any]] = {}
    for row in bom_rows:
        code = _row_code(row)
        if not code:
            continue
        if row.get("source") == "folder_job_synthesized" and code in shadowed:
            continue
        parent = _row_parent(row)
        # AN UNPARENTED ROW IS NOT A SECOND LINE. Where the code already has parented lines,
        # this row is the same part read by something that did not record an owner — a
        # catalogue scan, a synthesized fallback. Keying it on "" would emit it alongside
        # the real lines and count the part twice, so it joins the first parent instead and
        # is settled by source priority like any other duplicate.
        if not parent:
            known = parents_by_code.get(code)
            parent = sorted(known)[0] if known else ""
        # ONE PARENT CAN LIST A CODE TWICE — see _same_thing. The key is (code, parent) plus
        # an occurrence number, assigned by walking the lines already kept under that pair
        # and joining the first one this could BE. Where it could be none of them it is a new
        # line, so FIXING M4x8 and FIXING M4x10 under one GA stay two orders of two bolts.
        pri = _BOM_SOURCE_PRIORITY.get(str(row.get("source") or ""), 5)
        desc = _row_description(row)
        key = None
        for seen, kept in by_line.items():
            if seen[0] == code and seen[1] == parent and _same_thing(desc, _row_description(kept)):
                key = seen
                break
        if key is None:
            key = (code, parent, sum(1 for k in by_line if k[0] == code and k[1] == parent))
        prev = by_line.get(key)
        if prev is None or pri < _BOM_SOURCE_PRIORITY.get(str(prev.get("source") or ""), 5):
            by_line[key] = row

    # SAY WHEN A CODE IS OWNED TWICE. Downstream readers key on the part number in several
    # places, so a code with two lines is a shape they have not had to handle before; if one
    # of them collapses them again this is the sentence that makes the difference visible.
    _multi = {c: sorted(p) for c, p in parents_by_code.items() if len(p) > 1}
    if _multi:
        for _code, _parents in sorted(_multi.items()):
            print(f"   [bom] '{_code}' is used by {len(_parents)} assemblies "
                  f"({', '.join(_parents)}) — kept as separate lines", flush=True)

    return list(by_line.values())


def dedupe_weldment_parent_rows(bom_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop weldment parent (-101) when its detail children are also BOM lines."""
    codes = {_row_code(r) for r in bom_rows if _row_code(r)}
    drop: set = set()
    for code in codes:
        if not _WELDMENT_PARENT_RE.search(code):
            continue
        prefix = _WELDMENT_PARENT_RE.sub("", code)
        children = [
            c
            for c in codes
            if c.startswith(prefix + "-") and c != code and not _WELDMENT_PARENT_RE.search(c)
        ]
        if children:
            drop.add(code)
    return [r for r in bom_rows if _row_code(r) not in drop]


def synthesize_folder_job_bom_rows(
    summary: Dict[str, Any],
    part_estimates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build a job-level bay BOM when the folder has no top-level 1282-GA PDF."""
    rows = [dict(r) for r in (summary.get("document_analysis") or {}).get("bom_rows") or []]
    try:
        from part_identity import inject_missing_bay_rows

        rows = inject_missing_bay_rows(rows, summary)
    except Exception:
        pass
    existing = {_row_code(r) for r in rows if _row_code(r)}

    for est in part_estimates:
        code = _est_code(est)
        if not code or code in existing or code in _JUNK_ESTIMATE_CODES:
            continue
        try:
            from part_identity import dxf_alias_target

            alias = dxf_alias_target(code)
            if alias and _norm_code(alias) in existing:
                continue
        except Exception:
            pass
        if not code[0].isdigit():
            continue
        desc = str(est.get("description") or code)
        if classify_bom_line(code, desc) == "catalogue":
            continue
        rows.append(
            {
                "part_number": code,
                "description": desc,
                "quantity": est.get("quantity") or 1,
                "source": "folder_job_synthesized",
            }
        )
        existing.add(code)

    for row in extract_catalogue_bom_rows_from_pages(summary):
        code = _row_code(row)
        if code and code not in existing:
            rows.append(row)
            existing.add(code)

    rows = dedupe_weldment_parent_rows(rows)
    return dedupe_bom_rows_for_bay_rollup(rows, part_estimates)


def job_has_costing_root(bom_rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> bool:
    for row in bom_rows:
        pn = str(row.get("part_number") or "").upper()
        if re.search(r"\b1282\b", pn) and "-GA" in pn:
            return True
    codes = {_row_code(r) for r in bom_rows}
    return "1449-01C" in codes and "1450-01C" in codes


# ── Rollup ───────────────────────────────────────────────────────────────────

def _packaging_and_delivery_estimate(order_qty: int) -> Dict[str, Any]:
    """E1: per-bay packaging + delivery from PACKAGING_CONFIG. Stays flagged-not-costed
    until the warehouse throughput numbers (bays per box/pallet/delivery) are filled in.
    Config-driven so every future job inherits it; never invents a number."""
    cfg = getattr(config, "PACKAGING_CONFIG", {}) or {}
    box = cfg.get("box", {}) or {}
    pallet = cfg.get("pallet", {}) or {}
    per_box, per_pallet, per_del = cfg.get("bays_per_box"), cfg.get("bays_per_pallet"), cfg.get("bays_per_delivery")
    missing, box_c, pal_c, del_c = [], 0.0, 0.0, 0.0
    if per_box and box.get("price_gbp"):
        box_c = float(box["price_gbp"]) / float(per_box)
    else:
        missing.append("bays_per_box")
    if per_pallet and pallet.get("price_gbp"):
        pal_c = float(pallet["price_gbp"]) / float(per_pallet)
    else:
        missing.append("bays_per_pallet")
    if per_del and cfg.get("delivery_price_gbp"):
        del_c = float(cfg["delivery_price_gbp"]) / float(per_del)
    else:
        missing.append("bays_per_delivery")
    costed = not missing
    return {
        "packaging_cost_per_bay_gbp": round(box_c + pal_c + del_c, 2) if costed else None,
        "box_share_gbp": round(box_c, 2),
        "pallet_share_gbp": round(pal_c, 2),
        "delivery_share_gbp": round(del_c, 2),
        "costed": costed,
        "flag": None if costed else "PACKAGING NOT COSTED — confirm: " + ", ".join(missing),
    }


def build_bay_estimate(
    bom_rows: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
    *,
    order_quantity: int = 1,
    catalogue_pricer: Optional[Callable[[str, str], Optional[Dict[str, Any]]]] = None,
    packaging_lines: Optional[List[Dict[str, Any]]] = None,
    data_sufficiency_floor: float = 0.60,
    allow_ga_provisional: bool = True,
) -> Dict[str, Any]:
    order_qty = max(1, int(order_quantity or 1))
    bom_rows = dedupe_bom_rows_for_bay_rollup(bom_rows, part_estimates)

    est_by_code: Dict[str, Dict[str, Any]] = {}
    for e in part_estimates:
        c = _est_code(e)
        if c:
            est_by_code.setdefault(c, e)

    claimed_exact: set = set()
    for row in bom_rows:
        c = _row_code(row)
        if c and classify_bom_line(c, _row_description(row)) != "catalogue" and c in est_by_code:
            claimed_exact.add(c)

    bound_detail_codes: set = set()
    shadowed_details = codes_shadowed_by_parent_bom(bom_rows, est_by_code.keys())
    lines: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []

    def _flag(severity: str, code: str, detail: str):
        flags.append({"severity": severity, "line": code, "detail": detail})

    def _apply_cost(
        line: Dict[str, Any],
        *,
        uc: float,
        qty: float,
        source: str,
        provisional: bool,
        extra: Optional[Dict[str, Any]] = None,
    ):
        line.update(
            unit_cost_gbp=round(uc, 2),
            line_cost_gbp=round(uc * qty, 2),
            cost_source=source,
            costed=True,
            cost_confidence=_line_confidence(provisional=provisional),
            provisional=provisional,
        )
        if extra:
            line.update(extra)

    for row in bom_rows:
        code = _row_code(row)
        desc = _row_description(row)
        qty = _row_qty(row)
        if not code:
            continue
        if code in shadowed_details:
            continue
        kind = classify_bom_line(code, desc)

        line: Dict[str, Any] = {
            "code": code,
            "description": desc,
            "qty_per_bay": qty,
            "kind": kind,
            "unit_cost_gbp": None,
            "line_cost_gbp": 0.0,
            "cost_source": None,
            "costed": False,
            "cost_confidence": None,
            "provisional": False,
        }

        if kind == "consumable":
            _flag(
                "info",
                code,
                f"'{desc}' is a per-part consumable (powder) — already costed in the part "
                f"estimate; not re-added as a BOM line",
            )
            line["cost_source"] = "consumable_per_part"
            lines.append(line)
            continue

        if kind == "catalogue":
            priced = None
            # The Tier 2/3 loose scanner (FIXING236, ELECTRICS, tube) may already have
            # resolved this line against UDEF and attached unit_cost_gbp + supplier to the
            # row. Trust that first — it found the row via fuzzy/prefix matching the plain
            # catalogue_pricer can't do. Only fall back to the pricer if the row has no cost.
            _row_uc = row.get("unit_cost_gbp")
            if _row_uc is not None:
                try:
                    _row_uc_f = float(_row_uc)
                except (TypeError, ValueError):
                    _row_uc_f = None
                if _row_uc_f and _row_uc_f > 0:
                    priced = {
                        "unit_cost_gbp": _row_uc_f,
                        "source": row.get("source") or "loose_bom_scanner_udef",
                        "matched_part_code": row.get("part_number"),
                    }
            if priced is None and catalogue_pricer:
                priced = catalogue_pricer(code, desc)
                if not (priced and priced.get("unit_cost_gbp") is not None):
                    try:
                        from part_identity import catalogue_search_descriptions

                        for variant in catalogue_search_descriptions(code, desc)[1:]:
                            priced = catalogue_pricer(code, variant)
                            if priced and priced.get("unit_cost_gbp") is not None:
                                break
                    except Exception:
                        pass
            if priced and priced.get("unit_cost_gbp") is not None:
                uc = float(priced["unit_cost_gbp"])
                _apply_cost(
                    line,
                    uc=uc,
                    qty=qty,
                    source=priced.get("source") or "catalogue",
                    provisional=False,
                    extra={"matched_part_code": priced.get("matched_part_code")},
                )
            else:
                reason = (priced or {}).get("reason") or "no parts-DB match"
                _flag("warning", code, f"catalogue token '{desc}' not priced ({reason}) — price manually")
                line["cost_source"] = (priced or {}).get("source") or "catalogue_unpriced"

        else:
            try:
                from part_identity import resolve_estimate_code

                resolved = resolve_estimate_code(code, desc, est_by_code.keys())
            except Exception:
                resolved = None
            # Multi-child GA: roll up all shadowed detail estimates on the parent line.
            if resolved and (_ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly"):
                if len(_assembly_child_codes(code, est_by_code.keys())) > 1:
                    resolved = None
            if resolved and resolved in est_by_code:
                code = resolved
                line["code"] = code

            # An assembly (GA suffix / kind=assembly) may ALSO have its own part_estimate —
            # but that self-estimate is the provisional GA-page record (low reliability, a
            # rough blank guess), NOT the real cost. If the assembly has costed DETAIL children
            # available, their summed real DXF-based cost is the truth. Prefer that over the
            # provisional self-estimate. Without this, e.g. 1448-GA was costed at its provisional
            # £4.98 instead of summing 1448-01 (£2.23) + 1448-02 (£1.50), under-counting the bay.
            _is_assembly_code = bool(_ASSEMBLY_SUFFIX_RE.search(code)) or kind == "assembly"
            _child_sum = None
            if _is_assembly_code:
                _base = _assembly_base(code)
                _prefix = _numeric_prefix(_base or code)

                def _is_real_child(c: str) -> bool:
                    if c in claimed_exact or c in bound_detail_codes:
                        return False
                    if c == code or _ASSEMBLY_SUFFIX_RE.search(c):
                        return False  # don't fold one assembly into another
                    if c.startswith(code + "-") or c == _base or (_base and c.startswith(_base + "-")):
                        return True
                    if _prefix and c.startswith(_prefix + "-"):
                        return True
                    return False

                _kids = [(c, e) for c, e in est_by_code.items() if _is_real_child(c)]
                # Only override the self-estimate when EVERY child is properly costed (>0);
                # a partial sum would under-count worse than the provisional. Require >=1 child.
                if _kids:
                    _s = 0.0
                    _all_ok = True
                    _kc: List[str] = []
                    _anyprov = False
                    for c, ch in _kids:
                        cu = _est_unit_cost(ch)
                        if cu is None or cu <= 0:
                            _all_ok = False
                            break
                        _s += cu
                        _kc.append(c)
                        if _est_is_provisional(ch):
                            _anyprov = True
                    if _all_ok and _s > 0:
                        _child_sum = (_s, _kc, _anyprov)

            if _child_sum is not None:
                _s, _kc, _anyprov = _child_sum
                _apply_cost(
                    line, uc=_s, qty=qty,
                    source=f"assembly_of_{len(_kc)}_parts",
                    provisional=_anyprov,
                    extra={"child_part_codes": _kc, "kind": "assembly"},
                )
                for c in _kc:
                    bound_detail_codes.add(c)
                if _anyprov:
                    _flag("info", code,
                          f"assembly {_assembly_base(code)}: rolled up from {len(_kc)} costed detail part(s) "
                          f"(some provisional geometry) — preferred over GA self-estimate")
            elif code in est_by_code:
                uc = _est_unit_cost(est_by_code[code])
                if uc is not None and uc > 0:
                    prov = _est_is_provisional(est_by_code[code])
                    _apply_cost(line, uc=uc, qty=qty, source="fab_estimate", provisional=prov)
                    if prov:
                        _flag(
                            "warning",
                            code,
                            f"fab estimate for '{desc}' is provisional (inferred geometry / insufficient data)",
                        )
                    bound_detail_codes.add(code)
                elif uc is not None and uc <= 0:
                    _flag("warning", code, "matched fab estimate is £0 — price manually")
                else:
                    _flag("warning", code, "matched fab estimate has no unit cost — price manually")

            else:
                base = _assembly_base(code)
                prefix = _numeric_prefix(base or code)

                def _is_child(c: str) -> bool:
                    if c in claimed_exact or c in bound_detail_codes:
                        return False
                    if c == code:
                        return False
                    if c.startswith(code + "-") or c == base or c.startswith(base + "-"):
                        return True
                    if prefix and c.startswith(prefix + "-"):
                        return True
                    return False

                children = [(c, e) for c, e in est_by_code.items() if _is_child(c)]
                if children:
                    sub = 0.0
                    ok = True
                    any_prov = False
                    child_codes: List[str] = []
                    for c, ch in children:
                        cu = _est_unit_cost(ch)
                        if cu is None:
                            ok = False
                            continue
                        sub += cu
                        bound_detail_codes.add(c)
                        child_codes.append(c)
                        if _est_is_provisional(ch):
                            any_prov = True
                    if ok and sub > 0:
                        _apply_cost(
                            line,
                            uc=sub,
                            qty=qty,
                            source=f"assembly_of_{len(children)}_parts",
                            provisional=any_prov,
                            extra={"child_part_codes": child_codes, "kind": "assembly"},
                        )
                        if any_prov:
                            _flag(
                                "warning",
                                code,
                                f"assembly {base}: rolled up from {len(children)} part(s) with provisional geometry",
                            )
                    else:
                        _flag(
                            "warning",
                            code,
                            f"assembly {base}: {len(children)} detail part(s) but some uncosted — review",
                        )
                elif allow_ga_provisional and (_ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly"):
                    prov = provisional_cost_from_ga_bom(desc)
                    if prov and prov.get("unit_cost_gbp") is not None:
                        _apply_cost(
                            line,
                            uc=float(prov["unit_cost_gbp"]),
                            qty=qty,
                            source=prov.get("source") or "ga_bom_provisional",
                            provisional=True,
                            extra={
                                "kind": "assembly",
                                "inference_basis": prov.get("inference_basis"),
                                "blank_mm": prov.get("blank_mm"),
                            },
                        )
                        _flag("warning", code, prov.get("note") or "GA BOM provisional estimate — verify")
                    else:
                        _flag(
                            "error",
                            code,
                            f"assembly line '{desc}' has no costed detail parts and no GA description "
                            f"fallback — missing GA/detail set; price manually",
                        )
                        line.update(kind="assembly", cost_source="placeholder_no_detail")
                elif _ASSEMBLY_SUFFIX_RE.search(code) or kind == "assembly":
                    _flag(
                        "error",
                        code,
                        f"assembly line '{desc}' has no costed detail parts in scope — "
                        f"missing GA/detail set; price manually",
                    )
                    line.update(kind="assembly", cost_source="placeholder_no_detail")
                else:
                    _flag(
                        "error",
                        code,
                        f"BOM line '{desc}' has no cost basis (no estimate, no catalogue match) — price manually",
                    )
                    line["cost_source"] = "no_cost_basis"

        lines.append(line)

    for pl in packaging_lines or []:
        uc = float(pl.get("unit_cost_gbp") or 0.0)
        qty = float(pl.get("qty_per_bay") or 1.0)
        lines.append(
            {
                "code": pl.get("code") or "PACKAGING",
                "description": pl.get("description") or "Packaging",
                "qty_per_bay": qty,
                "kind": "template",
                "unit_cost_gbp": round(uc, 2),
                "line_cost_gbp": round(uc * qty, 2),
                "cost_source": "template",
                "costed": True,
                "cost_confidence": "high",
                "provisional": False,
            }
        )

    costed_lines = [ln for ln in lines if ln["costed"]]
    confident_lines = [ln for ln in costed_lines if ln.get("cost_confidence") == "high"]
    provisional_lines = [ln for ln in costed_lines if ln.get("provisional")]

    bay_unit_total = round(sum(ln["line_cost_gbp"] for ln in costed_lines), 2)
    bay_confident_total = round(sum(ln["line_cost_gbp"] for ln in confident_lines), 2)

    # E1 packaging + E3 overhead (config-driven, inheritable, surfaced for the spreadsheet)
    _pkg = _packaging_and_delivery_estimate(order_qty)
    _pkg_cost = _pkg.get("packaging_cost_per_bay_gbp") or 0.0
    _ovh_pol = getattr(config, "OVERHEAD_POLICY", {}) or {}
    _ovh_pct = float(_ovh_pol.get("pct", 0.0)) if _ovh_pol.get("enabled", False) else 0.0
    _ovh_base = bay_unit_total + _pkg_cost
    _overhead_gbp = round(_ovh_base * _ovh_pct / 100.0, 2)
    _bay_sell_total = round(_ovh_base + _overhead_gbp, 2)

    _excluded_kinds = {"template", "consumable"}
    n_lines = len([ln for ln in lines if ln["kind"] not in _excluded_kinds])
    n_uncosted = len([ln for ln in lines if ln["kind"] not in _excluded_kinds and not ln["costed"]])
    coverage = (n_lines - n_uncosted) / n_lines if n_lines else 0.0
    has_provisional = bool(provisional_lines)
    sufficient = (
        coverage >= data_sufficiency_floor
        and n_uncosted == 0
        and not has_provisional
    )

    return {
        "schema": "bay_estimate.v1",
        "order_quantity": order_qty,
        "bay_unit_total_gbp": bay_confident_total if sufficient else None,
        "bay_unit_total_provisional_gbp": bay_unit_total,
        "bay_unit_total_confident_gbp": bay_confident_total,
        "packaging": _pkg,
        "overhead_pct_applied": _ovh_pct,
        "overhead_gbp": _overhead_gbp,
        "bay_sell_total_gbp": _bay_sell_total,   # manufacturing + packaging + overhead
        "headline_suppressed": not sufficient,
        "line_coverage": round(coverage, 3),
        "uncosted_lines": n_uncosted,
        "provisional_lines": len(provisional_lines),
        "bom_line_count": len(lines),
        "lines": lines,
        "flags": flags,
    }


def make_system_cost_pricer(resolve_part_system_cost, *, reject_above_gbp: float = None):
    """Adapt _resolve_part_system_cost into a bay catalogue_pricer with £750 guard."""
    if reject_above_gbp is None:
        import config as _cfg_sc
        reject_above_gbp = float(getattr(_cfg_sc, "SYSTEM_COST_REJECT_ABOVE_GBP", 750.0))
    def pricer(code: str, desc: str):
        try:
            from part_identity import catalogue_search_descriptions

            desc_variants = catalogue_search_descriptions(code, desc)
        except Exception:
            desc_variants = [desc]
        for variant in desc_variants:
            part = {"part_number": code, "description": variant}
            try:
                res = resolve_part_system_cost(part) or {}
            except Exception as e:
                return {"unit_cost_gbp": None, "source": "system_cost_error", "reason": f"pricer error: {e}"}
            uc = res.get("applied_unit_cost")
            matched = res.get("matched_part_code")
            if uc is None:
                continue
            try:
                uc = float(uc)
            except (TypeError, ValueError):
                continue
            if uc <= 0 or uc > reject_above_gbp:
                continue
            return {
                "unit_cost_gbp": uc,
                "source": "system_cost",
                "matched_part_code": matched,
                "confidence": float(getattr(__import__("config"), "UDEF_CATALOGUE_CONFIDENCE", 0.9)),
            }
        # system_cost found nothing. Before giving up, try the fuzzy UDEF lookup, which
        # has a description-token / prefix arm the exact-code system_cost pricer lacks.
        # (Note: for some drawing codes like bare "ELECTRICS" there is no matching UDEF row
        # at all — the loom is a generic instruction, not a stocked catalogue part — so this
        # will correctly still miss and fall through to the web/LLM tier below.)
        try:
            fz = _udef_fuzzy_lookup(desc or code, code)
        except Exception:
            fz = None
        if fz and fz.get("unit_cost_gbp"):
            try:
                _fzuc = float(fz["unit_cost_gbp"])
            except (TypeError, ValueError):
                _fzuc = None
            if _fzuc and 0 < _fzuc <= reject_above_gbp:
                return {
                    "unit_cost_gbp": _fzuc,
                    "source": "udef_fuzzy",
                    "matched_part_code": fz.get("code"),
                    "supplier": fz.get("supplier_name"),
                    "confidence": float(getattr(__import__("config"), "UDEF_CATALOGUE_CONFIDENCE", 0.9)),
                }
        # Final tier: web/LLM indicative price. Fires ONLY when every internal source
        # (system_cost + fuzzy UDEF) has missed — i.e. a bought-in part that is identified on
        # the drawing but not priceable from SDI's own data. The price comes back clearly
        # flagged (source web_ai_fallback/llm_market_estimate) so xlsx_output renders it as
        # "AI ESTIMATE (Grok) — verify", never as a verified catalogue line. Gated on the
        # same web fallback policy the part pricer uses, so it can be disabled centrally.
        try:
            import config as _cfg_web
            _fp = getattr(_cfg_web, "FALLBACK_PRICING_POLICY", {}) or {}
            # Use the real policy key that exists in config (enable_web_ai_fallback). The
            # web/LLM tier fires only when this is on, so it can be disabled centrally.
            _web_enabled = bool(_fp.get("enable_web_ai_fallback", _fp.get("llm_market_estimate_fallback", False)))
        except Exception:
            _web_enabled = False
        if _web_enabled:
            # LLM prices are NON-DETERMINISTIC — Grok returns a different figure each call
            # (e.g. ELECTRICS came back £12.50 one run, £22.00 the next). An estimating tool
            # MUST be reproducible: the same job has to price the same every time. So cache the
            # LLM price per part description on first lookup and reuse it thereafter. The
            # estimator can clear the cache or override the line; the engine stays deterministic.
            import json as _json, os as _os, hashlib as _hashlib
            _cache_path = getattr(_cfg_web, "LLM_PRICE_CACHE",
                                  _os.path.join(str(getattr(_cfg_web, "OUTPUT_DIR", ".")), "llm_price_cache.json"))
            _key_raw = (str(code) + "|" + str(desc)).upper().strip()
            _key = _hashlib.md5(_key_raw.encode("utf-8")).hexdigest()
            _cache = {}
            try:
                if _os.path.exists(_cache_path):
                    with open(_cache_path, encoding="utf-8") as _cf:
                        _cache = _json.load(_cf) or {}
            except Exception:
                _cache = {}
            if _key in _cache:
                _c = _cache[_key]
                return {
                    "unit_cost_gbp": float(_c["unit_cost_gbp"]),
                    "source": _c.get("source", "llm_market_estimate"),
                    "matched_part_code": None,
                    "confidence": float(_c.get("confidence", 0.45)),
                    "review_flag": True,
                    "review_reason": _c.get("review_reason", "Indicative AI price (cached) — verify before quoting."),
                    "cached": True,
                }
            try:
                from web_ai_price_lookup import lookup_web_ai_price
                _wr = lookup_web_ai_price(
                    {"description": desc or code, "part_code": code},
                    enable_web_search=True,
                    enable_llm_estimate=True,
                )
                if _wr.get("found") and _wr.get("price_gbp"):
                    _wuc = float(_wr["price_gbp"])
                    if 0 < _wuc <= reject_above_gbp:
                        _cap = float((getattr(_cfg_web, "FALLBACK_PRICING_POLICY", {}) or {}).get("fallback_confidence_cap", 0.68))
                        _result = {
                            "unit_cost_gbp": _wuc,
                            "source": _wr.get("source_type", "web_ai_fallback"),
                            "matched_part_code": None,
                            "confidence": min(float(_wr.get("confidence") or 0.45), _cap),
                            "review_flag": True,
                            "review_reason": _wr.get("review_reason", "Indicative web/AI price — verify before quoting."),
                        }
                        # Persist so the NEXT run reuses this exact price (determinism).
                        try:
                            _cache[_key] = {
                                "unit_cost_gbp": _wuc,
                                "source": _result["source"],
                                "confidence": _result["confidence"],
                                "review_reason": _result["review_reason"],
                                "_desc": _key_raw,  # human-readable, so the cache is auditable/clearable
                            }
                            with open(_cache_path, "w", encoding="utf-8") as _cf:
                                _json.dump(_cache, _cf, indent=2)
                        except Exception:
                            pass
                        return _result
            except Exception:
                pass
        return {"unit_cost_gbp": None, "source": "system_cost_no_match", "reason": "no parts-DB match"}

    return pricer