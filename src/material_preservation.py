"""The charged line keeps the stated material, unless a recorded decision changed it (D-602).

THE HPP TIMBER BLOCKING, 30 OCT 2026. Eight timber blocks were read as a solid flat bar,
the hollow-section rule took the bar's thickness for a tube wall, and the line was charged
as mild steel: GBP 542.80 of steel section for eight pieces of wood. D-599c/d fixed that
route. The material sweep of the same day found ten more places where a part's material can
change after the read, and two of them write no flag at all. Fixing the sites one by one
leaves the next one silent.

So this is the check at the end, where the money is placed. For every part the workbook
charges:

  * the material it is charged as must be the material it was stated as, read as the same
    material under the rate lookup's own resolution ("Aluminium, 3mm" is ALUMINIUM), or the
    part must carry a recorded decision that says it was changed and asks for confirmation;

  * a Sheet Steel row must be steel the Sheet Steel block can price: mild steel, zintec,
    galvanised, or a part whose material was never read. That block prices every row at one
    mild-steel rate, so anything else there is charged as mild steel whatever it says.

A failure is never fixed silently here. It becomes a named question on the book.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

# Words that, in a flag on the part, show the change was recorded AND put to the estimator.
_RECORDED_MARKS = ("MATERIAL CONFLICT", "THE MATERIAL IS UNCONFIRMED",
                   "WHICH IS THE SAME MATERIAL")


def _key(material: Any) -> str:
    """The material under the rate lookup's own resolution, so a gauge or a stock-form word
    beside the name is not a different material."""
    name = str(material or "").strip()
    if not name:
        return ""
    try:
        import config
        resolved = config.resolve_material_rate_key(name)
    except Exception:                                                # noqa: BLE001
        resolved = None
    return str(resolved or name).upper().replace("_", " ").strip()


def same_material(a: Any, b: Any) -> bool:
    return _key(a) == _key(b)


def _charged_material(part: Dict[str, Any]) -> str:
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), dict) else {}
    return str(me.get("material") or "").strip()


def _stated_material(part: Dict[str, Any]) -> str:
    return str(part.get("normalized_material") or part.get("material") or "").strip()


def _flags(part: Dict[str, Any]) -> Iterable[str]:
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), dict) else {}
    for f in list(part.get("review_flags") or []) + list(me.get("review_flags") or []):
        yield str(f or "")


def change_is_recorded(part: Dict[str, Any], charged: str) -> bool:
    """A flag on the part names the change and asks for it to be confirmed."""
    ch = _key(charged)
    for f in _flags(part):
        up = f.upper()
        if any(m in up for m in _RECORDED_MARKS):
            return True
        if "CONFIRM" in up and ch and ch in up.replace("_", " "):
            return True
    return False


def material_question(part: Dict[str, Any]) -> Optional[str]:
    """The question to ask when the charged material is not the stated one and nothing
    recorded the change; None when they agree or the change was recorded."""
    stated, charged = _stated_material(part), _charged_material(part)
    if not stated or not charged or same_material(stated, charged):
        return None
    if change_is_recorded(part, charged):
        return None
    pn = str(part.get("part_number") or "—")
    return (f"MATERIAL NOT PRESERVED: {pn} is stated as {stated} and charged as {charged}, and "
            f"no recorded decision changed it — confirm which material is meant before this "
            f"line is relied on")


# The metals, as whole words (D-605a): the normaliser names steel, stainless and aluminium;
# these are the metals it does not name. "IRONWOOD" is a timber and "STEELWOOD" a finish.
_METAL_WORDS = ("STEEL", "STAINLESS", "ALUMINIUM", "ALUMINUM", "ZINTEC", "GALVANISED",
                "GALVANIZED", "GALV", "BRASS", "BRONZE", "COPPER", "IRON", "ZINC", "CR4",
                "TITANIUM", "GUNMETAL")
_METAL_KEYS = frozenset({"MILD_STEEL", "STAINLESS_STEEL", "ALUMINIUM", "ALUMINUM",
                         "GALVANISED_STEEL", "ZINTEC", "BRASS", "COPPER"})


def is_metal(material: Any) -> bool:
    """Is this material a metal? One controlled answer, by whole words (D-605a).

    The normaliser's own key decides first: a material it names as steel, stainless or
    aluminium is metal, and one it names as board, timber or plastic is not. Otherwise a
    metal word must stand as a word, so IRONWOOD and STEELWOOD are not metal."""
    name = " ".join(str(material or "").upper().replace("_", " ").split())
    if not name:
        return False
    try:
        from json_normaliser import _key_pattern, normalise_material
        key = str(normalise_material(name) or "").upper()
    except Exception:                                                # noqa: BLE001
        return False
    if key:
        return key in _METAL_KEYS
    return any(_key_pattern(w).search(name) for w in _METAL_WORDS)


def sheet_steel_can_price(material: Any) -> bool:
    """True when the Sheet Steel block's one mild-steel rate is this material's rate: a part
    whose material was never read, or a material the block's steel family covers."""
    name = str(material or "").strip()
    if not name:
        return True
    up = name.upper()
    if any(w in up for w in ("STEEL", "MILD", "CR4", "ZINTEC", "GALV")) \
            and "STAINLESS" not in up:
        return True
    try:
        import config
        key = config.resolve_material_rate_key(name)
        rates = getattr(config, "MATERIAL_PRICE_GBP_PER_KG", {}) or {}
        rate = rates.get(key) if key else None
        l5 = float((getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {})
                   .get("sheet_steel_cost_per_tonne_gbp") or 0.0) / 1000.0
        tol = float(getattr(config, "SHEET_STEEL_RATE_FAMILY_TOLERANCE", 0.5) or 0.5)
    except Exception:                                                # noqa: BLE001
        return False
    if not rate or l5 <= 0:
        return False
    return abs(float(rate) - l5) / l5 <= tol


def sheet_steel_question(part: Dict[str, Any]) -> Optional[str]:
    """The question for a part that reached the Sheet Steel block in a material it cannot price."""
    mat = _stated_material(part) or _charged_material(part)
    if sheet_steel_can_price(mat):
        return None
    pn = str(part.get("part_number") or "—")
    return (f"NOT SHEET STEEL: {pn} is {mat}, and the Sheet Steel block prices every row at "
            f"the mild-steel rate — so it is not charged there. Confirm a price for {mat}")
