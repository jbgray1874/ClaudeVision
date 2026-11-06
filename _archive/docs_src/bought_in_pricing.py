"""
bought_in_pricing.py — SDI Intelligence

A bought-in price book seeded from manually-estimated SDI workbooks (the
"Material Price Break" sheet). Bought-in / catalogue items — ELECTRICS, FIXING*,
SLOTTEDTUBE*, SUBPLAS* (acrylic/HIPS substrates), VINYL*, POWDER*, packaging —
are priced by IDENTITY: a coded description matched to a known price, NOT by
geometry. So a PDF GA is a perfectly good source for them and no DXF is needed;
reading them off the GA BOM is a lookup, not a guess.

Drop-in for bay_rollup's catalogue_pricer contract:
    pricer(code, desc) -> {"unit_cost_gbp", "source", "matched_part_code",
                           "confidence", ...}                      on a hit
                       -> {"unit_cost_gbp": None, "source", "reason"} on a miss
On a miss bay_rollup flags the line "price manually" rather than guessing — the
core no-confident-wrong-number rule holds.

Every price carries provenance (which estimate workbook it came from) so it is
auditable and updatable: surface -> ask -> fix, and log it. A price off one
sheet is a point estimate; recurring bought-ins (rivets, looms) are stable
enough to seed, and the qty-break basis is recorded so a qty mismatch lowers
the confidence rather than passing silently.

Loading needs pandas + an Excel engine (xlrd for .xls, openpyxl for .xlsx). If
neither is present, loading returns {} and never raises — ingestion can't break
an estimate run.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# SDI quantity-break columns seen on the Material Price Break sheet.
_QTY_BREAKS_DEFAULT = [25, 50, 100, 250, 500, 1000, 2000]

# Catalogue code = leading alpha run + optional digits: ELECTRICS, FIXING5,
# FIXING125, SLOTTEDTUBE01, SUBPLAS72, VINYL03, POWDER5, BOX82 ...
_CODE_RE = re.compile(r"^\s*([A-Z]+\d*)\b")


def split_code_desc(text: str) -> Tuple[str, str]:
    """'FIXING5-4.0 X 10 POP RIVET' -> ('FIXING5', '4.0 X 10 POP RIVET');
    'ELECTRICS - 50cm LOOM'        -> ('ELECTRICS', '50cm LOOM')."""
    s = str(text or "").strip()
    m = _CODE_RE.match(s.upper())
    if not m:
        return ("", s)
    code = m.group(1)
    rest = s[m.end():].lstrip(" -\u2013:\t").strip()
    return (code, rest)


def _normalise_desc(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper()).strip()


def load_price_book_from_workbook(
    path: Any,
    sheet_name: str = "Material Price Break",
    qty_breaks: Optional[List[int]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Read a manual-estimate 'Material Price Break' sheet into a price book
    keyed by catalogue code. Never raises — returns {} on any failure."""
    try:
        import pandas as pd
    except Exception:
        return {}
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, header=None)
    except Exception:
        return {}

    src = Path(str(path)).name
    breaks = set(qty_breaks or _QTY_BREAKS_DEFAULT)

    # Locate the header row carrying the qty-break columns.
    qty_cols: Dict[int, int] = {}
    desc_col: Optional[int] = None
    header_row: Optional[int] = None
    for r in range(min(15, len(df))):
        row = [df.iat[r, c] for c in range(df.shape[1])]
        nums: Dict[int, int] = {}
        for c, v in enumerate(row):
            try:
                iv = int(float(v))
            except (TypeError, ValueError):
                continue
            if iv in breaks:
                nums[c] = iv
        if len(nums) >= 3:
            qty_cols = nums
            first_qty_c = min(nums)
            for c in range(first_qty_c):
                if isinstance(row[c], str) and row[c].strip():
                    desc_col = c
            if desc_col is None:
                desc_col = max(0, first_qty_c - 1)
            header_row = r
            break

    if not qty_cols or header_row is None:
        return {}

    book: Dict[str, Dict[str, Any]] = {}
    for r in range(header_row + 1, len(df)):
        raw = df.iat[r, desc_col]
        if not isinstance(raw, str) or not raw.strip():
            continue
        code, desc = split_code_desc(raw)
        prices: Dict[int, float] = {}
        for c, q in qty_cols.items():
            try:
                p = float(df.iat[r, c])
            except (TypeError, ValueError):
                continue
            if p and p > 0:
                prices[q] = round(p, 4)
        if not prices:
            continue
        key = code or _normalise_desc(raw)
        book[key] = {
            "code": code,
            "description": desc or raw.strip(),
            "raw_text": raw.strip(),
            "prices_by_qty": prices,
            "source": f"manual_estimate:{src}",
        }
    return book


def merge_price_books(*books: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Combine several workbooks' price books. Later books win on key clashes,
    but qty breaks are unioned so coverage accumulates across jobs."""
    out: Dict[str, Dict[str, Any]] = {}
    for book in books:
        for key, rec in (book or {}).items():
            if key not in out:
                out[key] = {**rec, "prices_by_qty": dict(rec.get("prices_by_qty", {}))}
            else:
                out[key]["prices_by_qty"].update(rec.get("prices_by_qty", {}))
                out[key]["source"] = rec.get("source", out[key].get("source"))
    return out


_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _year_from_path(path: Any) -> Optional[int]:
    """Best-effort job year from a path/filename (e.g. K:\\...\\2019\\job.xls)."""
    m = _YEAR_RE.search(str(path))
    if m:
        y = int(m.group(0))
        if 1990 <= y <= 2100:
            return y
    return None


def sort_paths_chronologically(paths: List[Any]) -> List[Any]:
    """Oldest -> newest, by a year found in the path, then file mtime. Lets the
    master loader process newest last so recent prices win."""
    import os

    def key(p: Any):
        y = _year_from_path(p)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            mt = 0.0
        return (y if y is not None else 0, mt)

    return sorted(paths, key=key)


def load_master_price_book(
    workbook_paths: List[Any],
    sheet_name: str = "Material Price Break",
    order_chronologically: bool = True,
    min_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate the Material Price Break sheets across many estimate workbooks
    into one master price book. Drop-in for make_price_book_pricer via the
    returned ["book"]. Never raises — unreadable workbooks are skipped and
    listed. Records per item: chosen price (newest-wins), qty breaks unioned
    across jobs, n_jobs it appeared in, every contributing source, and the
    spread of observed prices (for a freshness/variance proviso).

    min_year filters to jobs at/after a year (e.g. 2003) when the path carries
    one; paths with no detectable year are kept (can't prove they're too old).
    """
    paths = list(workbook_paths)
    if min_year is not None:
        paths = [p for p in paths
                 if (_year_from_path(p) is None) or (_year_from_path(p) >= min_year)]
    if order_chronologically:
        paths = sort_paths_chronologically(paths)  # oldest first -> newest wins

    master: Dict[str, Dict[str, Any]] = {}
    loaded = 0
    skipped: List[str] = []
    for path in paths:
        book = load_price_book_from_workbook(path, sheet_name=sheet_name)
        if not book:
            skipped.append(str(path))
            continue
        loaded += 1
        for key, rec in book.items():
            prices = rec.get("prices_by_qty", {})
            tgt = master.get(key)
            if tgt is None:
                master[key] = {
                    "code": rec.get("code"),
                    "description": rec.get("description"),
                    "raw_text": rec.get("raw_text"),
                    "prices_by_qty": dict(prices),
                    "source": rec.get("source"),
                    "latest_source": rec.get("source"),
                    "n_jobs": 1,
                    "sources": [rec.get("source")],
                    "observed_by_qty": {q: [v] for q, v in prices.items()},
                }
            else:
                # processed in chronological order, so this later record wins.
                tgt["prices_by_qty"].update(prices)
                tgt["latest_source"] = rec.get("source")
                tgt["n_jobs"] += 1
                tgt["sources"].append(rec.get("source"))
                if not tgt.get("description"):
                    tgt["description"] = rec.get("description")
                for q, v in prices.items():
                    tgt["observed_by_qty"].setdefault(q, []).append(v)

    return {
        "book": master,
        "item_count": len(master),
        "workbooks_loaded": loaded,
        "workbooks_skipped": skipped,
    }


def _price_for_qty(
    prices_by_qty: Dict[int, float], order_qty: int
) -> Tuple[Optional[float], Optional[str]]:
    """Pick the unit price for an order qty: exact break, else nearest
    populated break <= qty, else the lowest populated break (flagged)."""
    if not prices_by_qty:
        return (None, None)
    if order_qty in prices_by_qty:
        return (prices_by_qty[order_qty], "exact_qty_break")
    le = [q for q in prices_by_qty if q <= order_qty]
    if le:
        q = max(le)
        return (prices_by_qty[q], f"nearest_qty_break_{q}")
    q = min(prices_by_qty)
    return (prices_by_qty[q], f"fallback_qty_break_{q}")


def make_price_book_pricer(
    price_book: Dict[str, Dict[str, Any]], order_quantity: int = 100
) -> Callable[[str, str], Dict[str, Any]]:
    """Drop-in bay_rollup catalogue_pricer backed by the manual-estimate price
    book. Matches the GA token's CODE directly (ELECTRICS, FIXING5, SUBPLAS72,
    ...); falls back to a normalised-description containment match. Returns a
    None-style dict on a miss so the line is flagged, never guessed."""
    by_code: Dict[str, Dict[str, Any]] = {}
    by_desc: Dict[str, Dict[str, Any]] = {}
    for rec in price_book.values():
        if rec.get("code"):
            by_code[rec["code"].upper()] = rec
        nd = _normalise_desc(rec.get("raw_text"))
        if nd:
            by_desc[nd] = rec

    def pricer(code: str, desc: str) -> Dict[str, Any]:
        c = str(code or "").strip().upper()
        rec = by_code.get(c)
        match_kind = "code"
        if rec is None:
            nd = _normalise_desc(f"{code} {desc}")
            rec = by_desc.get(nd)
            if rec is not None:
                match_kind = "description"
            else:
                for dkey, drec in by_desc.items():
                    if dkey and (dkey in nd or nd in dkey):
                        rec, match_kind = drec, "description"
                        break
        if rec is None:
            return {
                "unit_cost_gbp": None,
                "source": "price_book_no_match",
                "reason": "no manual-estimate price for this token",
            }
        price, qty_basis = _price_for_qty(rec["prices_by_qty"], order_quantity)
        if price is None:
            return {
                "unit_cost_gbp": None,
                "source": "price_book_no_qty",
                "reason": "no populated qty break",
            }
        conf = 0.85 if match_kind == "code" else 0.65
        if qty_basis and qty_basis.startswith("nearest"):
            conf -= 0.10
        elif qty_basis and qty_basis.startswith("fallback"):
            conf -= 0.20
        n_jobs = int(rec.get("n_jobs", 1) or 1)
        provisos: List[str] = []
        if n_jobs <= 1:
            conf -= 0.05
            provisos.append("single historical observation — may be job-specific")
        allobs = [v for vs in (rec.get("observed_by_qty") or {}).values() for v in vs]
        if len(allobs) >= 2:
            lo, hi = min(allobs), max(allobs)
            if lo > 0 and hi / lo > 1.5:
                conf -= 0.05
                provisos.append(f"price varies across jobs (\u00a3{lo:g}-\u00a3{hi:g}) \u2014 verify")
        if qty_basis and not qty_basis.startswith("exact"):
            provisos.append(f"qty-break basis: {qty_basis} (no exact match for order qty)")
        return {
            "unit_cost_gbp": price,
            "source": rec.get("source"),
            "matched_part_code": rec.get("code") or rec.get("raw_text"),
            "confidence": round(max(conf, 0.3), 2),
            "match_kind": match_kind,
            "qty_basis": qty_basis,
            "n_jobs": n_jobs,
            "provisos": provisos,
        }

    return pricer


def combine_pricers(
    *pricers: Optional[Callable[[str, str], Dict[str, Any]]]
) -> Callable[[str, str], Dict[str, Any]]:
    """Compose catalogue_pricers in priority order: the first to return a usable
    price wins; otherwise the last miss (with its reason) is returned so
    bay_rollup still flags the line meaningfully."""
    ps = [p for p in pricers if p]

    def pricer(code: str, desc: str) -> Dict[str, Any]:
        last: Optional[Dict[str, Any]] = None
        for p in ps:
            res = p(code, desc)
            if res and res.get("unit_cost_gbp") is not None:
                return res
            last = res or last
        return last or {"unit_cost_gbp": None, "source": "no_pricer", "reason": "no pricer matched"}

    return pricer


# ══════════════════════════════════════════════════════════════════════════════
# Caching — build the master book once (periodically), load it fast at runtime
# ══════════════════════════════════════════════════════════════════════════════

def _num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def save_price_book(book: Dict[str, Dict[str, Any]], path: Any) -> Any:
    """Persist a (master) price book to JSON. Build periodically, NOT per-scan."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(book, f, indent=2, default=str)
    return path


def load_cached_price_book(path: Any) -> Dict[str, Dict[str, Any]]:
    """Load a cached price book; returns {} if absent/unreadable so the estimate
    path degrades to system-cost-only. Restores the int qty-break keys that JSON
    serialises as strings (the pricer looks up prices_by_qty[order_qty] as int)."""
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    book: Dict[str, Dict[str, Any]] = {}
    for key, rec in (raw or {}).items():
        rec = dict(rec)
        pbq = rec.get("prices_by_qty") or {}
        rec["prices_by_qty"] = {int(q): _num(v) for q, v in pbq.items() if _num(v) is not None}
        obq = rec.get("observed_by_qty")
        if isinstance(obq, dict):
            rec["observed_by_qty"] = {
                int(q): [_num(x) for x in vs if _num(x) is not None] for q, vs in obq.items()
            }
        book[key] = rec
    return book


def build_and_cache_master_book(workbook_paths: List[Any], cache_path: Any, **kwargs) -> Dict[str, Any]:
    """Aggregate the archive into a master book and cache it. Run periodically
    (e.g. weekly), NOT on the estimate hot path. Returns the loader stats plus
    cache_path."""
    res = load_master_price_book(workbook_paths, **kwargs)
    save_price_book(res["book"], cache_path)
    res["cache_path"] = str(cache_path)
    return res
