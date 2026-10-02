"""
section_profile.py — read a hollow-section profile (and its cut length) off drawing text.

A LEAF MODULE ON PURPOSE. The detector lived in document_builder, which imports the estimator
and half the engine; part_identity and bom_pipeline need the same reading of a parts-list row
("30.00 x 30.00 x 2.00mm TUBE 1532") and could not import document_builder without a cycle.
One reader, moved here unchanged, and document_builder imports it back under its old name —
so the page reader, the parts-list row classifier and the cut-list reader all ask one function
the one question "is this text a section, and how long" (D-383).

Also the one formula for a section's mass per metre, which the estimator's section path and
the cut-list mass check both use: two copies of the cross-section arithmetic are how a round
tube came to be weighed as a square one in one place and not the other.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

__all__ = ["detect_section_stock", "section_kg_per_m"]

# The hollow-section keywords PATH 1 needs. Config (SECTION_HOLLOW_KEYWORDS) since this list
# also decides which parts-list rows are a frame's cut list; this is the default.
_SECTION_HOLLOW_KW_DEFAULT = ("TUBE", "RHS", "SHS", "BOX SECTION", "BOX-SECTION", "HOLLOW SECTION")
try:
    import config as _cfg
    _SECTION_HOLLOW_KW = tuple(str(w).upper() for w in (
        getattr(_cfg, "SECTION_HOLLOW_KEYWORDS", None) or _SECTION_HOLLOW_KW_DEFAULT))
except Exception:                                                # noqa: BLE001
    _SECTION_HOLLOW_KW = _SECTION_HOLLOW_KW_DEFAULT
_SECTION_PROFILE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)(?:\s*MM)?",
    re.IGNORECASE,
)

_PI = 3.141592653589793


def detect_section_stock(text: str) -> Optional[Dict[str, Any]]:
    """Pull a hollow-section profile + cut length from page / cutting-list text.

    Two genuine detection paths, both reading the drawing's own text:

    PATH 1 — canonical cutting-list form, e.g. '30 x 60 x 1.50mm TUBE 1125'.
      Gated on a hollow-section keyword AND a parseable a x b x t profile.
      High confidence.

    PATH 2 — 'WALL'-notation detail form, e.g. a leg detail that states
      '60.0 EXT  30.0 EXT  1.5 WALL ... 1072.0 EXT' with no 'TUBE' keyword and
      no 'AxBxC' string (common on SDI leg/upright detail sheets). The 'n.n WALL'
      callout is an unambiguous tube signal (only hollow sections have a wall
      thickness). Section sides are read as the unqualified 'EXT' dimensions
      adjacent to WALL, EXCLUDING feature callouts tagged FROM TOP / FROM BOTTOM /
      PITCH (those are hole offsets, not section dims), and excluding the large
      (>300mm) EXT which is the cut length. Lower confidence than PATH 1 → carries
      review_section_profile=True so the estimate flags it for human verification.

    Returns None when neither path can read a profile (honest gap — caller flags).
    """
    if not text:
        return None
    up = str(text).upper()

    # ── PATH 1: canonical 'AxBxC <keyword>' ─────────────────────────────────
    if any(kw in up for kw in _SECTION_HOLLOW_KW):
        m = _SECTION_PROFILE_RE.search(up)
        if m:
            dims = sorted(float(m.group(i)) for i in (1, 2, 3))
            wall, side_a, side_b = dims[0], dims[1], dims[2]
            if not (wall <= 0 or wall > 12 or side_a <= wall * 2 or side_b <= wall * 2):
                tail_nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", up[m.end():])]
                length = next((n for n in tail_nums if n >= max(side_a, side_b) * 2), None)
                if length is None:
                    all_nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", up)]
                    cand = [n for n in all_nums if n >= max(side_a, side_b) * 3]
                    length = max(cand) if cand else None
                return {
                    "a": side_a,
                    "b": side_b,
                    "t": wall,
                    "length_mm": length,
                    "profile_form": "SHS" if abs(side_a - side_b) < 1e-6 else "RHS",
                    "keyword": next(kw for kw in _SECTION_HOLLOW_KW if kw in up),
                    "detection_path": "canonical_profile",
                    "source_text": text[m.start():m.start() + 60].strip(),
                }

    # ── PATH 2: 'n.n WALL' notation (no keyword / no AxBxC) ──────────────────
    wm = re.search(r"(\d+(?:\.\d+)?)\s*WALL", up)
    if wm:
        wall = float(wm.group(1))
        if 0 < wall <= 12:
            # All 'EXT' dimensions with any trailing qualifier captured.
            ext_tokens = []  # (value, qualifier)
            for em in re.finditer(r"(\d+(?:\.\d+)?)\s*EXT(\s+(?:FROM\s+\w+|TOP|BOTTOM))?", up):
                ext_tokens.append((float(em.group(1)), (em.group(2) or "").strip()))
            # Section sides: unqualified EXT dims, larger than 2x wall, section-sized (<=300mm).
            side_vals = sorted(
                {v for (v, q) in ext_tokens if not q and wall * 2 < v <= 300},
                reverse=True,
            )[:2]
            # Cut length: the large unqualified EXT (>300mm).
            length_cands = [v for (v, q) in ext_tokens if not q and v > 300]
            if len(side_vals) >= 2:
                side_a, side_b = sorted(side_vals)
                length = max(length_cands) if length_cands else None
                return {
                    "a": side_a,
                    "b": side_b,
                    "t": wall,
                    "length_mm": length,
                    "profile_form": "SHS" if abs(side_a - side_b) < 1e-6 else "RHS",
                    "keyword": "WALL",
                    "detection_path": "wall_notation",
                    "review_section_profile": True,  # less certain than canonical — flag for verify
                    "source_text": text[max(0, wm.start() - 40):wm.start() + 20].strip(),
                }

            # ── PATH 3: ROUND tube — a diameter beside the WALL callout ──────────────
            #
            # ROUND TUBE HAD NO PATH AT ALL, AND IT IS THE COMMONEST TUBE WE BUY.
            #
            # Paths 1 and 2 both need a PAIR of sides: 'a x b x t', or two unqualified EXT
            # dimensions. A round tube has one dimension and a wall, so both fall through and
            # return None — no section, no tube stock form, no saw and no weld.
            #
            # M&S 2085 is exactly this. Its GA reads "12.7  1.2 WALL" for the outer tube and
            # "10.0" for the inner (12.7 less two 1.2 walls is a 10.3 bore — they telescope).
            # Neither tube got a section, so neither reached the labour path, and a welded
            # three-part bracket booked GBP 2.00 of labour with no operation against either.
            #
            # The rule is the same one PATH 2 uses, with one dimension instead of two: a wall
            # thickness only exists on hollow section, and the number beside it is the size.
            # Reached only when PATH 2 could not find a pair, so a rectangular section is never
            # read as round. Flagged for verification like PATH 2 — this is a reading of a
            # layout convention, not a printed section callout.
            _before = up[max(0, wm.start() - 30):wm.start()]
            _dia_nums = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)", _before)]
            _dia = next((d for d in reversed(_dia_nums) if wall * 2 < d <= 300), None)
            if _dia:
                return {
                    # a and b are the OUTSIDE DIAMETER. Anything reading them as the sides of
                    # a square gets a cross-section 27% too big, so profile_form is not
                    # decoration — the mass calculation switches on it.
                    "a": _dia,
                    "b": _dia,
                    "t": wall,
                    "outside_diameter_mm": _dia,
                    "length_mm": None,
                    "profile_form": "CHS",
                    "keyword": "WALL",
                    "detection_path": "round_wall_notation",
                    "review_section_profile": True,
                    "source_text": text[max(0, wm.start() - 40):wm.start() + 20].strip(),
                }

    return None


def section_kg_per_m(a: Any, b: Any, t: Any, profile_form: Any = "",
                     density_kg_m3: Optional[float] = None) -> Optional[float]:
    """Mass per metre of a hollow section, or None when the profile cannot be weighed.

    A ROUND TUBE IS NOT A SQUARE ONE: CHS carries its outside diameter in a and b, and its
    area is the annulus, not outer square less inner square (27% heavy on a 12.7 x 1.2).
    The density is the caller's (config.MATERIAL_DENSITY_KG_PER_M3 for the part's material);
    steel when none is given. One formula for every reader that weighs a section."""
    try:
        a_f, b_f, t_f = float(a), float(b), float(t)
    except (TypeError, ValueError):
        return None
    if a_f <= 0 or b_f <= 0 or t_f <= 0:
        return None
    inner_a = max(0.0, a_f - 2.0 * t_f)
    inner_b = max(0.0, b_f - 2.0 * t_f)
    if str(profile_form or "").upper() == "CHS":
        area_mm2 = max(0.0, _PI / 4.0 * ((a_f ** 2) - (inner_a ** 2)))
    else:
        area_mm2 = max(0.0, (a_f * b_f) - (inner_a * inner_b))
    try:
        dens = float(density_kg_m3) if density_kg_m3 else 7850.0
    except (TypeError, ValueError):
        dens = 7850.0
    return (area_mm2 * dens) / 1_000_000.0
