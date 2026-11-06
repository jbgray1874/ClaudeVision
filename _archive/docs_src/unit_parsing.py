import re
from typing import Optional


def _normalize_unit(unit: Optional[str]) -> str:
    """
    Normalize supplier "unit" strings into something comparable.

    Examples we try to handle:
    - "GBP_per_kg", "per_kg", "kg"
    - "GBP/kg", "GBP / kg", "£/kg"
    - "GBP_per_hour", "hourly", "per_hour", "GBP/hr"
    """
    if unit is None:
        return ""
    u = str(unit).strip().lower()
    u = u.replace("£", "gbp")
    u = u.replace("€", "eur")
    u = u.replace(" ", "")
    u = u.replace("–", "-")
    u = u.replace("_", "_")
    return u


def is_per_kg_unit(unit: Optional[str]) -> bool:
    u = _normalize_unit(unit)
    if not u:
        return False

    # Common explicit matches
    if u in {"gbp_per_kg", "per_kg", "kg", "gbp/kg"}:
        return True

    # Flexible pattern match
    # - "gbp/kg"
    # - "perkg"
    # - "price per kg"
    if "per" in u and "kg" in u:
        return True
    if re.search(r"gbp[/]kg", u):
        return True

    return False


def is_per_hour_unit(unit: Optional[str]) -> bool:
    u = _normalize_unit(unit)
    if not u:
        return False

    if u in {"hour", "hourly", "per_hour", "gbp_per_hour", "gbp/hr", "hr"}:
        return True

    if "per" in u and "hour" in u:
        return True
    if "gbp" in u and ("hr" in u or "hour" in u):
        return True

    # Also accept variants like "gbp/hr"
    if re.search(r"gbp[/]h(r|our)?", u):
        return True

    return False

