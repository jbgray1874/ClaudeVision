"""
source_connectors/solidworks.py — normalise the SolidWorks native extract into the
shapes the estimator/reconcile consume. This is Layer 0 (highest reliability) of the
source waterfall: for SDI's own designs the native model is ground truth for BOM
structure + quantities + material; DXF stays authoritative for flat geometry (holes,
cut length) and PDF for free-text notes.

Input: the JSON written by tools/solidworks/sw_native_analyse.py (`_sw_native_extract.json`),
a list of per-file records: {path, title, doctype (1 part/2 asm/3 drw), custom_properties,
bbox_mm, bom:[...], route_signals:{...}|null, errors}.

This module does NOT open SolidWorks. It reads the extract JSON (optionally triggering
the analyser as a subprocess on a machine that has SW). Pure field-mapping — no per-job
or per-part logic — so it scales to any job the analyser can read.

Public surface:
    load_native_extract(json_path)                 -> list[dict]  (raw records)
    normalize_native_extract(records)              -> NativeJob   (bom + part_signals + meta)
    native_extract_for_job(folder=..., json=...,
                           run=False, analyser=...) -> NativeJob | None
    apply_native_to_pre_estimate(parts, job)       -> counts      (BEFORE costing)
    apply_native_to_part_estimates(summary, job)   -> counts      (AFTER costing, reconcile)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE_NAME = "solidworks_api"
RELIABILITY = 1.0
EXTRACT_FILENAME = "_sw_native_extract.json"

# Stamped on a part whose blank came from the SolidWorks sheet-metal cut list. This is a
# MEASURED flat pattern — the same class of truth as a DXF flat, from the model that
# produced the DXF — so the engine's measured-geometry gates must recognise it. It is a
# DISTINCT token from the DXF ones: nothing here pretends a DXF exists.
NATIVE_GEOMETRY_SOURCE = "solidworks_flat_pattern"

# Doc types (mirror the analyser).
SW_PART, SW_ASM, SW_DRW = 1, 2, 3

# Assembly description/title tokens that indicate a WELDED assembly (not bolt-together).
# The native model does not always flag weld intent structurally, so — like the engine's
# existing _ASSEMBLY_WELD_PHRASES — we read it from the name/description. Weld-bead feature
# detection on assemblies is a planned refinement; until then a match is a FLAGGED
# candidate, never a silent assertion.
_WELD_NAME_TOKENS = ("weld assy", "weld assembly", "welded", "weldment", "wa0", "wa1", "-wa", "sa0")


def _clean_pn(name: str) -> str:
    """Normalise a part number for matching. The analyser already strips SolidWorks
    instance suffixes (it emits clean document titles), so we do NOT strip here — that
    would wrongly turn '12120-01-103' into '12120-01'. Just trim/upper-safe compare."""
    return str(name or "").strip()


def _num(v: Any) -> Optional[float]:
    """Tolerant numeric read. The analyser writes floats, but cut-list values arrive as
    strings ('126.39') from the SolidWorks property store, so accept both."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


# Blank-dimension sanity window, matched to the engine's own BLANK_DIMENSION_POLICY
# defaults. A cut-list value outside it is not used (and is flagged) rather than costed.
_MIN_BLANK_MM, _MAX_BLANK_MM = 1.0, 2500.0
_MIN_THK_MM, _MAX_THK_MM = 0.3, 50.0


def _plausible_mm(v: Optional[float]) -> bool:
    return v is not None and _MIN_BLANK_MM <= v <= _MAX_BLANK_MM


def _plausible_thk(v: Optional[float]) -> bool:
    return v is not None and _MIN_THK_MM <= v <= _MAX_THK_MM


@dataclass
class NativePart:
    part_number: str
    material: str = ""
    is_sheet_metal: bool = False
    bend_count: int = 0
    hole_count_est: int = 0
    flat_pattern: bool = False
    has_weldment: bool = False
    bbox_mm: Optional[List[float]] = None
    doctype: int = SW_PART
    # ── measured cut-list geometry (the estimating prize a PDF cannot supply) ──
    flat_length_mm: Optional[float] = None
    flat_width_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    bend_radius_mm: Optional[float] = None
    cut_length_mm: Optional[float] = None
    cut_out_count: Optional[int] = None
    blank_area_mm2: Optional[float] = None
    surface_treatment: str = ""
    mass_kg: Optional[float] = None
    # Formed solid whose bends are baked into a Base Flange sketch (no countable bend
    # feature). Real folds, un-counted — flagged so the fold op still fires.
    formed_but_no_bend_features: bool = False
    # Imported body with no modelled fabrication features = supplier model = bought in.
    likely_bought_in: bool = False
    ops_hint: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    description: str = ""
    source: str = SOURCE_NAME
    reliability: float = RELIABILITY

    def has_flat(self) -> bool:
        return bool(_plausible_mm(self.flat_length_mm) and _plausible_mm(self.flat_width_mm))


@dataclass
class NativeBomRow:
    part_number: str
    quantity: float = 1.0
    material: str = ""
    is_assembly: bool = False
    weld_candidate: bool = False
    source: str = SOURCE_NAME
    reliability: float = RELIABILITY
    flags: List[str] = field(default_factory=list)


@dataclass
class NativeJob:
    bom: List[NativeBomRow] = field(default_factory=list)          # top-assembly flattened BOM
    part_signals: Dict[str, NativePart] = field(default_factory=dict)  # by part number
    assembly_pns: List[str] = field(default_factory=list)          # every .SLDASM in the pack
    meta: Dict[str, Any] = field(default_factory=dict)
    found: bool = False

    def material_for(self, part_number: str) -> str:
        p = self.part_signals.get(_clean_pn(part_number))
        return p.material if p else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "meta": self.meta,
            "bom": [vars(r) for r in self.bom],
            "part_signals": {k: vars(v) for k, v in self.part_signals.items()},
        }


# ── loading ──────────────────────────────────────────────────────────────────
def load_native_extract(json_path: str | Path) -> List[Dict[str, Any]]:
    jp = Path(json_path)
    if not jp.exists():
        return []
    try:
        data = json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _reject_folded_box_as_flat(p: NativePart) -> None:
    """Drop a 'flat pattern' that is really the part's FOLDED bounding box.

    A folded part's DEVELOPED blank must be LARGER than the envelope it folds into —
    material is consumed going round each bend. So when a part with bends reports a flat
    equal to its own bounding box, the cut-list read returned the folded box: a real
    number, but the wrong one, and smaller than the truth. Costing it UNDER-BUYS material.

    PRECAUTIONARY, not observed. It was written believing 12120-01-01M had failed this
    way; fuller extraction showed it had not — 01M's folded solid is 79x64.5x21.5 and its
    cut-list flat of 126.39x82.2 is a genuine developed blank, correctly far larger. The
    guard stays because the geometry it asserts is sound and the analyser's own 'a flat
    cannot be smaller than the solid' gate passes a folded box by construction, so nothing
    else would catch it. It is inert on every 12120 part. Applied at normalisation so it
    also protects extracts already on disk, without re-running SolidWorks.

    Keyed on bend evidence and geometry only — no part numbers, no job specifics."""
    if not (p.flat_length_mm and p.flat_width_mm and p.bbox_mm):
        return
    if not (p.bend_count or p.formed_but_no_bend_features):
        return  # a genuinely flat part's blank SHOULD equal its bounding box
    try:
        dims = [float(x) for x in p.bbox_mm if x]
        flat = [float(p.flat_length_mm), float(p.flat_width_mm)]
    except (TypeError, ValueError):
        return
    if len(dims) < 2:
        return
    # Do BOTH flat sides coincide with a bounding-box dimension? Match against ANY axis, not
    # the two largest: a folded part's height often exceeds its footprint width (01M is
    # 126.39 x 82.2 x 90 — the 90 is the upstand). Each bbox dimension is consumed once, so
    # a single 90mm side cannot satisfy a 90 x 90 flat.
    _avail = list(dims)
    for f in flat:
        hit = next((d for d in _avail if abs(f - d) <= max(0.5, d * 0.01)), None)
        if hit is None:
            return  # at least one side is genuinely developed — a real flat pattern
        _avail.remove(hit)
    p.notes.append(
        f"REJECTED flat {p.flat_length_mm:g}x{p.flat_width_mm:g}mm — part is FOLDED "
        f"({p.bend_count or 'formed'}) yet both sides of the reported flat match its folded "
        f"bounding box ({'x'.join(f'{d:g}' for d in dims)}mm). That is the folded envelope, "
        f"not a developed blank; using it would under-buy material")
    p.flat_length_mm = None
    p.flat_width_mm = None
    # Same read, same doubt: cut length came from the same property set.
    p.cut_length_mm = None


def _is_weld_candidate(title: str, description: str) -> bool:
    blob = f"{title} {description}".lower()
    return any(tok in blob for tok in _WELD_NAME_TOKENS)


def _pick_top_assembly(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The job's top assembly = the assembly record with the largest (full-depth) BOM.
    Generic — no reliance on a '-GA' naming convention, though that usually wins anyway."""
    asms = [r for r in records if r.get("doctype") == SW_ASM and r.get("bom")]
    if not asms:
        return None
    return max(asms, key=lambda r: len(r.get("bom") or []))


# ── normalisation ────────────────────────────────────────────────────────────
def normalize_native_extract(records: List[Dict[str, Any]]) -> NativeJob:
    job = NativeJob()
    if not records:
        return job
    job.found = True

    # Per-part signals from every part record's route_signals (material + geometry).
    doctype_by_pn: Dict[str, int] = {}
    for r in records:
        pn = _clean_pn(r.get("title") or "")
        if not pn:
            continue
        doctype_by_pn[pn] = int(r.get("doctype") or SW_PART)
        rs = r.get("route_signals")
        if not isinstance(rs, dict):
            continue
        job.part_signals[pn] = NativePart(
            part_number=pn,
            material=str(rs.get("material") or ""),
            is_sheet_metal=bool(rs.get("is_sheet_metal")),
            bend_count=int(rs.get("bend_count") or 0),
            hole_count_est=int(rs.get("hole_count_est") or 0),
            flat_pattern=bool(rs.get("flat_pattern_present")),
            has_weldment=bool(rs.get("has_weldment")),
            bbox_mm=rs.get("bbox_mm"),
            doctype=int(r.get("doctype") or SW_PART),
            flat_length_mm=_num(rs.get("flat_length_mm")),
            flat_width_mm=_num(rs.get("flat_width_mm")),
            thickness_mm=_num(rs.get("thickness_mm")),
            bend_radius_mm=_num(rs.get("bend_radius_mm")),
            cut_length_mm=_num(rs.get("cut_length_mm")),
            blank_area_mm2=_num(rs.get("blank_area_mm2")),
            surface_treatment=str(rs.get("surface_treatment") or ""),
            mass_kg=_num(rs.get("mass_kg")),
            formed_but_no_bend_features=bool(rs.get("formed_but_no_bend_features")),
            likely_bought_in=bool(rs.get("likely_bought_in")),
            ops_hint=[str(o) for o in (rs.get("ops_hint") or [])],
        )
        _reject_folded_box_as_flat(job.part_signals[pn])

    # Every document that is itself an assembly — the GA double-count rule keys on this.
    asm_titles = {
        _clean_pn(r.get("title") or "")
        for r in records
        if int(r.get("doctype") or SW_PART) == SW_ASM and _clean_pn(r.get("title") or "")
    }
    job.assembly_pns = sorted(asm_titles)

    # BOM = the top assembly's full-depth component list, quantities already rolled up.
    top = _pick_top_assembly(records)
    if top:
        job.meta["top_assembly"] = top.get("title")
        for line in (top.get("bom") or []):
            pn = _clean_pn(line.get("part_number") or "")
            if not pn:
                continue
            dt = doctype_by_pn.get(pn, SW_PART)
            # A BOM line is an ASSEMBLY when either its own document is one, or it appears
            # as the top of somebody's component list. The analyser's BOM is FULL-DEPTH, so
            # every sub-assembly AND its children are listed: the assembly line therefore
            # must never be costed for material — its content is already on the child rows.
            # This is the GA double-count rule, keyed on document type, not on naming.
            is_asm = (dt == SW_ASM) or pn in asm_titles
            desc = str(line.get("description") or "")
            weld = is_asm and _is_weld_candidate(pn, desc)
            # Material: prefer the part's own applied material (BOM lines carry none).
            mat = job.material_for(pn) or str(line.get("material") or "")
            # The analyser emits `qty` (BomLine.qty); tolerate `quantity` from any other
            # producer of this JSON. Reading only 'quantity' silently pinned every row to 1.
            _q = _num(line.get("qty"))
            if _q is None:
                _q = _num(line.get("quantity"))
            row = NativeBomRow(
                part_number=pn,
                quantity=float(_q) if _q and _q > 0 else 1.0,
                material=mat,
                is_assembly=is_asm,
                weld_candidate=weld,
            )
            if desc:
                row.flags.append(f"desc: {desc}")
            if weld:
                row.flags.append("weld-assembly candidate (from name) — confirm weld/dress")
            job.bom.append(row)
            # Carry the BOM description onto the part signal for downstream display.
            sig = job.part_signals.get(pn)
            if sig is not None and desc and not sig.description:
                sig.description = desc

    job.meta["counts"] = {
        "records": len(records),
        "parts_with_signals": len(job.part_signals),
        "bom_rows": len(job.bom),
        "weld_candidates": sum(1 for r in job.bom if r.weld_candidate),
        "material_coverage": sum(1 for p in job.part_signals.values() if p.material),
        "flat_pattern_coverage": sum(1 for p in job.part_signals.values() if p.has_flat()),
        "thickness_coverage": sum(1 for p in job.part_signals.values()
                                  if _plausible_thk(p.thickness_mm)),
        "bought_in": sum(1 for p in job.part_signals.values() if p.likely_bought_in),
    }
    return job


# ── job entry point ──────────────────────────────────────────────────────────
def native_extract_for_job(
    *,
    folder: Optional[str | Path] = None,
    json_path: Optional[str | Path] = None,
    run: bool = False,
    analyser: Optional[str | Path] = None,
    python_exe: Optional[str] = None,
) -> Optional[NativeJob]:
    """Resolve + normalise the native extract for a job.

    - json_path given            -> read it.
    - folder given               -> read <folder>/_sw_native_extract.json; if absent and
                                     run=True, invoke the analyser (needs SolidWorks) then read.
    Returns a NativeJob (found=False if nothing native is available — the caller then
    falls back cleanly to the PDF/DXF path)."""
    jp: Optional[Path] = Path(json_path) if json_path else None
    if jp is None and folder is not None:
        jp = Path(folder) / EXTRACT_FILENAME

    if jp is not None and not jp.exists() and run and folder is not None:
        _run_analyser(folder, analyser=analyser, python_exe=python_exe)

    records = load_native_extract(jp) if jp else []
    job = normalize_native_extract(records)
    job.meta.setdefault("extract_path", str(jp) if jp else None)
    return job


def _run_analyser(folder: str | Path, analyser: Optional[str | Path] = None,
                  python_exe: Optional[str] = None) -> None:
    """Invoke sw_native_analyse.py on a folder (Windows + SolidWorks only). Best-effort:
    failures leave no JSON and the caller falls back to PDF/DXF."""
    if analyser is None:
        analyser = Path(__file__).resolve().parents[2] / "tools" / "solidworks" / "sw_native_analyse.py"
    exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or "python"
    try:
        subprocess.run([exe, str(analyser), str(folder)], check=False, timeout=1800)
    except Exception:
        pass


# ── material normalisation ───────────────────────────────────────────────────
# SolidWorks library material names ("Plain Carbon Steel", "AISI 304", "6061 Alloy") do
# not look like the title-block wording the engine's normaliser was written for, so map
# the library families FIRST and fall back to the shared text normaliser. Keyed on family
# tokens, so it covers any SW material library, not one job's picks.
_SW_MATERIAL_FAMILIES = (
    ("STAINLESS_STEEL", ("AISI 304", "AISI 316", "AISI 321", "AISI 302", "AISI 201",
                         "STAINLESS", "1.4301", "1.4307", "1.4401", "1.4404", "316L", "304L")),
    ("ALUMINIUM",       ("ALUMINI", "ALUMINU", "6061", "6082", "5251", "5052", "1050",
                         "1060 ALLOY", "7075", "ALLOY 5", "ALLOY 6")),
    ("GALVANISED_STEEL", ("GALVANIS", "GALVANIZ", "GALVA")),
    ("ZINTEC",          ("ZINTEC", "ZINC COATED STEEL")),
    ("MILD_STEEL",      ("PLAIN CARBON STEEL", "CAST CARBON STEEL", "ALLOY STEEL",
                         "AISI 1020", "AISI 1035", "AISI 1045", "CARBON STEEL",
                         "CR4", "DC01", "S275", "S355", "MILD STEEL")),
    ("BRASS",           ("BRASS",)),
    ("COPPER",          ("COPPER",)),
    ("ACRYLIC",         ("ACRYLIC", "PMMA", "PERSPEX", "PLEXIGLAS")),
    ("PVC",             ("PVC",)),
    ("ABS",             ("ABS ",)),
    ("NYLON",           ("NYLON", "PA6", "PA 6")),
    ("POLYCARBONATE",   ("POLYCARB", "LEXAN")),
    ("MDF",             ("MDF",)),
    ("PLYWOOD",         ("PLYWOOD", "PLY WOOD")),
    ("TIMBER",          ("OAK", "PINE", "BEECH", "BIRCH", "BALSA", "MAPLE", "TEAK",
                         "SPRUCE", "SOFTWOOD", "HARDWOOD", "TIMBER")),
)


def _norm_sw_material(raw: str) -> str:
    u = str(raw or "").upper().strip()
    if not u:
        return ""
    for family, tokens in _SW_MATERIAL_FAMILIES:
        if any(t in u for t in tokens):
            return family
    # Fall back to the shared title-block normaliser so both source paths agree on
    # family naming; if it recognises nothing it returns the raw string unchanged.
    try:
        from .llm_full_job import _norm_material  # same package, no heavy imports
        return _norm_material(raw)
    except Exception:
        return u


_METAL_FAMILIES = {"MILD_STEEL", "STAINLESS_STEEL", "ALUMINIUM", "ZINTEC",
                   "GALVANISED_STEEL", "BRASS", "COPPER"}
_NON_METAL_FAMILIES = {"TIMBER", "MDF", "PLYWOOD", "ACRYLIC", "HIPS", "PVC", "ABS",
                       "NYLON", "POLYCARBONATE", "FOAMEX"}
# Operations the engine actually costs. The analyser's ops_hint vocabulary is aligned to
# this, but we filter anyway so a new hint can never invent a route the engine misprices.
_KNOWN_OPS = {"laser_cutting", "folding", "hole_machining", "welding", "dress_welds",
              "powder_coating", "wet_spray", "diamond_polish", "cnc_routing", "glue"}


def _pn_key(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or "")).upper()


def _match_native(part: Dict[str, Any], exact: Dict[str, str],
                  tail: Dict[str, str]) -> Optional[str]:
    """Resolve a pre-estimate part to a native part number. Exact (whitespace/case
    insensitive) first; then a UNIQUE trailing-segment match, which covers the common
    case where the PDF prints '01M' against the model's '12120-01-01M'. Ambiguous tails
    are refused — a wrong match would put one part's geometry on another."""
    pk = _pn_key(part.get("part_number"))
    if not pk:
        return None
    if pk in exact:
        return exact[pk]
    return tail.get(pk)


def _has_costable_geometry(part: Dict[str, Any]) -> bool:
    """True when SOMETHING in the record can produce a material cost: a blank, a stated
    weight, or a bought section. Used by the flag-don't-zero guard."""
    ng = part.get("normalized_geometry") or {}
    if _num(ng.get("blank_length_mm")) and _num(ng.get("blank_width_mm")):
        return True
    if _num(part.get("blank_length_mm")) and _num(part.get("blank_width_mm")):
        return True
    if _num(part.get("overall_length_mm")) and _num(part.get("overall_width_mm")):
        return True
    if _num(part.get("stated_weight_g")):
        return True
    ss = part.get("section_stock")
    if isinstance(ss, dict) and _num(ss.get("length_mm")):
        return True
    return False


def _dxf_blank_mm(part: Dict[str, Any]):
    """The DXF's DEVELOPED blank, in the order the engine itself resolves it.

    Critically this must NEVER fall back to overall_length_mm/overall_width_mm. On a folded
    part those carry the FORMED bounding box, not the blank (12120-01-01M: overall
    126.39x82.2 formed, developed blank 132.39x88.2). Comparing a flat against a folded box
    would report a false 'agreement' on exactly the parts where it matters most."""
    ng = part.get("normalized_geometry") or {}
    if not isinstance(ng, dict):
        return None, None
    l = _num(ng.get("blank_length_mm")) or _num(part.get("blank_length_mm"))
    w = _num(ng.get("blank_width_mm")) or _num(part.get("blank_width_mm"))
    if l and w:
        return l, w
    box = ng.get("bounding_box_flat_mm")
    if isinstance(box, dict):
        l, w = _num(box.get("length")), _num(box.get("width"))
        if l and w:
            return l, w
    l = _num(ng.get("developed_length_mm"))
    w = _num(ng.get("developed_width_mm"))
    if l and w:
        return l, w
    return None, None


def _dxf_backed(part: Dict[str, Any]) -> bool:
    """The engine's own definition of a DXF-measured part (estimator.py). DXF stays
    authoritative for flat geometry — native never overwrites it, only cross-checks."""
    return (
        "dxf" in str(part.get("geometry_source") or "").lower()
        or bool(part.get("dxf_augmented"))
        or bool(part.get("dxf_source_file"))
    )


def apply_native_to_pre_estimate(parts: List[Dict[str, Any]], job: NativeJob) -> Dict[str, int]:
    """Fold the SolidWorks native extract into the PRE-ESTIMATE part records — i.e. BEFORE
    costing — so the engine's existing paths fire with modelled truth instead of inferred
    or vision-derived values. Mirrors llm_full_job.apply_full_job_to_pre_estimate but sits
    ABOVE it in the waterfall (native > DXF > deterministic PDF > LLM).

    What it sets, and the rule for each:
      GEOMETRY   flat blank L/W + thickness from the sheet-metal CUT LIST. Written only
                 where the part is NOT already DXF-backed; where it IS, native is compared
                 and any material disagreement is FLAGGED (free QA, no silent overwrite).
      MATERIAL   the model's applied material. Fills a gap always; overrides only an
                 engine metal default that native contradicts (metal <-> non-metal).
                 A metal-to-metal disagreement is flagged, not silently changed — the
                 printed title block is what the shop buys to.
      BENDS      bend_count, or a fold flag where the solid is demonstrably formed but the
                 bends are baked into a Base Flange sketch (under-counted by feature scan).
      QUANTITY   the full-depth BOM roll-up.
      STRUCTURE  assembly rows are marked as parents so their material is NOT costed twice
                 (the GA double-count rule); imported supplier bodies are marked bought-in
                 so they take no fabrication route.

    FLAG, NEVER ZERO: if native gives a part a material but the record still has no
    costable geometry, the part is flagged loudly rather than left to cost at £0. A £0
    line that looks priced is the failure mode this guard exists to prevent.

    Returns counts of what changed. Non-destructive everywhere else.
    """
    out = {"flat": 0, "thickness": 0, "material": 0, "material_conflict": 0, "bends": 0,
           "qty": 0, "assembly_parent": 0, "bought_in": 0, "weld_flagged": 0,
           "ops": 0, "mass": 0, "no_geometry_flagged": 0, "geometry_conflict": 0,
           "geometry_unchecked": 0, "not_in_bom": 0, "rejected_values": 0,
           "finish": 0}
    if not job or not job.found or not isinstance(parts, list):
        return out

    exact = {_pn_key(pn): pn for pn in job.part_signals}
    for r in job.bom:
        exact.setdefault(_pn_key(r.part_number), r.part_number)
    # The TOP assembly is not a line in its own BOM, so index the assembly documents too.
    # Without this the GA row falls through and gets costed as if it were a leaf part —
    # the single largest over-count this connector exists to stop.
    asm_keys = {_pn_key(a) for a in job.assembly_pns}
    for a in job.assembly_pns:
        exact.setdefault(_pn_key(a), a)
    # Unique trailing-segment index ('12120-01-01M' -> '01M'), built only from keys that
    # are unambiguous; a tail claimed by two parts is dropped from the index entirely.
    _tail_hits: Dict[str, List[str]] = {}
    for k, pn in exact.items():
        seg = k.rsplit("-", 1)[-1]
        if seg and seg != k:
            _tail_hits.setdefault(seg, []).append(pn)
    tail = {k: v[0] for k, v in _tail_hits.items() if len(v) == 1 and k not in exact}

    bom_by_pn = {_pn_key(r.part_number): r for r in job.bom}

    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = _match_native(part, exact, tail)
        if not pn:
            continue
        nat = job.part_signals.get(pn)
        row = bom_by_pn.get(_pn_key(pn))
        part["solidworks_native"] = True
        part["solidworks_part_number"] = pn
        flags = part.setdefault("review_flags", [])

        # ── STRUCTURE: assembly row -> parent, never costed for material ──────────
        # The native BOM is FULL DEPTH: a sub-assembly and all of its children appear.
        # Costing both double-counts every gram. Mark the parent; the engine already
        # suppresses material on is_assembly_parent / is_sub_assembly records.
        _is_asm = _pn_key(pn) in asm_keys or (row is not None and row.is_assembly)
        if _is_asm:
            part["is_assembly_parent"] = True
            part["is_sub_assembly"] = True
            flags.append("SolidWorks: assembly — its parts are costed on their own rows "
                         "(material suppressed here to avoid double-counting)")
            out["assembly_parent"] += 1
            if (row is not None and row.weld_candidate) or _is_weld_candidate(pn, ""):
                flags.append("SolidWorks: welded sub-assembly (from name) — confirm weld/dress route")
                out["weld_flagged"] += 1

        # ── QUANTITY: full-depth BOM roll-up ─────────────────────────────────────
        if row is not None and row.quantity and row.quantity > 0:
            _q = int(round(row.quantity))
            _cur = _num(part.get("quantity"))
            if _q > 0 and (_cur is None or int(_cur) != _q):
                part["quantity"] = _q
                flags.append(f"qty {_cur if _cur is not None else '-'} -> {_q} from the "
                             f"SolidWorks assembly BOM (component count, all levels)")
                out["qty"] += 1

        # ── NOT IN THE ASSEMBLY BOM ──────────────────────────────────────────────
        # A modelled part that appears in no assembly is not a component of the product:
        # a fixture, a jig, a setup block (e.g. a 500x500 setup part sitting in the job
        # folder). Flag it rather than drop it — a BOM the analyser failed to read would
        # otherwise silently delete real parts. Only fires when the BOM is substantial
        # enough to prove it was read, so a failed read cannot mislabel a whole job.
        if row is None and not _is_asm and len(job.bom) >= 3:
            part["not_in_assembly_bom"] = True
            flags.append("SolidWorks: this part appears in NO assembly BOM — a fixture, jig "
                         "or setup part, not a component of the product. Confirm before "
                         "costing it into the job")
            out["not_in_bom"] += 1

        if nat is None:
            continue

        # ── SURFACE THE ANALYSER'S OWN REJECTIONS ────────────────────────────────
        # A value the geometry gates threw out (a folded box read as a flat, an impossible
        # thickness) must reach the estimator. Discarding it silently leaves the part
        # looking merely un-measured, when in fact we READ something and judged it wrong —
        # which is a different thing, and the estimator needs to know which.
        for _n in nat.notes:
            if _n not in flags:
                flags.append(f"SolidWorks: {_n}")
                if "REJECTED" in _n:
                    out["rejected_values"] += 1

        # ── BOUGHT-IN: imported body, no modelled fabrication ────────────────────
        if nat.likely_bought_in:
            roles = part.setdefault("page_roles", [])
            if "bought_in" not in [str(r).lower() for r in roles]:
                roles.append("bought_in")
            part["is_bought_in"] = True
            flags.append("SolidWorks: imported supplier model with no fabrication features "
                         "— bought-in component, no fabrication route applied")
            out["bought_in"] += 1
            # A bought-in part takes no flat/fold/coat route; skip the fabrication fields.
            continue

        # ── MATERIAL ─────────────────────────────────────────────────────────────
        if nat.material:
            new_mat = _norm_sw_material(nat.material)
            cur_mat = str(part.get("normalized_material") or "").strip().upper()
            if new_mat and not cur_mat:
                part["normalized_material"] = new_mat
                part["material_source"] = SOURCE_NAME
                flags.append(f"material '{new_mat}' from the SolidWorks model "
                             f"(applied material: {nat.material})")
                out["material"] += 1
            elif new_mat and cur_mat and new_mat != cur_mat:
                _cross_family = (
                    (new_mat in _NON_METAL_FAMILIES and cur_mat in _METAL_FAMILIES)
                    or (new_mat in _METAL_FAMILIES and cur_mat in _NON_METAL_FAMILIES)
                )
                if _cross_family:
                    # A wood/board part is definitively not steel (and vice versa). The
                    # model is authoritative on what the designer specified — override
                    # the engine's family default and say so.
                    part["normalized_material"] = new_mat
                    part["material_source"] = SOURCE_NAME
                    flags.append(f"material '{cur_mat}' overridden to '{new_mat}' from the "
                                 f"SolidWorks model ('{nat.material}') — wrong material FAMILY")
                    out["material"] += 1
                else:
                    # Same family, different grade. The printed title block is what the
                    # shop buys to, so keep it — but surface the disagreement.
                    flags.append(f"material check: drawing '{cur_mat}' vs SolidWorks "
                                 f"'{new_mat}' ('{nat.material}') — kept the drawing value")
                    out["material_conflict"] += 1

        # ── GEOMETRY: the sheet-metal cut list ───────────────────────────────────
        if nat.has_flat():
            fl, fw = float(nat.flat_length_mm), float(nat.flat_width_mm)
            if _dxf_backed(part):
                # DXF stays authoritative. Compare and flag a real disagreement (>10% on
                # area) — two independent measurements of the same blank should agree.
                _dl, _dw = _dxf_blank_mm(part)
                if _dl and _dw:
                    _a_dxf, _a_sw = _dl * _dw, fl * fw
                    if _a_sw > 0 and abs(_a_dxf - _a_sw) / _a_sw > 0.10:
                        flags.append(
                            f"blank check: DXF {_dl:g}x{_dw:g}mm vs SolidWorks flat "
                            f"{fl:g}x{fw:g}mm — kept the DXF (measured flat pattern)")
                        out["geometry_conflict"] += 1
                else:
                    # A cross-check that silently declines to check is WORSE than none: it
                    # reports zero disagreements, which reads as agreement. Say so instead.
                    flags.append(
                        f"blank check NOT PERFORMED — the part is DXF-backed but no DXF blank "
                        f"could be read to compare against the SolidWorks flat "
                        f"{fl:g}x{fw:g}mm. The two measurements are UNRECONCILED")
                    out["geometry_unchecked"] += 1
            else:
                ng = part.get("normalized_geometry")
                ng = dict(ng) if isinstance(ng, dict) else {}
                ng["blank_length_mm"] = fl
                ng["blank_width_mm"] = fw
                ng["geometry_source"] = NATIVE_GEOMETRY_SOURCE
                part["normalized_geometry"] = ng
                part["blank_length_mm"] = fl
                part["blank_width_mm"] = fw
                part["geometry_source"] = NATIVE_GEOMETRY_SOURCE
                # Measured flat, from the model that generates the DXF. This marker is what
                # the engine's measured-geometry gates and the credibility gate key on.
                part["native_flat_pattern"] = True
                part["flat_pattern_detected"] = True
                flags.append(f"flat blank {fl:g} x {fw:g}mm from the SolidWorks sheet-metal "
                             f"cut list (modelled flat pattern — measured, not inferred)")
                out["flat"] += 1
                # CUT LENGTH. Laser run time is driven by profile length, so a part with a
                # real blank but no cut length would be costed as if it took no cutting at
                # all — under-costing, which is the direction that loses money.
                gr = part.setdefault("geometry_rollup", {})
                if isinstance(gr, dict) and not _num(gr.get("estimated_cut_length_mm")):
                    if nat.cut_length_mm and nat.cut_length_mm > 0:
                        gr["estimated_cut_length_mm"] = float(nat.cut_length_mm)
                    else:
                        # Rectangular-outline FLOOR, not an estimate of the real outline.
                        # Any closed profile enclosing an L x W blank has a perimeter of at
                        # least 2(L+W), so this cannot overstate the cut. It ignores hole
                        # edges and any non-rectangular outline, so the true figure is
                        # HIGHER — flagged as a floor so nobody reads it as measured.
                        _perim = 2.0 * (fl + fw)
                        gr["estimated_cut_length_mm"] = round(_perim, 1)
                        gr["cut_length_basis"] = "solidworks_blank_perimeter_floor"
                        flags.append(
                            f"cut length {_perim:,.0f}mm is a FLOOR from the blank outline "
                            f"(2 x ({fl:g}+{fw:g})) — the model gave no cut length; holes and "
                            f"any non-rectangular profile add to this, so laser time is a "
                            f"MINIMUM, not a measurement")

        # ── THICKNESS ────────────────────────────────────────────────────────────
        if _plausible_thk(nat.thickness_mm):
            thk = float(nat.thickness_mm)
            cur_thk = _num(part.get("normalized_thickness_mm"))
            if not cur_thk:
                part["normalized_thickness_mm"] = thk
                flags.append(f"thickness {thk:g}mm from the SolidWorks sheet-metal cut list")
                out["thickness"] += 1
            elif abs(cur_thk - thk) > 0.05 and not _dxf_backed(part):
                # The model's sheet thickness is the gauge the part is made from; a PDF
                # thickness is often lifted from a tolerance table. Model wins, and says so.
                part["normalized_thickness_mm"] = thk
                flags.append(f"thickness {cur_thk:g}mm -> {thk:g}mm from the SolidWorks "
                             f"cut list (modelled sheet gauge)")
                out["thickness"] += 1

        # ── SURFACE TREATMENT ────────────────────────────────────────────────────
        # The cut list publishes the finish the designer specified. This is the datum the
        # drawing states as a POINTER ('SEE ASSEMBLY DRAWING') on four of 12120's parts —
        # the model carries it directly. Added, never replacing a printed finish: the
        # drawing is the released document and wins where the two differ.
        if nat.surface_treatment:
            _fin = part.setdefault("surface_finishes", [])
            if isinstance(_fin, list):
                _known = " ".join(str(f) for f in _fin).upper()
                if nat.surface_treatment.upper() not in _known:
                    _fin.append(nat.surface_treatment)
                    flags.append(f"finish '{nat.surface_treatment}' from the SolidWorks cut "
                                 f"list ('Surface Treatment')"
                                 + (" — the drawing states a different finish, both kept "
                                    "for the estimator to reconcile" if _known else ""))
                    out["finish"] += 1

        # ── MASS ─────────────────────────────────────────────────────────────────
        if nat.mass_kg and nat.mass_kg > 0 and not _num(part.get("stated_weight_g")):
            part["stated_weight_g"] = round(float(nat.mass_kg) * 1000.0, 2)
            flags.append(f"mass {nat.mass_kg:.4f}kg from the SolidWorks model")
            out["mass"] += 1

        # ── BENDS ────────────────────────────────────────────────────────────────
        _bends = int(nat.bend_count or 0)
        if _bends > 0:
            mf = part.setdefault("manufacturing_features", {})
            if isinstance(mf, dict) and int(mf.get("bend_count") or 0) < _bends:
                mf["bend_count"] = _bends
                flags.append(f"{_bends} bend(s) counted in the SolidWorks feature tree")
                out["bends"] += 1
            if _plausible_thk(nat.bend_radius_mm):
                part["bend_radius_mm"] = float(nat.bend_radius_mm)
        elif nat.formed_but_no_bend_features:
            # Real folds that no feature counts — a Base Flange from a multi-segment
            # sketch. Flag it so the fold op still fires and an estimator can set the
            # count; do NOT invent a number.
            part["formed_no_bend_count"] = True
            flags.append("SolidWorks: part is formed (folded solid) but its bends are baked "
                         "into the base flange sketch — bend COUNT not readable, fold time "
                         "provisional; confirm the number of folds")
            _ops = part.setdefault("textual_operations", [])
            if isinstance(_ops, list) and "folding" not in _ops:
                _ops.append("folding")
                out["bends"] += 1

        if nat.hole_count_est and not _num((part.get("manufacturing_features") or {}).get("hole_count")):
            mf = part.setdefault("manufacturing_features", {})
            if isinstance(mf, dict):
                mf["hole_count"] = int(nat.hole_count_est)

        # ── OPS HINTS ────────────────────────────────────────────────────────────
        # The analyser only emits an op where the feature tree evidences it (steel + sheet
        # metal for powder, a real bend for folding, ...). Merge, never replace.
        _ops = part.setdefault("textual_operations", [])
        if isinstance(_ops, list):
            for op in nat.ops_hint:
                if op in _KNOWN_OPS and op not in _ops:
                    _ops.append(op)
                    out["ops"] += 1

        # ── FLAG, NEVER ZERO ─────────────────────────────────────────────────────
        # Material assigned but nothing to cost it against. Left alone this becomes a
        # £0 line that reads as "priced and free". Flag it as unpriced instead.
        if (part.get("normalized_material") and not _has_costable_geometry(part)
                and not part.get("is_assembly_parent")):
            part["native_material_without_geometry"] = True
            flags.append("SolidWorks gave this part a material but NO usable geometry "
                         "(no flat pattern, mass or section) — material cost cannot be "
                         "derived; treat any £0 on this line as MISSING, not free")
            out["no_geometry_flagged"] += 1

    return out


# ── reconcile helper (native -> part_estimates), mirrors the dual-path reconcile ──
def apply_native_to_part_estimates(summary: Dict[str, Any], job: NativeJob) -> Dict[str, int]:
    """Fold native truth into estimate_summary.part_estimates, non-destructively:
      - MATERIAL: set from the native model where a part currently has none/inferred
        (native is reliability 1.0 — the model's own applied material).
      - QUANTITY: correct bought-in/fastener quantities from the native BOM roll-up.
      - WELD: flag weld-candidate assemblies for the weld/dress route.
    Returns {'material_set','qty_corrected','weld_flagged'}. Geometry (holes/cut length)
    is deliberately NOT overwritten here — DXF stays authoritative for that.

    NOT ON THE LIVE PATH. apply_native_to_pre_estimate() supersedes it and IS wired into
    file_scan: applying native truth BEFORE costing means the numbers are computed from it,
    rather than patched afterwards while the costs still reflect the old values. This is
    kept for the reconcile/audit use case — folding native data into an ALREADY-COSTED
    summary for comparison — and must not be called on the estimating path, where it would
    silently desynchronise part records from the costs derived from them."""
    out = {"material_set": 0, "qty_corrected": 0, "weld_flagged": 0}
    if not job or not job.found:
        return out
    es = summary.get("estimate_summary") or {}
    parts = es.get("part_estimates")
    if not isinstance(parts, list):
        return out

    qty_by_pn = {_clean_pn(r.part_number): r.quantity for r in job.bom}
    weld_pns = {_clean_pn(r.part_number) for r in job.bom if r.weld_candidate}

    for p in parts:
        pn = _clean_pn(str(p.get("part_number") or ""))
        if not pn:
            continue
        nat = job.part_signals.get(pn)
        # Material: native wins where the engine has nothing solid.
        if nat and nat.material and not str(p.get("normalized_material") or "").strip():
            p["normalized_material"] = nat.material
            p.setdefault("review_flags", []).append(
                f"Material '{nat.material}' from SolidWorks model")
            out["material_set"] += 1
        # Quantity: native BOM roll-up corrects fastener/bought-in counts.
        q = qty_by_pn.get(pn)
        if q is not None and int(q) > 0 and p.get("quantity") != int(q):
            _old = p.get("quantity")
            p["quantity"] = int(q)
            p.setdefault("review_flags", []).append(
                f"Quantity {_old} -> {int(q)} from SolidWorks BOM")
            out["qty_corrected"] += 1
        # Weld candidate → flag for the weld/dress route.
        if pn in weld_pns:
            p.setdefault("review_flags", []).append(
                "SolidWorks: welded sub-assembly — confirm weld/dress route")
            out["weld_flagged"] += 1

    return out
