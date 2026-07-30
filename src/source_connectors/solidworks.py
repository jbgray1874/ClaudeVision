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

from source_precedence import apply_field as _apply_field

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
    """Records only. Accepts both shapes: the v2 payload {_manifest, records} and the bare
    list the analyser wrote before manifests existed — an extract already sitting in a job
    folder must not stop working because the writer gained a header."""
    return (load_native_payload(json_path) or {}).get("records") or []


def load_native_payload(json_path: str | Path) -> Dict[str, Any]:
    """The whole extract: manifest and records. Returns {} when there is nothing readable."""
    jp = Path(json_path)
    if not jp.exists():
        return {}
    try:
        data = json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, list):
        # Pre-manifest extract. Say so explicitly rather than reporting an empty manifest,
        # which would read as "checked, nothing wrong" when nothing was checked.
        return {"records": data, "_manifest": None, "manifest_absent": True}
    if isinstance(data, dict):
        return {"records": data.get("records") or [],
                "_manifest": data.get("_manifest"),
                "manifest_absent": not isinstance(data.get("_manifest"), dict)}
    return {}


def _is_flat_solid(p: "NativePart") -> bool:
    """Is this part a plate — a solid whose smallest dimension IS its thickness?

    A folded part's envelope always stands taller than its material: 12120's 01M is
    79 x 64.5 x 21.5 at 1.5mm, 06M is 30.9 x 39.09 x 35 at 1.2mm. A part measuring one
    thickness in its smallest direction has nowhere for a bend to be. Physical, and true of
    any part from any job.
    """
    thk = _num(p.thickness_mm)
    bbox = [b for b in (_num(v) for v in (p.bbox_mm or [])) if b]
    if not thk or len(bbox) < 3:
        return False
    # Generous: SolidWorks reports the envelope of the modelled solid, which can stand a
    # fraction over gauge from a countersink or an embossed feature.
    return min(bbox) <= thk * 1.25 + 0.2


def _bbox_text(p: "NativePart") -> str:
    b = [f"{_num(v):g}" for v in (p.bbox_mm or []) if _num(v)]
    return (" x ".join(b) + "mm") if b else "unknown"


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
            cut_out_count=(int(_num(rs.get("cut_out_count")))
                           if _num(rs.get("cut_out_count")) is not None else None),
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
    falls back cleanly to the PDF/DXF path).

    FRESHNESS. An extract is a photograph of the models at the moment it was taken. Reading
    one without checking it still describes the files on disk is how a job gets costed from
    last month's geometry with nothing on screen to say so — the same silence the invariant
    layer exists to break. `native_files_state` fingerprints the native files; a mismatch
    does not discard the extract (it is still the best evidence available) but marks it
    STALE, which the estimate must carry through as provisional."""
    jp: Optional[Path] = Path(json_path) if json_path else None
    if jp is None and folder is not None:
        jp = Path(folder) / EXTRACT_FILENAME

    _run_error = None
    if jp is not None and run and folder is not None and _should_run(jp, folder):
        _produced: List[str] = []
        _run_error = _run_analyser(folder, analyser=analyser, python_exe=python_exe,
                                   out_path=jp, produced=_produced)
        if _produced and Path(_produced[0]) != jp:
            # It wrote somewhere else — a read-only share, most often. Read what exists,
            # not what was requested.
            jp = Path(_produced[0])

    records = load_native_extract(jp) if jp else []
    job = normalize_native_extract(records)
    job.meta.setdefault("extract_path", str(jp) if jp else None)

    if folder is not None or jp is not None:
        # FINGERPRINT THE FOLDER THE EXTRACT WAS TAKEN FROM, not the job folder.
        # The models routinely live somewhere other than the drawings — the analyser's own
        # header says so — and SDI_SW_EXTRACT_JSON exists precisely for that case. Comparing
        # the manifest against the JOB folder then compares a fingerprint of the models with
        # a fingerprint of a folder containing none, which reads as "everything changed" and
        # would mark a freshly generated extract STALE. The manifest records where it was
        # generated from; that is the folder to check.
        _man_early = None
        if jp is not None and jp.exists():
            _man_early = (load_native_payload(jp) or {}).get("_manifest")
        _fp_folder = (_man_early or {}).get("generated_from") or folder
        _state = native_files_state(_fp_folder) if _fp_folder else {
            "count": 0, "fingerprint": "", "newest_mtime": 0.0, "files": []}
        job.meta["fingerprint_folder"] = str(_fp_folder) if _fp_folder else None
        # An extract generated from somewhere else, with no manifest to say where: nothing
        # can be verified about its freshness at all, and that must not read as a pass.
        if (_man_early is None and folder is not None and jp is not None
                and jp.parent.resolve() != Path(folder).resolve()):
            job.meta["freshness_unverifiable"] = True
        job.meta["native_files_present"] = _state["count"]
        job.meta["native_files_fingerprint"] = _state["fingerprint"]
        if jp is not None and jp.exists():
            _payload = load_native_payload(jp)
            _man = _payload.get("_manifest") if isinstance(_payload.get("_manifest"), dict) else None
            _recorded = (_man or {}).get("native_files_fingerprint")
            job.meta["changed_during_extraction"] = bool((_man or {}).get("changed_during_extraction"))
            job.meta["fingerprint_before"] = (_man or {}).get("fingerprint_before")
            if _recorded:
                # UNREACHABLE IS NOT STALE. If the manifest names a folder on a drive that is
                # not mapped now, the current fingerprint comes back empty and every file
                # looks changed — which would report a perfectly good extract as stale on the
                # strength of a missing network drive. That proves only that we could not
                # look.
                _folder_ok = bool(_fp_folder) and Path(str(_fp_folder)).exists()
                if not _folder_ok or not _state["fingerprint"]:
                    job.meta["source_unreachable"] = True
                    job.meta["extract_stale"] = False
                else:
                    # The real test: does this extract still describe the files on disk? A
                    # fingerprint sees a deleted or renamed model, which a timestamp cannot.
                    job.meta["extract_stale"] = (_recorded != _state["fingerprint"])
                job.meta["extract_manifest"] = _man
            else:
                # No manifest. mtime is the only thing left, and it is genuinely weaker: a
                # copy, a restore or a touch defeats it, and a deleted model is invisible to
                # it. Record that the check was WEAK rather than letting a pass on a
                # timestamp read like a pass on identity.
                job.meta["extract_stale"] = _state["newest_mtime"] > jp.stat().st_mtime
                job.meta["freshness_check"] = "mtime_only"
                job.meta["manifest_absent"] = True
            # COVERAGE. Per-file failures are written as error-only records and the analyser
            # still exits zero, so an extraction where every file failed produced a non-empty
            # list that read downstream as a successful read.
            if _man:
                job.meta["files_read"] = _man.get("files_read")
                job.meta["files_failed"] = _man.get("files_failed")
                job.meta["extract_errors"] = _man.get("errors")
            _recs = _payload.get("records") or []
            _failed = [r for r in _recs if isinstance(r, dict) and r.get("errors")]
            _read = [r for r in _recs
                     if isinstance(r, dict) and not r.get("errors") and r.get("title")]
            job.meta.setdefault("files_read", len(_read))
            job.meta.setdefault("files_failed", len(_failed))
            job.meta["extract_incomplete"] = bool(_recs) and not _read
        # NATIVE MODELS PRESENT BUT NO EXTRACT. The strongest source in the building is
        # sitting in the folder unread, and until now that was indistinguishable from a job
        # that simply has no models.
        if _state["count"] and not records:
            job.meta["native_present_but_unread"] = True
            job.meta["native_unread_reason"] = _run_error or (
                "native models are in the job folder but no extract has been generated. "
                "Run tools/solidworks/sw_native_analyse.py on a machine with SolidWorks")
    if _run_error:
        job.meta["analyser_error"] = _run_error
    return job


# Native model files. Drawings are included in the fingerprint because a released .SLDDRW
# carries BOM tables and callouts the analyser reads.
_NATIVE_EXTS = (".sldprt", ".sldasm", ".slddrw")

# Folders whose contents are not the live design. MUST match
# sw_native_analyse._EXCLUDED_DIR_TOKENS exactly, or the consumer counts files the analyser
# never opened — and a fixture compares the two rules name for name.
#
# Matched as whole WORDS. The substring version excluded "CAD Folder", because "folder"
# contains "old", and the damage was silent: the analyser read those files while the manifest
# omitted them, so later changes to them were invisible to the freshness check.
# "previous" and "prev" come from the discovery rule this replaced. Unifying two lists must
# not quietly WIDEN what gets read: every token either list had is kept.
_EXCLUDED_DIR_TOKENS = ("archive", "archived", "obsolete", "superseded", "old", "backup",
                        "bak", "dnu", "scrap", "wip", "temp", "tmp",
                        "previous", "prev")
_EXCLUDED_DIR_PHRASES = ("do not use", "not for manufacture")


def _is_excluded_dir(name: str) -> bool:
    n = str(name or "").strip().lower()
    if n.startswith(".") or n.startswith("~"):
        return True
    if any(ph in n for ph in _EXCLUDED_DIR_PHRASES):
        return True
    return any(w in _EXCLUDED_DIR_TOKENS for w in re.split(r"[^a-z0-9]+", n) if w)


def native_files_state(folder: str | Path) -> Dict[str, Any]:
    """Fingerprint the native files in a job folder: how many, and their identity.

    Size+mtime rather than a content hash — a hash of a folder of 80MB assemblies costs
    seconds per run and buys nothing here, because the question is only "have these files
    changed since the extract was taken", not "are they byte-identical to a known good"."""
    out: Dict[str, Any] = {"count": 0, "fingerprint": "", "newest_mtime": 0.0, "files": []}
    try:
        root = Path(folder)
        if not root.exists():
            return out
        found = []
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _NATIVE_EXTS:
                continue
            # SCOPE MUST MATCH THE ANALYSER'S. Counting files it does not read produces the
            # worst of both: a drawing-only job blocked because an archived model from two
            # revisions ago was "not read", and a fingerprint that changes when somebody
            # tidies an Archive folder. ~$ files are SolidWorks lock files, not models.
            if p.name.startswith("~$") or p.name.startswith("."):
                continue
            if any(_is_excluded_dir(part) for part in p.relative_to(root).parts[:-1]):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            found.append((p.name.lower(), st.st_size, int(st.st_mtime)))
            out["newest_mtime"] = max(out["newest_mtime"], st.st_mtime)
        out["count"] = len(found)
        out["files"] = [f[0] for f in found]
        if found:
            import hashlib
            basis = "|".join(f"{n}:{s}:{m}" for n, s, m in found)
            out["fingerprint"] = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    except Exception:
        pass
    return out


def _should_run(extract_path: Path, folder: str | Path) -> bool:
    """Run the analyser when there is no extract, or the one we have predates the models."""
    if not extract_path.exists():
        return True
    try:
        return native_files_state(folder)["newest_mtime"] > extract_path.stat().st_mtime
    except Exception:
        return False


def _run_analyser(folder: str | Path, analyser: Optional[str | Path] = None,
                  python_exe: Optional[str] = None,
                  out_path: Optional[str | Path] = None,
                  produced: Optional[List[str]] = None) -> Optional[str]:
    """Invoke sw_native_analyse.py on a folder (Windows + SolidWorks only).

    Returns None on success, or a description of the failure. It used to swallow every
    exception and return nothing, so an analyser that could not start — no SolidWorks, no
    licence, a bad path — was indistinguishable from a job with no models: the run simply
    continued on PDF+DXF and said nothing. The caller records the reason."""
    if analyser is None:
        analyser = Path(__file__).resolve().parents[2] / "tools" / "solidworks" / "sw_native_analyse.py"
    exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or "python"
    produced = produced if produced is not None else []
    cmd = [exe, str(analyser), str(folder)]
    if out_path:
        # Tell it where to write, and read back where it ACTUALLY wrote. The analyser falls
        # back to the working directory when the target is a read-only CAD share, so the
        # caller cannot assume the path it asked for — it used to read a different file from
        # the one that had just been produced.
        cmd += ["--out", str(out_path)]
    try:
        r = subprocess.run(cmd, check=False, timeout=1800,
                           capture_output=True, text=True)
        for _line in reversed((r.stdout or "").splitlines()):
            if _line.startswith("EXTRACT_PATH="):
                produced.append(_line.split("=", 1)[1].strip())
                break
        if r.returncode != 0:
            _tail = (r.stderr or r.stdout or "").strip().splitlines()
            return (f"the SolidWorks analyser exited {r.returncode}"
                    + (f": {_tail[-1][:300]}" if _tail else ""))
        return None
    except FileNotFoundError:
        return f"could not start the SolidWorks analyser — python executable {exe!r} not found"
    except subprocess.TimeoutExpired:
        return "the SolidWorks analyser timed out after 30 minutes"
    except Exception as exc:
        return f"the SolidWorks analyser could not be run: {exc}"


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


def _reject_dxf_geometry(part: Dict[str, Any], nat: "NativePart",
                         fl: float, fw: float, verdict: Dict[str, Any],
                         flags: List[str]) -> None:
    """Swap a rejected DXF fact set out for the model's, atomically.

    Every cost-driving geometry field measured from the rejected file is moved aside under
    `rejected_dxf_geometry` — kept, because a person needs to see what the file said, but out
    of reach of costing. What the model can supply is written in its place; what it cannot is
    left ABSENT rather than inherited, because an absent number is priced as unknown while a
    stale one is priced as fact.
    """
    _ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), dict) else {}
    _gr = part.get("geometry_rollup") if isinstance(part.get("geometry_rollup"), dict) else {}

    _COST_DRIVING = ("blank_length_mm", "blank_width_mm", "blank_area_mm2",
                     "estimated_cut_length_mm", "cut_length_mm", "raw_cut_length_mm",
                     "estimated_hole_count", "hole_count", "estimated_pierce_count",
                     "pierce_count", "drawing_extents_mm", "weight_kg",
                     "estimated_bend_line_count", "closed_contour_count",
                     "pierce_count_incomplete")
    quarantined: Dict[str, Any] = {}
    for holder_name, holder in (("part", part), ("normalized_geometry", _ng),
                                ("geometry_rollup", _gr),
                                ("manufacturing_features",
                                 part.get("manufacturing_features")
                                 if isinstance(part.get("manufacturing_features"), dict) else {})):
        if not isinstance(holder, dict):
            continue
        for f in _COST_DRIVING:
            if f in holder:
                quarantined[f"{holder_name}.{f}"] = holder.pop(f)

    part["rejected_dxf_geometry"] = {
        "reason": verdict.get("reason"),
        "area_ratio": verdict.get("area_ratio"),
        "dxf_source_file": part.get("dxf_source_file"),
        "values": quarantined,
        "note": ("Measured from a DXF that does not contain the whole part. Retained for "
                 "inspection only — not costed, and not to be read back into the estimate."),
    }

    # The model's flat, which IS complete.
    _ng = part.setdefault("normalized_geometry", {})
    _ng["blank_length_mm"], _ng["blank_width_mm"] = fl, fw
    _ng["blank_area_mm2"] = fl * fw
    _ng["geometry_source"] = NATIVE_GEOMETRY_SOURCE
    part["blank_length_mm"], part["blank_width_mm"] = fl, fw
    part["blank_area_mm2"] = fl * fw
    part["geometry_source"] = NATIVE_GEOMETRY_SOURCE
    part["blank_length_mm_source"] = SOURCE_NAME
    part["native_flat_pattern"] = True
    part["dxf_geometry_rejected"] = True
    part["dxf_measured_outline"] = False
    # The DXF is no longer evidence of anything measured. Leaving these set kept the part
    # inside the engine's "has a measured flat pattern" gates on the strength of a file we
    # have just rejected.
    part["dxf_augmented"] = False
    part["flat_pattern_detected"] = True          # true of the MODEL's flat, which we now hold

    _gr = part.setdefault("geometry_rollup", {})
    if nat is not None and getattr(nat, "cut_length_mm", None):
        _gr["estimated_cut_length_mm"] = float(nat.cut_length_mm)
    else:
        # No model perimeter either. A rectangular floor is honest about being a floor; a
        # stale perimeter from the rejected file is not.
        _gr["estimated_cut_length_mm"] = 2.0 * (fl + fw)
        _gr["estimated_cut_length_is_floor"] = True
        flags.append(f"cut length for this part is a RECTANGULAR FLOOR ({2.0 * (fl + fw):.0f}mm) "
                     f"— the DXF was rejected and the model publishes no cut length")
    if nat is not None and getattr(nat, "cut_out_count", None) is not None:
        _apply_field(part, "geometry_rollup.estimated_pierce_count",
                     int(nat.cut_out_count) + 1, SOURCE_NAME)
    if nat is not None and getattr(nat, "hole_count_est", None):
        _gr["estimated_hole_count"] = int(nat.hole_count_est)
    flags.append(f"DXF geometry QUARANTINED for this part ({len(quarantined)} field(s)) — "
                 f"costed from the SolidWorks flat {fl:g} x {fw:g}mm")


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

        # ── SECTION CUT LENGTH: the model knows what the drawing never printed ────
        #
        # A tube's cut length is the one number the section path cannot do without, and on a
        # GA-only pack nothing prints it — M&S 2085 dimensions its tubes on the views, so
        # both came through with a profile and no length, unpriced. The model has it: the
        # part's bounding box is captured already and, for a straight section, its LONGEST
        # dimension IS the cut length. Measured, rank solidworks_api, not inferred.
        #
        # Only where the part already has a SECTION and no length. This never invents a
        # section for something that is not one, and never overwrites a length the drawing
        # or the cutting list stated.
        #
        # A BENT tube is the honest limitation: the bounding box is its envelope, not its
        # developed length, so it under-reads. Flagged rather than silently used, because
        # under-reading a tube is how a job gets quoted short.
        _ss = part.get("section_stock")
        if isinstance(_ss, dict) and not _num(_ss.get("length_mm")):
            _bb = [f for f in (_num(v) for v in (getattr(nat, "bbox_mm", None) or [])) if f]
            if _bb:
                _len = max(_bb)
                _ss = dict(_ss)
                _ss["length_mm"] = round(_len, 2)
                _ss["length_source"] = "solidworks_api"
                part["section_stock"] = _ss
                out["section_length"] = out.get("section_length", 0) + 1
                _bent = any(o in (part.get("textual_operations") or [])
                            for o in ("tube_bending", "rolling"))
                flags.append(
                    f"section cut length {_len:.1f}mm taken from the MODEL's bounding box — "
                    f"the drawing does not print one" +
                    (". The part is also bent, so this is the ENVELOPE, not the developed "
                     "length, and it UNDER-READS: confirm the cut length before quoting"
                     if _bent else ""))

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
            # ALWAYS SUBMIT, even when the numbers already match. Skipping the resolver on
            # agreement left the datum carrying the WEAKER source's name, so a later
            # medium-ranked pass could still displace a quantity the model had independently
            # confirmed. Agreement is evidence: it upgrades provenance. The flag is gated on
            # the return, which is true only when the value actually changed.
            if _q > 0:
                # The counter belongs INSIDE the success branch. Outside it, a quantity the
                # resolver refused — because an estimator had already corrected it — was
                # still counted as applied, so the run reported work it did not do.
                if _apply_field(part, "quantity", _q, SOURCE_NAME):
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
                if _apply_field(part, "normalized_material", new_mat, SOURCE_NAME):
                    flags.append(f"material '{new_mat}' from the SolidWorks model "
                                 f"(applied material: {nat.material})")
                    out["material"] += 1
            elif new_mat and cur_mat and new_mat == cur_mat:
                # Same answer from a stronger source. Nothing changes on screen; what changes
                # is that the value now rests on the model rather than on the drawing text,
                # and a later pass can no longer quietly replace it.
                _apply_field(part, "normalized_material", new_mat, SOURCE_NAME)
            elif new_mat and cur_mat and new_mat != cur_mat:
                _cross_family = (
                    (new_mat in _NON_METAL_FAMILIES and cur_mat in _METAL_FAMILIES)
                    or (new_mat in _METAL_FAMILIES and cur_mat in _NON_METAL_FAMILIES)
                )
                if _cross_family:
                    # A wood/board part is definitively not steel (and vice versa). The
                    # model is authoritative on what the designer specified — override
                    # the engine's family default and say so.
                    # Gated on the RESULT. A rank-100 estimator correction can legitimately
                    # survive this, and claiming "overridden" when it did not is a review
                    # flag that describes something the engine did not do.
                    if _apply_field(part, "normalized_material", new_mat, SOURCE_NAME):
                        flags.append(f"material '{cur_mat}' overridden to '{new_mat}' from the "
                                     f"SolidWorks model ('{nat.material}') — wrong material FAMILY")
                        out["material"] += 1
                else:
                    # SAME FAMILY, DIFFERENT GRADE — still submitted. This branch used to
                    # decide the outcome itself and never call the resolver at all, on the
                    # reasoning that the printed title block is what the shop buys to. That
                    # reasoning is a rank judgement, and rank is not this function's to make:
                    # it kept the drawing value even against an estimator's own correction,
                    # and it left the datum carrying the weaker source so a later pass could
                    # still move it. Submit; let apply_field decide and record the conflict.
                    if _apply_field(part, "normalized_material", new_mat, SOURCE_NAME):
                        flags.append(f"material '{cur_mat}' -> '{new_mat}' from the SolidWorks "
                                     f"model ('{nat.material}') — same family, different grade")
                        out["material"] += 1
                    else:
                        flags.append(f"material check: drawing '{cur_mat}' vs SolidWorks "
                                     f"'{new_mat}' ('{nat.material}') — kept the drawing value")
                        out["material_conflict"] += 1

        # ── GEOMETRY: the sheet-metal cut list ───────────────────────────────────
        if nat.has_flat():
            fl, fw = float(nat.flat_length_mm), float(nat.flat_width_mm)
            if _dxf_backed(part):
                # Two independent measurements of the same blank. Arbitrated on geometry
                # alone — see geometry_arbitration for why a materially SMALLER DXF loses to
                # the model while a larger one is kept and marked unreconciled. Flagging the
                # disagreement and keeping the DXF regardless, as this did, is what let a
                # part measuring 25% of its true area be costed at 25% of its true area.
                _dl, _dw = _dxf_blank_mm(part)
                if _dl and _dw:
                    from geometry_arbitration import arbitrate_flat, NATIVE
                    _verdict = arbitrate_flat(_dl, _dw, fl, fw)
                    part["flat_arbitration"] = _verdict
                    if not _verdict["agree"]:
                        flags.append(f"blank check: {_verdict['reason']}")
                        out["geometry_conflict"] += 1
                    if _verdict["winner"] == NATIVE:
                        # QUARANTINE THE WHOLE REJECTED FACT SET, not just the two dimensions
                        # that lost. A DXF that measured a quarter of the part measured its
                        # cut length, hole count, pierce count and extents from the same
                        # incomplete file — all of them wrong in the same direction, all of
                        # them still readable by costing. Replacing the blank alone leaves a
                        # part with the model's size and the broken file's perimeter, which
                        # is a worse record than either source on its own.
                        _reject_dxf_geometry(part, nat, fl, fw, _verdict, flags)
                        part.setdefault("review_flags", []).append(
                            f"DXF flat pattern REJECTED and replaced by the model's: "
                            f"{_verdict['reason']}. Check the DXF export — the file does not "
                            f"contain the whole part")
                        out["geometry_rejected"] = out.get("geometry_rejected", 0) + 1
                    elif _verdict["unreconciled"]:
                        part["flat_unreconciled"] = True
                        part.setdefault("review_flags", []).append(
                            f"Blank UNRECONCILED: {_verdict['reason']}")
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
            if not cur_thk or abs(cur_thk - thk) <= 0.05:
                # Empty, or already agreeing: submit either way so the model's rank attaches.
                if _apply_field(part, "normalized_thickness_mm", thk, SOURCE_NAME):
                    flags.append(f"thickness {thk:g}mm from the SolidWorks sheet-metal cut list")
                    out["thickness"] += 1
            else:
                # DIFFERING GAUGE — submitted whether or not the part is DXF-backed. This
                # branch used to be guarded by `not _dxf_backed(part)`, so a part with a DXF
                # never even offered the model's gauge. That is a rank judgement made
                # locally, and a wrong one: a DXF filename thickness is a filename, while the
                # cut list is the gauge the part is modelled in. The resolver ranks them.
                #
                # The model's sheet thickness is the gauge the part is made from; a PDF
                # thickness is often lifted from a tolerance table. Model wins, and says so.
                if _apply_field(part, "normalized_thickness_mm", thk, SOURCE_NAME):
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
        elif (_plausible_thk(nat.thickness_mm)
              and not nat.formed_but_no_bend_features and _is_flat_solid(nat)):
            # THE MODEL SAYS THIS PART DOES NOT FOLD, AND ITS SOLID AGREES.
            #
            # A zero bend count on its own proves nothing — that is exactly the failure
            # `formed_but_no_bend_features` exists for, where a Base Flange hides real folds
            # from the feature tree. So zero is believed only when the SOLID corroborates it:
            # a part one thickness thick has nowhere for a bend to be. 12120's 04M is
            # 60 x 34.04 x 1.5mm at 1.5mm gauge — a plate — and it was being folded.
            #
            # THE GUARD USED TO REQUIRE is_sheet_metal, AND THAT EXCLUDED THE WHOLE POINT.
            # is_sheet_metal is true only where the feature tree holds a sheet-metal feature
            # — SMBaseFlange, an EdgeFlange, a SketchBend. Nobody models a flat plate that
            # way; you extrude it. So the parts this gate exists to catch were precisely the
            # ones it could not see, and 04M kept coming back in the Fold 1.5mm group.
            #
            # Nothing is lost by dropping it. _plausible_thk demands a real thickness and
            # _is_flat_solid demands a three-dimensional bounding box, so the gate still
            # fires only where the model was actually read — which is the assurance
            # is_sheet_metal was being credited with. And a folded part cannot pass
            # _is_flat_solid however it was modelled: its envelope always stands taller than
            # its material.
            #
            # The op is dropped here rather than left to a later gate because nothing
            # downstream has this evidence: the drawing text, the DXF bend-line heuristic and
            # the PDF can all suggest a fold, and none of them can see that the part is flat.
            _ops = part.get("textual_operations")
            _removed = False
            if isinstance(_ops, list) and "folding" in _ops:
                _ops[:] = [o for o in _ops if o != "folding"]
                _removed = True
            mf = part.setdefault("manufacturing_features", {})
            if isinstance(mf, dict):
                if _num(mf.get("bend_count")):
                    _removed = True
                mf["bend_count"] = 0
                mf["bend_count_source"] = SOURCE_NAME
            _rf = part.get("risk_flags")
            if isinstance(_rf, list):
                _rf[:] = [f for f in _rf if "fold" not in str(f).lower()
                          and "bend" not in str(f).lower()]
            # A DURABLE FACT, not just a removal. Stripping the op here is not enough: the
            # connector runs early, and a later pass re-derives folding from the drawing's
            # own text ("fold or bend work indicated"), which is how 04M was back in the
            # Fold 1.5mm group after the strip had removed it. The marker records that the
            # MODEL says this part is a plate, so the gate can be enforced again at costing
            # time, after every pass that could re-add the op has run.
            part["native_flat_solid"] = True
            if _removed:
                flags.append(
                    f"fold REMOVED: the cut list reports 0 bends and the solid is "
                    f"{_bbox_text(nat)} at {nat.thickness_mm:g}mm — one thickness thick, so "
                    f"there is nowhere for a bend to be. A fold was routed from the drawing")
                out["fold_removed"] = out.get("fold_removed", 0) + 1
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
        # CUT-OUTS. The cut list publishes how many internal profiles the laser has to cut,
        # which is separate from round holes and drives pierce count and cutting time. It
        # was read from the model and then discarded before it reached anything that costs.
        # `is not None`, NOT truthiness. A cut list reporting ZERO cut-outs has told us
        # something definite — this part is a plain blank with one outer profile and one
        # pierce — and it is the model saying it, the strongest source we have. Treating 0 as
        # "no data" let a weaker PDF-derived count survive against explicit model evidence,
        # which is the same silent-overwrite failure in the opposite direction.
        if nat.cut_out_count is not None:
            # Every internal cut-out needs its own pierce, as does the outer profile.
            # Under-counting pierces under-prices the laser.
            _native_pierces = int(nat.cut_out_count) + 1
            # SUPERSEDE, DO NOT MERELY FILL. This is the model's own count of internal
            # profiles — rank 90, above DXF and far above a PDF-derived guess. Filling only
            # an empty value meant any earlier positive number, however weak, locked the
            # stronger evidence out: a drawing-text estimate of 2 kept its place against a
            # cut list saying 9, and the laser was charged for two pierces. A disagreement is
            # flagged rather than silently overwritten, so a human can see both figures.
            # Through the resolver, on dotted paths, because these fields do not live at the
            # top of a part record — and a resolver that cannot see inside geometry_rollup
            # cannot arbitrate the numbers that drive the laser. apply_field records the
            # source, defends the value against weaker later passes, and writes the
            # disagreement onto the part when it declines. An explicit ZERO is written and
            # then defended like any other value.
            from source_precedence import apply_field as _apply
            _prev = max(_num((part.get("manufacturing_features") or {}).get("pierce_count")) or 0,
                        _num((part.get("geometry_rollup") or {}).get("estimated_pierce_count")) or 0)
            _apply(part, "manufacturing_features.cut_out_count",
                   int(nat.cut_out_count), SOURCE_NAME)
            _w1 = _apply(part, "manufacturing_features.pierce_count",
                         _native_pierces, SOURCE_NAME)
            _w2 = _apply(part, "geometry_rollup.estimated_pierce_count",
                         _native_pierces, SOURCE_NAME)
            # Gated on the writes actually landing. The flag claimed the previous count had
            # been replaced whatever the resolver decided, so a rank-100 estimator value
            # could survive while the audit trail said SolidWorks had overwritten it.
            if _prev and int(_prev) != _native_pierces and (_w1 or _w2):
                part.setdefault("review_flags", []).append(
                    f"pierce_count: {int(_prev)} from an earlier pass replaced by "
                    f"{_native_pierces} from the SolidWorks cut list ({nat.cut_out_count} "
                    f"cut-out(s) + the outer profile). The model is the stronger source; "
                    f"the two disagree, so confirm the drawing shows every cut-out")
            flags.append(
                f"{nat.cut_out_count} cut-out(s) from the SolidWorks cut list — each needs "
                f"its own pierce ({_native_pierces} with the outer profile)"
                if nat.cut_out_count else
                "SolidWorks cut list reports NO cut-outs — a plain blank, one pierce for the "
                "outer profile. This is the model stating it, not missing data")

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
            if _apply_field(p, "normalized_material", nat.material, SOURCE_NAME):
                p.setdefault("review_flags", []).append(
                    f"Material '{nat.material}' from SolidWorks model")
                out["material_set"] += 1
        # Quantity: native BOM roll-up corrects fastener/bought-in counts.
        q = qty_by_pn.get(pn)
        if q is not None and int(q) > 0 and p.get("quantity") != int(q):
            _old = p.get("quantity")
            if _apply_field(p, "quantity", int(q), SOURCE_NAME):
                p.setdefault("review_flags", []).append(
                    f"Quantity {_old} -> {int(q)} from SolidWorks BOM")
                out["qty_corrected"] += 1
        # Weld candidate → flag for the weld/dress route.
        if pn in weld_pns:
            p.setdefault("review_flags", []).append(
                "SolidWorks: welded sub-assembly — confirm weld/dress route")
            out["weld_flagged"] += 1

    return out
