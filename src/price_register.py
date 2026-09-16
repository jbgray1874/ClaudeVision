"""SDI's prices as DATA — one versioned register, reviewable without a code edit.

    "Prices are data, not hidden logic. A price must state its source, date, scope, status
     and review/expiry date. A job-specific quote must never become an automatic shared
     rate."                                     — the change register's operating rules

WHY THIS EXISTS. The figures were numeric literals in config.py — the tape's roll at £4.50,
Tony's edging at £0.35/m, a plater's £250 — each attributed and dated, which made them honest
and did not make them right. Three things follow from a price living in source:

  * changing a rate is a CODE change, so a commercial decision needs an engineer;
  * nothing carries an EXPIRY, so a figure is as loud on the day it goes stale as on the day
    it was given, and age becomes indistinguishable from agreement;
  * a job's quote and a shop's standing rate look identical in the file, which is how £250
    for one stand came to be chargeable on every job whose drawing named the same finish.

So the money moves to `data/price_register.json` and this module reads it. The engine keeps
the MECHANISM — what to price, in what quantity, by which route, and which source wins.

NOT A CACHE AND NOT A CATALOGUE. It answers where SDI Live cannot, and is asked after it.
stated_prices.resolve still runs the waterfall; this is one rung of it.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REGISTER_PATH = Path(__file__).resolve().parent.parent / "data" / "price_register.json"

# Status meanings, and what each one permits. Ordered from firmest down, because the
# hierarchy in the operating rules is the same order.
STATUSES = ("live", "confirmed", "historical", "indicative")

# Every field an entry must carry. A price that cannot say these things cannot be judged,
# and a figure nobody can judge is one nobody can replace.
REQUIRED_FIELDS = ("price_key", "label", "amount", "unit", "currency",
                   "source_type", "source_reference", "source_date",
                   "review_date", "scope", "status")

_CACHE: Optional[Dict[str, Any]] = None


def _today() -> date:
    """Overridable for tests, and never a hidden dependency on the wall clock elsewhere."""
    _stub = os.getenv("SDI_REGISTER_TODAY", "").strip()
    if _stub:
        try:
            return datetime.strptime(_stub, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _parse_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def load(refresh: bool = False) -> Dict[str, Any]:
    """The register, or an empty one. NEVER raises.

    A missing or malformed register must not stop a job being estimated — it means the
    engine falls through to the sources below it, exactly as it does when SDI Live is
    unreachable. What it must not do is fail silently, so problems are collected and
    reported to the caller rather than swallowed.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    out: Dict[str, Any] = {"prices": {}, "problems": [], "path": str(_REGISTER_PATH)}
    try:
        raw = json.loads(_REGISTER_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["problems"].append(f"{_REGISTER_PATH}: no price register — nothing to read")
        _CACHE = out
        return out
    except (OSError, ValueError) as err:
        out["problems"].append(f"{_REGISTER_PATH}: unreadable — "
                               f"{type(err).__name__}: {err}")
        _CACHE = out
        return out
    for entry in (raw.get("prices") or []):
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("price_key") or "").strip().upper()
        missing = [f for f in REQUIRED_FIELDS if entry.get(f) in (None, "")]
        if not key:
            out["problems"].append("an entry has no price_key — skipped")
            continue
        if missing:
            # NOT APPLIED, AND SAID OUT LOUD. An incomplete price is the one shape this
            # register exists to prevent: a number with no date, scope or status is the
            # literal it replaced, wearing a JSON file's clothes.
            out["problems"].append(
                f"{key}: missing {', '.join(missing)} — NOT APPLIED. Every price must say "
                f"what it is, where it came from, when that was current, what it may price "
                f"and how firm it is")
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status not in STATUSES:
            out["problems"].append(
                f"{key}: status {status!r} is not one of {', '.join(STATUSES)} — NOT APPLIED")
            continue
        out["prices"][key] = dict(entry, price_key=key, status=status)
    _CACHE = out
    return out


def problems() -> List[str]:
    """Everything wrong with the register, for the run log. Empty is the normal case."""
    return list(load().get("problems") or [])


def _scope_allows(entry: Dict[str, Any], job: Any) -> bool:
    """May this price apply to the job in hand?

    Only `job_only` narrows by job, and it is the reason this field exists: a quote given
    for one job must not price another. Every other scope is about materials, departments
    or customers, which the caller has already matched by asking for the key.
    """
    scope = entry.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    if str(scope.get("kind") or "").strip().lower() != "job_only":
        return True
    want = str(scope.get("value") or "").strip()
    if not want:
        return False
    try:
        from estimator_confirmed import _same_job_code as _same
    except Exception:                                                # noqa: BLE001
        return False
    for code in (job or ()):
        if _same(want, str(code)):
            return True
    return False


def lookup(price_key: Any, job: Any = ()) -> Optional[Dict[str, Any]]:
    """The register's answer for this key, or None.

    Returns the entry with two computed fields the caller needs and must not work out for
    itself:

        chargeable   may the engine put this figure on the sheet as a price? `historical`
                     prices are NOT chargeable outside their own job — they are offered as
                     labelled comparators, and the caller decides how to say so.
        out_of_review  the review date has passed. The figure still answers, because silence
                     is worse than an old number, and it says so.
    """
    key = str(price_key or "").strip().upper()
    if not key:
        return None
    entry = (load().get("prices") or {}).get(key)
    if not entry:
        return None
    _own_job = _scope_allows(entry, job)
    _review = _parse_date(entry.get("review_date"))
    out = dict(entry)
    out["in_scope_for_this_job"] = _own_job
    out["chargeable"] = bool(_own_job and entry["status"] in ("live", "confirmed",
                                                             "indicative"))
    out["out_of_review"] = bool(_review and _review < _today())
    return out


def describe(entry: Dict[str, Any]) -> str:
    """The sentence that goes beside the money, so the line says what it rests on."""
    if not isinstance(entry, dict):
        return ""
    bits = [f"{entry.get('source_type', 'source not recorded')}: "
            f"{entry.get('source_reference', 'reference not recorded')}",
            f"current at {entry.get('source_date', 'an unrecorded date')}",
            f"status {entry.get('status', 'unknown')}"]
    if entry.get("out_of_review"):
        bits.append(f"PAST ITS REVIEW DATE ({entry.get('review_date')}) — still applied, "
                    f"because a missing price is worse than an old one, but check it")
    return " · ".join(bits)
