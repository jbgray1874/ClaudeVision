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


# ── A UNIT THAT CONTRADICTS THE DESCRIPTION ──────────────────────────────────────────────
#
# FIXING1784 is live in the bought-in catalogue right now:
#
#     Edging Seal Strip 10m Roll (Rubusec)    uom = metre    GBP 29.80
#
# GBP 29.80 is the ROLL. Per metre it is GBP 2.98. A part needing two metres of edging is
# costed at GBP 59.60 instead of GBP 5.96, and everything downstream agrees with it, because
# a price and a unit are individually plausible and only wrong together.
#
# parse_unit is careful about WHERE it read the unit -- column, then price heading, then
# description -- and that ordering exists because reading "sheet" out of "ABS sheet white
# textured" once loaded a per-m2 price as a per-sheet one. This is the other half of the same
# problem: the unit can be read correctly from the file and still contradict what the
# description says is being sold.
#
# It CANNOT be resolved automatically. "10m Roll ... per metre" is either a roll price with
# the wrong unit or a metre price with the roll size mentioned in passing, and only the
# supplier knows which. So this flags and does not fix: a wrong price loaded silently is the
# failure, an argument on the console is not.
_PACK_IN_DESCRIPTION = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(m|mm|metre|metres|kg|g|l|ltr|litre)\b"
    r"\s*(roll|reel|coil|pack|box|bag|tub|drum|tin|sheet|length|bar|tube)\b",
    re.I)
# A unit that measures a quantity. If the description says the product IS a pack of these,
# the price is very likely the pack.
_MEASURED = {"m", "m2", "kg", "t", "l"}
# The catalogue does not spell units the way parse_unit does -- the live row that started
# this says "metre", not "m". A checker that only understands its own vocabulary passes the
# exact row it was written for, which is what the first version of this did.
_UNIT_ALIASES = {"metre": "m", "metres": "m", "mtr": "m", "lm": "m", "lin m": "m",
                 "sqm": "m2", "sq m": "m2", "m^2": "m2", "square metre": "m2",
                 "kilo": "kg", "kilogram": "kg", "kgs": "kg",
                 "litre": "l", "ltr": "l", "tonne": "t", "ton": "t",
                 "ea": "ea", "each": "ea", "unit": "ea", "pc": "ea", "pcs": "ea"}


def unit_conflicts(description: str, unit: str) -> str:
    """Say why a unit looks wrong for this description, or "" if it does not.

    Deliberately narrow. Every rule here has a row behind it that is wrong in the live
    catalogue today; a checker that fires on healthy lines is one people switch off.
    """
    desc = str(description or "")
    unit = str(unit or "").strip().lower()
    unit = _UNIT_ALIASES.get(unit, unit)

    pack = _PACK_IN_DESCRIPTION.search(desc)
    if pack and unit in _MEASURED:
        qty, measure, container = pack.groups()
        return (f'described as a {qty}{measure} {container.lower()} but priced per "{unit}" '
                f"-- if the figure is the {container.lower()}, every line using this is out "
                f"by {qty}x")

    # Powder, paint and adhesive are sold by mass. "each" of a coating is not a quantity
    # anybody can cost against, and there are two such rows in the catalogue now.
    # A RAL number with a finish level names a COATING, not a part: "Black RAL 9005 Gloss"
    # is in the catalogue at GBP 4.23 "each", beside "Powder Anthracite Grey RAL 7016 Semi
    # Gloss" at GBP 4.56. The second says powder and the first does not, and they are the
    # same kind of thing -- so matching only the word "powder" flags one of a pair.
    coating = re.search(r"\b(powder\s*coat|powder|lacquer|paint|adhesive|resin|primer)\b",
                        desc, re.I) or re.search(
        r"\bRAL\s*\d{4}\b.*\b(gloss|matt|matte|satin|semi[\s-]?gloss|textured)\b", desc, re.I)
    # BUT A POWDER-COATED BRACKET IS A BRACKET, and it is priced each, correctly. SDI
    # powder-coats most of what it makes, so "coating word + each" on its own would flag a
    # large share of a healthy file -- and a checker that cries wolf on real rows is one
    # somebody turns off in the week it would have mattered. The distinction is whether the
    # description names a THING or only a FINISH: "Black RAL 9005 Gloss" is a finish;
    # "RAL9005 Gloss Black Powder Coated Steel Bracket 200mm" is a bracket that has one.
    is_a_thing = re.search(
        r"\b(bracket|panel|plate|frame|tube|bar|angle|channel|profile|leg|foot|feet|shelf|"
        r"door|lid|tray|box|clip|screw|nut|bolt|washer|rivet|insert|hinge|castor|caster|"
        r"wheel|handle|lock|magnet|glide|stud|pin|strip|rail|post|upright|base|top|"
        r"sheet|board|cover|housing|assembly|weldment|component|part)\b", desc, re.I)
    if unit == "ea" and coating and not is_a_thing:
        return ('a coating priced "each" -- each of what? These are bought by mass, so the '
                "figure is a rate with its unit lost, not a part price")

    return ""
