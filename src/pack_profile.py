"""Which convention a drawing pack speaks, decided once, from evidence.

0359342 (M&S Edition Sunglasses Stand) is the job this exists for: a 79-page PDF-only
pack whose BOM tables are the customer's, keyed by the GA's own drawing number (A61636)
rather than the SDI job number, with no SolidWorks model and no DXF anywhere in the
folder. Run through the structured-pack assumptions it collapsed structurally — the
stated root was refused (twelve top-level rows orphaned, the x2 back-panel cascade
lost), and the document's general finish note became per-part operations.

The rule of this module is the reviewer's: KEEP CUSTOMER-SPECIFIC PARSING ISOLATED, FIX
INTEGRITY FAILURES GENERICALLY. A pack is classified once, from what is in it — never
from a customer name — and every relaxation the foreign mode allows is gated on that
classification, so a structured SDI pack can never enter by accident. The one signal
that matters most is negative: ANY model or DXF evidence anywhere in the job means the
structured readers have real geometry to stand on, and this module answers "structured"
without looking further.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

# ── pack modes ───────────────────────────────────────────────────────────────────────
STRUCTURED = "structured"      # SDI convention: models/DXFs/deterministic BOM — lane A
PDF_PRIMARY = "pdf_primary"    # foreign convention: PDF tables are the only structure


def detect_pack_mode(summary: Optional[Mapping[str, Any]]) -> str:
    """One verdict per job, from the pack's own contents.

    PDF_PRIMARY requires ALL of:
      - BOM rows that STATE ownership (a bom_parent on the row) — the table structure
        this mode exists to honour. No stated ownership, nothing to honour: structured.
      - NO DXF anywhere in the job — not matched, not skipped, not stray. A DXF in the
        pack means the structured flat-pattern readers have something real to measure.
      - NO part carrying model geometry (solidworks/dxf geometry_source, a DXF
        augmentation, a native flat verdict).

    Anything else is STRUCTURED, which is the mode every existing job already runs in —
    the default answer changes nothing for lane A.
    """
    if not isinstance(summary, Mapping):
        return STRUCTURED
    da = summary.get("document_analysis") or {}
    _rows = list(da.get("bom_rows") or []) + list(da.get("bay_bom_rows") or [])
    _stated = [r for r in _rows if isinstance(r, Mapping)
               and str(r.get("bom_parent") or r.get("parent") or "").strip()]
    if not _stated:
        return STRUCTURED
    dxf = summary.get("dxf_augmentation")
    if isinstance(dxf, Mapping) and any(dxf.get(k) for k in dxf):
        return STRUCTURED
    for _pool in (summary.get("parts"),
                  (summary.get("manufacturing_writeup") or {}).get("parts")):
        for p in (_pool or []):
            if not isinstance(p, Mapping):
                continue
            gs = str(p.get("geometry_source") or "").lower()
            if ("dxf" in gs or "solidworks" in gs or "native" in gs
                    or p.get("dxf_augmented") or p.get("native_flat_solid")):
                return STRUCTURED
    return PDF_PRIMARY


# ── the family map: config, not inference ────────────────────────────────────────────
# The reviewer's table for 0359342, held as data so the next foreign pack edits a tuple
# rather than a rule. Material tokens are matched as words against the part's own
# material/description text; code stems are matched against the part number. "LAMAINATE"
# is the drawing's own spelling, kept deliberately — the map must match the evidence as
# written, not as it should have been written.
JOINERY_MATERIAL_TOKENS = (
    "MDF", "FLEXI MDF", "FLEXIMDF", "LAMINATE", "LAMAINATE", "PLYWOOD", "PLY",
    "TIMBER", "BIRCH", "OAK", "CHIPBOARD",
)
BOUGHT_IN_MATERIAL_TOKENS = (
    "CORIAN", "SOLID SURFACE", "MIRROR", "VINYL", "GLASS", "STICKER", "GRAPHIC",
)
METAL_MATERIAL_TOKENS = (
    "STEEL", "CR4", "MILD WIRE", "MILD STEEL", "STAINLESS", "ALUMINIUM", "ZINTEC",
)
BOUGHT_IN_CODE_STEMS = ("RM", "R0", "BI-")
BOUGHT_IN_CODE_EXACT = ("TBA",)
BOUGHT_IN_BRAND_TOKENS = ("HAFELE", "ESSENTRA", "ROSS", "VITAL PARTS")

JOINERY = "joinery"
BOUGHT_IN = "bought_in"
METAL = "metal"
UNKNOWN = ""


def _has_token(text: str, tokens) -> bool:
    up = f" {re.sub(r'[^A-Z0-9]+', ' ', str(text).upper())} "
    return any(f" {t} " in up or (" " in t and t in up) for t in tokens)


def family_for(material_text: Any = "", part_number: Any = "",
               description: Any = "") -> str:
    """joinery / bought_in / metal / '' for one part, from ITS OWN evidence only.

    Order matters and is deliberate. A code stem that says "purchased" wins over any
    material word — an RM-coded steel screw is a catalogue fastener, not a laser part,
    and pricing it off a sheet-steel page is the exact 0359342 defect this exists to
    stop. Then the MATERIAL text is consulted fully before the description ever is:
    MBY439 is "Edition Sunglasses Mirror Plate" in "Mild Steel CR4", and a rule that
    reads both fields as one string ships a steel plate to the glazier because its NAME
    contains Mirror. No evidence returns '' — the caller must treat unknown as unknown,
    never default it into a route.
    """
    pn = str(part_number or "").strip().upper()
    if pn in BOUGHT_IN_CODE_EXACT or any(pn.startswith(s) for s in BOUGHT_IN_CODE_STEMS):
        return BOUGHT_IN
    if _has_token(f"{material_text or ''} {description or ''}", BOUGHT_IN_BRAND_TOKENS):
        return BOUGHT_IN
    for _text in (material_text, description):
        if not str(_text or "").strip():
            continue
        if _has_token(_text, BOUGHT_IN_MATERIAL_TOKENS):
            return BOUGHT_IN
        if _has_token(_text, JOINERY_MATERIAL_TOKENS):
            return JOINERY
        if _has_token(_text, METAL_MATERIAL_TOKENS):
            return METAL
    return UNKNOWN
