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

THE BACKUP READER (SCRUM-184). Where an extract is needed and the COM analyser cannot run — it
is switched off, there is no SolidWorks on the machine, or its run failed — and SDI_SW_DOCMGR=1,
the SOLIDWORKS Document Manager reader (tools/solidworks/sw_docmgr_analyse.py) is run instead.
It writes the same record schema from what each file SAVED, measures nothing, and marks every
record `"reader": "solidworks_docmgr"`. Values from such an extract are applied under source
`solidworks_docmgr`, ranked below `solidworks_api` and below DXF; what it cannot supply is
reported missing, and a formed part with no saved flat pattern is flagged as needing the
SolidWorks worker. The job meta records which reader produced the extract and why.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from source_precedence import apply_field as _apply_field

# What a bounding box means about a part — one definition, shared with the estimator's
# blank sizing. Soft, because this connector must still run on a machine where an optional
# geometry dependency did not install; the envelope upgrade is then simply not offered.
try:
    import blank_credibility as _bc
except Exception:                                                  # pragma: no cover
    _bc = None                                                     # type: ignore[assignment]

SOURCE_NAME = "solidworks_api"
# A material the model carries only as a library appearance/simulation default — not a spec
# the designer typed. Ranked below the drawing's own callout in source_precedence, so a lone
# SW library material cannot overrule the drawing (MDF stays MDF against a birch-ply visual).
APPLIED_MATERIAL_SOURCE = "solidworks_applied_material"
RELIABILITY = 1.0
EXTRACT_FILENAME = "_sw_native_extract.json"

# ── THE DOCUMENT MANAGER BACKUP READER (SCRUM-184) ─────────────────────────────────────
#
# The same model files, read without SolidWorks: what each file SAVED, nothing rebuilt and
# nothing measured. Its values enter under their own source names so the waterfall can rank
# them below the worker's measurement and below a DXF (source_precedence), and so every value
# on the sheet says which reader produced it.
DOCMGR_SOURCE_NAME = "solidworks_docmgr"
DOCMGR_APPLIED_MATERIAL_SOURCE = "solidworks_docmgr_applied_material"
# A SEPARATE FILE, NOT THE SAME NAME. A backup extract written as _sw_native_extract.json would
# pass the freshness check on the next run — same models, current schema — and be reused for
# ever, so a job read once without a seat would never be read WITH one again. Under its own
# name the next run still tries the worker first, and falls back to this only when it must.
DOCMGR_EXTRACT_FILENAME = "_sw_docmgr_extract.json"
# THE FILES SOLIDWORKS OPENED AND COULD NOT READ, read again by the Document Manager in the
# same run (D-706). Its own name for the same reason as above: the SolidWorks extract is left
# exactly as the worker wrote it, so the next run with a healthy seat reads those files again.
DOCMGR_TOPUP_FILENAME = "_sw_docmgr_topup.json"
# The licence key's NAME. The value is read only to check it is present and to scrub it out of
# any error text; it reaches the reader through the inherited environment, never argv.
DOCMGR_KEY_ENV = "SDI_SW_DOCMGR_KEY"

# THE MODELS DO NOT HAVE TO BE IN THE JOB FOLDER FOR US TO READ THEM.
#
# A staged pack holds exactly the drawings an estimator selected, which is the point of
# staging — but it means the SLDPRT and SLDASM files are back where they started, and a
# connector that looks only in the job folder finds nothing and reports a job with no models.
# That is how 12349-02 was costed from drawings alone three times over, with a full set of
# models one folder away.
#
# Copying models into the pack is the wrong answer: away from their own folder an assembly
# loses the references that resolve its components, and a pack is then tens of megabytes on
# every re-run. So the pack carries their ADDRESS instead, written by staging, and the
# analyser is pointed at them in place. The extract still lands in the job folder, so
# everything downstream is unchanged.
MODEL_SOURCES_FILENAME = "_sdi_model_sources.json"


def model_source_folders(folder: str | Path) -> List[Path]:
    """The folders a staged pack says its models are in, in the order staging listed them.

    Absent file, unreadable file, wrong shape: no folders, no exception. This is a hint about
    where to look, and a malformed hint must degrade to the behaviour we had before it existed.
    """
    try:
        raw = (Path(folder) / MODEL_SOURCES_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    out: List[Path] = []
    for entry in payload.get("models_folders") or []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        p = Path(entry.strip())
        try:
            if p.is_dir():
                out.append(p)
        except OSError:
            continue
    return out


# ── COM PLUMBING IS NOT AN ESTIMATOR'S PROBLEM ────────────────────────────────────────
#
# The analyser writes 29 different notes, and every one of them was being promoted to the
# part's `review_flags` — the list whose entire job is to say "a person should look at this
# line". Most of them are traces the analyser keeps for its own debugging:
#
#     SolidWorks: mdoc_wrapped=CDispatch
#     SolidWorks: first_feature=obj
#     SolidWorks: features_visited=47
#
# None of those is a finding. They appear on EVERY SolidWorks part, so the flags that are
# findings — a flat blank rejected as a folded box, a blank measured by flattening — sit at
# the bottom of a list nobody reads to the end of. A review flag that fires on everything
# tells you nothing about anything, and it makes the ones that matter cost more to find.
#
# THIS BECAME URGENT WITH FLATTENING ON. Self-verification tries several bend states and
# notes each rejection, so a formed part can now add three or four more lines of the same
# kind. Turning the measurement on without this would have traded one silent gap for a
# noisy report — a worse deal than it looks, because noise is how the last defect stayed
# hidden in plain sight.
#
# ERRORS ARE KEPT. `cutlist_err`, `material_name_err`, `feature_walk_error` mean something
# was tried and failed, which is a finding: it is the difference between "we did not read a
# blank" and "we tried to read one and could not".
_COM_TRACE_PREFIXES = ("mdoc_wrapped=", "first_feature=", "features_visited=",
                       "weldment_section=")


def _is_com_trace(note: str, *, flatten_succeeded: bool) -> bool:
    """Is this note the analyser talking to itself rather than to an estimator?"""
    n = str(note or "").strip()
    if n.startswith(_COM_TRACE_PREFIXES):
        return True
    # A rejected bend-state candidate is the self-verification WORKING: the state was tried,
    # the resulting box failed the grow/thickness test, and the next one was tried. Worth
    # keeping only when none of them succeeded — then it is the evidence for why this part
    # has no blank, and somebody will want it.
    if n.startswith("flatten attempt (state") and flatten_succeeded:
        return True
    return False


def _material_source_token(nat: "NativePart") -> str:
    """Which waterfall source a native part's MATERIAL is submitted under. A material the
    model carries only as a library appearance ('applied_library') enters below the drawing
    callout; an explicit custom property — or an older extract that never recorded which it
    was — enters at full model rank, exactly as before. A part read by the Document Manager
    backup reader takes that reader's tokens, one step below each COM counterpart."""
    _applied = str(getattr(nat, "material_source", "") or "") == "applied_library"
    if str(getattr(nat, "source", "") or "") == DOCMGR_SOURCE_NAME:
        return DOCMGR_APPLIED_MATERIAL_SOURCE if _applied else DOCMGR_SOURCE_NAME
    return APPLIED_MATERIAL_SOURCE if _applied else SOURCE_NAME


def _record_reader(record: Dict[str, Any]) -> str:
    """Which reader produced an extract record. A record that does not say is the COM
    analyser's — every extract written before the backup reader existed."""
    return str((record or {}).get("reader") or "").strip() or SOURCE_NAME


def job_source(job: Any) -> str:
    """The waterfall source a whole extract's values enter under."""
    return (DOCMGR_SOURCE_NAME
            if str(((getattr(job, "meta", None) or {}).get("extract_reader")) or "")
            == DOCMGR_SOURCE_NAME else SOURCE_NAME)

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
    # "custom_property" (a spec the designer typed — strongest model source) or
    # "applied_library" (the model's appearance default — must not overrule a drawing callout).
    # Empty on extracts taken before the analyser recorded it, which fall back to the old
    # behaviour (the material is trusted at full model rank), so nothing regresses.
    material_source: str = ""
    is_sheet_metal: bool = False
    bend_count: int = 0
    hole_count_est: int = 0
    flat_pattern: bool = False
    has_weldment: bool = False
    bbox_mm: Optional[List[float]] = None
    # The body's volume and surface area (extract schema v4, SCRUM-180): density-free
    # measures a board whose mass never populates still has. None on older extracts.
    volume_mm3: Optional[float] = None
    surface_area_mm2: Optional[float] = None
    doctype: int = SW_PART
    # ── measured cut-list geometry (the estimating prize a PDF cannot supply) ──
    flat_length_mm: Optional[float] = None
    flat_width_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    bend_radius_mm: Optional[float] = None
    cut_length_mm: Optional[float] = None
    cut_out_count: Optional[int] = None
    blank_area_mm2: Optional[float] = None
    # Tube/hollow-section profile read from the weldment cut list — the frame members a
    # sheet-metal read never sees. {a, b, t, profile_form, length_mm} or None.
    section_profile: Optional[Dict[str, Any]] = None
    surface_treatment: str = ""
    mass_kg: Optional[float] = None
    # Formed solid whose bends are baked into a Base Flange sketch (no countable bend
    # feature). Real folds, un-counted — flagged so the fold op still fires.
    formed_but_no_bend_features: bool = False
    # Imported body with no modelled fabrication features = supplier model = bought in.
    likely_bought_in: bool = False
    # Document Manager backup reads only (SCRUM-184): a formed sheet-metal part whose file
    # saved no flat pattern — the one number that reader cannot produce — and the fields it
    # could not supply at all. Empty on every COM extract.
    needs_solidworks_worker: bool = False
    needs_solidworks_worker_reason: str = ""
    not_saved: List[str] = field(default_factory=list)
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
    # parent -> [(child, qty)] from every SLDASM in the pack, not just the flattened top BOM.
    # THE MODEL ALREADY KNOWS WHO OWNS WHAT. Reading only the top assembly's full-depth
    # component list tells the engine that 05M is somewhere in the job and never that it
    # hangs off 102 — so every question of ownership downstream (which assembly a powder
    # event belongs to, which parent carries a child's material, whether a node is connected
    # at all) is reconstructed from descriptions and part-code shape when the answer was in
    # the file.
    hierarchy: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)

    def parent_of(self, part_number: str) -> str:
        """The assembly this part hangs off, or "" when the model does not say."""
        child = _clean_pn(part_number)
        for parent, kids in self.hierarchy.items():
            if any(_clean_pn(k) == child for k, _ in kids):
                return parent
        return ""

    def material_for(self, part_number: str) -> str:
        p = self.part_signals.get(_clean_pn(part_number))
        return p.material if p else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "meta": self.meta,
            "bom": [vars(r) for r in self.bom],
            "part_signals": {k: vars(v) for k, v in self.part_signals.items()},
            "hierarchy": {k: [list(t) for t in v] for k, v in self.hierarchy.items()},
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


def _bom_codes(record: Dict[str, Any]) -> set:
    return {_clean_pn(l.get("part_number") or "")
            for l in (record.get("bom") or []) if isinstance(l, dict)} - {""}


def _pick_top_assembly(records: List[Dict[str, Any]],
                       ambiguity: Optional[Dict[str, Any]] = None,
                       job_codes: Optional[set] = None
                       ) -> Optional[Dict[str, Any]]:
    """The job's top assembly, whose full-depth BOM becomes the job's component list.

    LARGEST BOM WINS was the whole rule, and on a folder of fifteen assemblies that is a
    coin toss dressed as a decision. 11650 carries test and scratch assemblies beside the
    released ones; a test rig that happens to contain more components than the GA would have
    supplied the entire job's BOM, at rank 90, silently.

    THE STRUCTURAL FACT FIRST. Every SLDASM reports its own edges, so an assembly that
    appears as somebody else's CHILD is by definition not the top of anything. Restricting
    the candidates to roots is exact, needs no naming convention, and is what stops a
    sub-assembly winning on size — which is the common half of this failure.

    WHAT IT CANNOT DECIDE, IT SAYS. A scratch assembly is usually a root too, so several
    roots may remain and nothing in the extract can rank them: that needs the job's own
    drawing numbers, which this function is not given. Size still breaks the tie, because a
    guess is better than no BOM at all — but the competing roots are recorded so the run can
    report that a choice was made rather than presenting it as a reading.
    """
    asms = [r for r in records if r.get("doctype") == SW_ASM and r.get("bom")]
    if not asms:
        return None

    # ── THE DRAWINGS ALREADY SAY WHICH ASSEMBLY THIS IS ─────────────────────────────
    # 11650 proved the roots rule insufficient on its own. Only two assemblies were nobody's
    # child -- "11650-test assy" and "Lock Assembly" -- and the released 11650-00-GA was
    # neither, because the test assembly PARENTS it. So the rule that was written to stop a
    # sub-assembly winning excluded the right answer outright, size picked the test rig, and
    # its component list became the job at rank 90: TOP PANEL went from 1 to 3, SIDE CHANNEL
    # from 2 to 6, on a sheet an estimator would have read as a measurement.
    #
    # The released drawings are the commercial truth and the engine has already read them, so
    # the assembly that matches them IS the job. JACCARD, not raw overlap, because all three
    # wrong shapes fail it in different directions and only intersection-over-union catches
    # all of them: a sub-assembly shares too few of the job's parts, a test rig that contains
    # the GA shares them all and carries extra scaffolding the drawings never mention, and the
    # GA itself matches closely on both sides. No naming convention, and nothing about "test".
    if job_codes:
        scored = []
        for r in asms:
            codes = _bom_codes(r)
            if not codes:
                continue
            union = codes | job_codes
            scored.append((len(codes & job_codes) / len(union) if union else 0.0, r))
        scored.sort(key=lambda t: (-t[0], str(t[1].get("title") or "")))
        if scored and scored[0][0] > 0:
            best, chosen = scored[0]
            if ambiguity is not None:
                ambiguity["top_assembly_chosen_by"] = (
                    f"closest match to the {len(job_codes)} part(s) the drawings name "
                    f"({best:.0%} of the combined list)")
                # A near-tie is still a choice somebody should see.
                _close = [t for t in scored[1:] if best - t[0] < 0.10]
                if _close:
                    ambiguity["top_assembly_candidates"] = sorted(
                        [str(chosen.get("title") or "")]
                        + [str(r.get("title") or "") for _sc, r in _close])
            return chosen

    children = set()
    # WERE THERE ANY EDGES AT ALL. Without this the two cases are indistinguishable: an
    # extract that recorded no tree makes EVERY assembly trivially "nobody's child", so the
    # roots test passes vacuously and the run would claim it had ruled the others out. An
    # older extract with no assembly_edges has ruled out nothing, and must say so.
    any_edges = False
    for r in records:
        if int(r.get("doctype") or SW_PART) != SW_ASM:
            continue
        for e in (r.get("assembly_edges") or []):
            if isinstance(e, dict) and e.get("child"):
                children.add(_clean_pn(e["child"]))
                any_edges = True
    def _own(r):
        return _clean_pn(r.get("assembly_part_number") or r.get("title") or "")
    roots = [r for r in asms if _own(r) and _own(r) not in children] if any_edges else []
    candidates = roots or asms
    chosen = max(candidates, key=lambda r: len(r.get("bom") or []))
    if ambiguity is not None and len(candidates) > 1:
        ambiguity["top_assembly_candidates"] = sorted(
            str(r.get("title") or "") for r in candidates)
        ambiguity["top_assembly_chosen_by"] = (
            f"largest BOM among {len(candidates)} assemblies that are nobody's child"
            if any_edges else
            "largest BOM — no assembly edges were recorded, so nothing could be ruled out")
    return chosen


# ── normalisation ────────────────────────────────────────────────────────────
def normalize_native_extract(records: List[Dict[str, Any]],
                             job_codes: Optional[set] = None) -> NativeJob:
    job = NativeJob()
    if not records:
        return job
    job.found = True

    # WHICH READER PRODUCED THIS EXTRACT. Said by the records themselves, so an extract handed
    # over by path (SDI_SW_EXTRACT_JSON) is ranked by what it IS, not by how it arrived.
    _readers = sorted({_record_reader(r) for r in records
                       if isinstance(r, dict) and r.get("title")})
    job.meta["extract_reader"] = (_readers[0] if len(_readers) == 1
                                  else ("mixed" if _readers else SOURCE_NAME))
    if len(_readers) > 1:
        job.meta["extract_readers"] = _readers
    job.meta["extract_source"] = job_source(job)

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
        _psrc = (DOCMGR_SOURCE_NAME if _record_reader(r) == DOCMGR_SOURCE_NAME
                 else SOURCE_NAME)
        job.part_signals[pn] = NativePart(
            part_number=pn,
            material=str(rs.get("material") or ""),
            material_source=str(rs.get("material_source") or ""),
            is_sheet_metal=bool(rs.get("is_sheet_metal")),
            bend_count=int(rs.get("bend_count") or 0),
            hole_count_est=int(rs.get("hole_count_est") or 0),
            flat_pattern=bool(rs.get("flat_pattern_present")),
            has_weldment=bool(rs.get("has_weldment")),
            bbox_mm=rs.get("bbox_mm"),
            volume_mm3=_num(rs.get("volume_mm3")),
            surface_area_mm2=_num(rs.get("surface_area_mm2")),
            doctype=int(r.get("doctype") or SW_PART),
            flat_length_mm=_num(rs.get("flat_length_mm")),
            flat_width_mm=_num(rs.get("flat_width_mm")),
            thickness_mm=_num(rs.get("thickness_mm")),
            bend_radius_mm=_num(rs.get("bend_radius_mm")),
            cut_length_mm=_num(rs.get("cut_length_mm")),
            blank_area_mm2=_num(rs.get("blank_area_mm2")),
            cut_out_count=(int(_num(rs.get("cut_out_count")))
                           if _num(rs.get("cut_out_count")) is not None else None),
            section_profile=(rs.get("section_profile")
                             if isinstance(rs.get("section_profile"), dict) else None),
            surface_treatment=str(rs.get("surface_treatment") or ""),
            mass_kg=_num(rs.get("mass_kg")),
            formed_but_no_bend_features=bool(rs.get("formed_but_no_bend_features")),
            likely_bought_in=bool(rs.get("likely_bought_in")),
            needs_solidworks_worker=bool(rs.get("needs_solidworks_worker")),
            needs_solidworks_worker_reason=str(rs.get("needs_solidworks_worker_reason") or ""),
            not_saved=[str(f) for f in (rs.get("not_saved") or []) if str(f or "").strip()],
            ops_hint=[str(o) for o in (rs.get("ops_hint") or [])],
            source=_psrc,
        )
        _reject_folded_box_as_flat(job.part_signals[pn])

    # Every document that is itself an assembly — the GA double-count rule keys on this.
    asm_titles = {
        _clean_pn(r.get("title") or "")
        for r in records
        if int(r.get("doctype") or SW_PART) == SW_ASM and _clean_pn(r.get("title") or "")
    }
    job.assembly_pns = sorted(asm_titles)

    # ── THE TREE, FROM EVERY ASSEMBLY, NOT JUST THE TOP ONE ───────────────────────
    # Each SLDASM record reports its own parent->child edges. An edge with no parent named
    # is a DIRECT child of the assembly that record describes, which is the case that
    # matters most: it is what says 05M hangs off 102 rather than off the GA.
    #
    # Edges are read from every assembly record, so a sub-assembly used in two places has
    # both its owners. Nothing here decides anything — it records what the models say, and
    # the canonical compiler arbitrates.
    # THE SAME EDGE IS REPORTED TWICE AND IT IS STILL ONE EDGE. The GA's component list is
    # FULL-DEPTH, so it reports 102 -> 05M; 102's own record reports it too. Adding them
    # gives 05M a quantity of four where the job builds two, and a quantity nobody can trace
    # is worse than one that is merely wrong. Counted within a record, then merged ACROSS
    # records by taking the larger — a deeper record can see instances a shallower one
    # cannot, and neither can see instances that are not there.
    #
    # TWO READERS FOR ONE FACT, because one reader is one silent failure away from none.
    # assembly_bom writes the owner twice — as `assembly_edges` on the record, and as
    # `parent_part_number` on every BOM line it emits. The edge list is the better source
    # (it carries per-instance quantity and survives aggregation), but it is keyed on the
    # document object inside the analyser and is absent entirely from any extract taken
    # before that key existed. The BOM line's own parent is carried in the same JSON the
    # engine already consumes for geometry, so an extract that has one and not the other
    # still yields a tree. Whichever supplied an edge is recorded, so "no hierarchy" can
    # never again mean "we looked in one place".
    _seen_edges: Dict[Tuple[str, str], float] = {}
    _sources: Dict[str, int] = {}
    for r in records:
        if int(r.get("doctype") or SW_PART) != SW_ASM:
            continue
        _own = _clean_pn(r.get("assembly_part_number") or r.get("title") or "")
        _this_record: Dict[Tuple[str, str], float] = {}
        for _e in (r.get("assembly_edges") or []):
            if not isinstance(_e, dict):
                continue
            _child = _clean_pn(_e.get("child") or "")
            if not _child:
                continue
            _parent = _clean_pn(_e.get("parent") or "") or _own
            if not _parent or _parent == _child:
                continue
            _q = _num(_e.get("qty"))
            _this_record[(_parent, _child)] = (_this_record.get((_parent, _child), 0.0)
                                               + (float(_q) if _q and _q > 0 else 1.0))
        if _this_record:
            _sources["assembly_edges"] = _sources.get("assembly_edges", 0) + len(_this_record)
        # THE SECOND READER, and it takes ONLY an EXPLICIT parent. An assembly's BOM is
        # FULL-DEPTH, so a line with no parent recorded is a DESCENDANT of this assembly and
        # not necessarily a child of it — defaulting those to the reporting assembly, as the
        # edge loop above legitimately does for its own edges, would flatten every
        # grandchild onto the top node and call it hierarchy. An edge list omits the parent
        # when the parent IS this record; a BOM line omits it when nobody could resolve it.
        # Same-looking blank, opposite meanings.
        #
        # Quantity here is the aggregate, which is the right number for the edge when every
        # instance hangs off the same parent and an over-count when it does not — so this
        # only ever FILLS a pair the edge list did not report, never overwrites one it did.
        for _line in (r.get("bom") or []):
            if not isinstance(_line, dict):
                continue
            _child = _clean_pn(_line.get("part_number") or "")
            _parent = _clean_pn(_line.get("parent_part_number") or "")
            if not _child or not _parent or _parent == _child:
                continue
            if (_parent, _child) in _this_record:
                continue
            _q = _num(_line.get("qty"))
            if _q is None:
                _q = _num(_line.get("quantity"))
            _this_record[(_parent, _child)] = float(_q) if _q and _q > 0 else 1.0
            _sources["bom_parent"] = _sources.get("bom_parent", 0) + 1
        for _k, _v in _this_record.items():
            _seen_edges[_k] = max(_seen_edges.get(_k, 0.0), _v)
    for (_parent, _child), _q in sorted(_seen_edges.items()):
        job.hierarchy.setdefault(_parent, []).append((_child, _q))
    job.meta["hierarchy_edges"] = sum(len(v) for v in job.hierarchy.values())
    job.meta["hierarchy_parents"] = sorted(job.hierarchy)
    job.meta["hierarchy_sources"] = dict(sorted(_sources.items()))
    job.meta["hierarchy_assembly_records"] = sum(
        1 for r in records if int(r.get("doctype") or SW_PART) == SW_ASM)

    # BOM = the top assembly's full-depth component list, quantities already rolled up.
    _amb: Dict[str, Any] = {}
    top = _pick_top_assembly(records, _amb, job_codes=job_codes)
    if top:
        job.meta["top_assembly"] = top.get("title")
        # THE PRODUCT'S OWN SIZE (D-551): the analyser records every document's bounding box;
        # the top assembly's is the assembled product's envelope, which packing is sized from.
        _tb = [v for v in (_num(x) for x in (top.get("bbox_mm") or [])) if v]
        if len(_tb) == 3:
            job.meta["top_assembly_bbox_mm"] = [round(v, 1) for v in _tb]
        job.meta.update(_amb)
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
                source=(DOCMGR_SOURCE_NAME if _record_reader(top) == DOCMGR_SOURCE_NAME
                        else SOURCE_NAME),
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
    # WHAT THE BACKUP READER COULD NOT SUPPLY, said for the whole job as well as per part, so
    # a reader of the summary learns it without opening every line.
    _dm_parts = [p for p in job.part_signals.values() if p.source == DOCMGR_SOURCE_NAME]
    if _dm_parts:
        job.meta["docmgr_not_saved"] = sorted({f for p in _dm_parts for f in p.not_saved})
        job.meta["docmgr_needs_worker"] = sorted(p.part_number for p in _dm_parts
                                                 if p.needs_solidworks_worker)
    return job


# ── job entry point ──────────────────────────────────────────────────────────
def native_extract_for_job(
    *,
    folder: Optional[str | Path] = None,
    json_path: Optional[str | Path] = None,
    run: bool = False,
    analyser: Optional[str | Path] = None,
    python_exe: Optional[str] = None,
    job_codes: Optional[set] = None,
    docmgr: Optional[bool] = None,
    docmgr_analyser: Optional[str | Path] = None,
) -> Optional[NativeJob]:
    """Resolve + normalise the native extract for a job.

    - json_path given            -> read it.
    - folder given               -> read <folder>/_sw_native_extract.json; if absent and
                                     run=True, invoke the analyser (needs SolidWorks) then read.
    Returns a NativeJob (found=False if nothing native is available — the caller then
    falls back cleanly to the PDF/DXF path).

    THE BACKUP. `docmgr` (default: the SDI_SW_DOCMGR switch) lets the Document Manager reader
    stand in when an extract is needed, the folder holds models, and the COM analyser cannot
    run: run=False (SDI_SW_RUN_ANALYSER=0), no SolidWorks registered on this machine, or the
    analyser run failed. Its extract is written to DOCMGR_EXTRACT_FILENAME beside the COM one
    and read in its place; the job meta records `extract_reader` and `docmgr_backup_reason`.
    With the switch off this function behaves exactly as it did before the backup existed.

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
    _analyse_from: Optional[Path] = Path(folder) if folder is not None else None
    if folder is not None and not native_files_state(folder)["count"]:
        # No models here. If the pack says where they are, that is what to read — the
        # extract still lands in the job folder, so nothing downstream changes.
        for _src in model_source_folders(folder):
            if native_files_state(_src)["count"]:
                _analyse_from = _src
                break
    # THE BACKUP IS ASKED ONLY WHERE THERE ARE MODELS TO READ. A drawings-only folder needs no
    # extract from anybody, and running a reader over nothing would turn every such job into
    # a reported reader failure the moment the switch went on.
    _docmgr_on = docmgr_switch_on() if docmgr is None else bool(docmgr)
    _backup_reason: Optional[str] = None
    _has_models = bool(_docmgr_on and _analyse_from is not None
                       and native_files_state(_analyse_from)["count"])
    _must_run = bool(jp is not None and run and _analyse_from is not None
                     and _should_run(jp, _analyse_from))
    if _must_run and _has_models:
        # NO SOLIDWORKS HERE AT ALL: do not launch an analyser that can only fail, go straight
        # to the reader that needs no seat. Asked only with the switch on, so with it off the
        # analyser is launched exactly as before and its failure reported as before.
        _com_ok, _com_why = solidworks_com_available()
        if not _com_ok:
            _must_run = False
            _backup_reason = f"no SolidWorks on this machine — {_com_why}"
    elif (not run and _has_models and jp is not None
          and _should_run(jp, _analyse_from)):
        _backup_reason = ("the SolidWorks COM analyser is switched off for this run "
                          "(SDI_SW_RUN_ANALYSER=0)")
    try:
        import run_timing as _rt_sw
        if jp is not None and (jp.exists() or _must_run):
            _rt_sw.reuse("solidworks_extract", not _must_run)
    except Exception:                                        # noqa: BLE001
        pass
    if _must_run:
        _produced: List[str] = []
        _run_error = _run_analyser(_analyse_from, analyser=analyser, python_exe=python_exe,
                                   out_path=jp, produced=_produced)
        if _produced and Path(_produced[0]) != jp:
            # It wrote somewhere else — a read-only share, most often. Read what exists,
            # not what was requested.
            jp = Path(_produced[0])
        if _run_error and _has_models:
            _backup_reason = f"the SolidWorks COM analyser failed — {_run_error}"

    _docmgr_meta: Dict[str, Any] = {}
    if _backup_reason and _analyse_from is not None:
        jp, _docmgr_meta = _docmgr_backup(jp, _analyse_from, _backup_reason,
                                          analyser=docmgr_analyser, python_exe=python_exe)

    records = load_native_extract(jp) if jp else []
    # SOLIDWORKS READ SOME FILES AND NOT OTHERS (D-706). A seat that drops out partway through a
    # batch, a model open in a designer's session, a file it will not open: the worker still
    # exits zero with the files it reached, and the rest were left unread. With the backup on,
    # the Document Manager reads exactly those files now, in this run, and their records take
    # the place of the failures. Files SolidWorks did read keep the worker's values.
    _topup_meta: Dict[str, Any] = {}
    if (_docmgr_on and not _docmgr_meta and _analyse_from is not None and jp is not None
            and records and native_files_state(_analyse_from)["count"]):
        records, _topup_meta = _docmgr_topup(records, jp, _analyse_from,
                                             analyser=docmgr_analyser, python_exe=python_exe)
    job = normalize_native_extract(records, job_codes=job_codes)
    job.meta.update(_docmgr_meta)
    job.meta.update(_topup_meta)
    job.meta.setdefault("extract_path", str(jp) if jp else None)
    if (_analyse_from is not None and folder is not None
            and Path(_analyse_from) != Path(folder)):
        # SAID EITHER WAY. Read from somewhere other than the job folder is a fact about
        # where this estimate's geometry came from, and it belongs on the record whether the
        # read succeeded or the analyser never ran.
        job.meta["models_analysed_from"] = str(_analyse_from)

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
            "count": 0, "fingerprint": "", "newest_mtime": 0.0, "files": [],
            "folder_reachable": False}
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
        # A FOLDER WE COULD NOT OPEN AT ALL. Reported separately from "models present and
        # unread", because the actions are different -- reconnect the VPN or map the drive,
        # versus run the analyser -- and because this one has no count to report. Left silent
        # it is the more dangerous of the two: an unreachable share produces a job that says
        # nothing whatsoever about SolidWorks and looks exactly like a job that has no models.
        if _fp_folder and not _state.get("folder_reachable"):
            job.meta["native_folder_unreachable"] = str(_fp_folder)
        _known_models = _state["count"] or (
            native_files_state(_analyse_from)["count"]
            if (_analyse_from is not None and folder is not None
                and Path(_analyse_from) != Path(folder)) else 0)
        if _known_models and not records:
            job.meta["native_present_but_unread"] = True
            job.meta["native_files_present"] = _known_models
            _where = job.meta.get("models_analysed_from") or "the job folder"
            _dm_err = _docmgr_meta.get("docmgr_error")
            job.meta["native_unread_reason"] = (
                (_run_error + (f"; the Document Manager backup also failed — {_dm_err}"
                               if _dm_err else "")) if _run_error else
                (f"{_backup_reason}, and the Document Manager backup failed — {_dm_err}"
                 if _dm_err else None)) or (
                f"native models are in {_where} but no extract has been generated. "
                "Run tools/solidworks/sw_native_analyse.py on a machine with SolidWorks")
    if _topup_meta.get("docmgr_topped_up"):
        # THE COUNTS SAY WHAT THIS RUN HAS, not what the worker alone managed: a file the
        # Document Manager read in place of a failure is read, and only what neither reader
        # could open is still failed.
        _done = {_path_key(p) for p in _topup_meta["docmgr_topped_up"]}
        _n = len(_done)
        job.meta["files_read"] = int(job.meta.get("files_read") or 0) + _n
        job.meta["files_failed"] = max(0, int(job.meta.get("files_failed") or 0) - _n)
        job.meta["extract_errors"] = [e for e in (job.meta.get("extract_errors") or [])
                                      if not (isinstance(e, dict)
                                              and _path_key(e.get("path")) in _done)]
        job.meta["extract_incomplete"] = False
    if _run_error:
        job.meta["analyser_error"] = _run_error
    elif _docmgr_meta.get("docmgr_error"):
        # THE BACKUP WAS ASKED FOR AND IT FAILED. Somebody switched it on because the worker
        # could not run; a reader that then failed too is a fault to fix (the key, the
        # install), not the ordinary drawings-only path, so it is reported as an analyser
        # failure and the invariant layer treats it as one.
        job.meta["analyser_error"] = (f"the SolidWorks Document Manager backup reader failed "
                                      f"({_backup_reason}): {_docmgr_meta['docmgr_error']}")
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
    # "I COULD NOT LOOK" IS NOT "THERE IS NOTHING THERE". A count of zero from a folder that
    # does not exist -- a VPN down, a drive unmapped, a job running from a local copy of the
    # drawings while the models sit on the share -- is indistinguishable downstream from a
    # genuinely drawings-only job, and the second is silent by design. So the reachability is
    # recorded beside the count and the caller must decide which of the two it has.
    out: Dict[str, Any] = {"count": 0, "fingerprint": "", "newest_mtime": 0.0, "files": [],
                           "folder_reachable": False}
    try:
        root = Path(folder)
        if not root.exists():
            return out
        out["folder_reachable"] = True
        found = []
        # THE JOB FOLDER'S OWN MODELS, NEVER A SUB-FOLDER'S (James Gray, 1 Oct 2026: "we should
        # never tackle sub directories / folders"). The analyser reads the same scope —
        # sw_native_analyse.find_sw_files — so the two still agree on what was there to read.
        for p in sorted(root.iterdir()):
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


# The oldest extract schema this engine will trust WITHOUT re-reading the models. Bump it in
# step with sw_native_analyse.EXTRACT_SCHEMA_VERSION whenever the extract gains a field the
# estimate needs. An extract stamped below this is regenerated even when the models have not
# changed — so an analyser CODE fix reaches an OLD job (2019 models, last year's extract)
# automatically, instead of being frozen out by a freshness check that only compares file dates.
_MIN_EXTRACT_SCHEMA_VERSION = 4


def _extract_schema_version(extract_path: Path) -> int:
    """The schema version stamped in an extract, or 0 when it predates versioning / is unreadable.
    Reads the raw JSON (the version is stamped both at the top and in the manifest) and never
    raises — an unreadable version reads as 0, which forces a re-run, the safe direction."""
    try:
        data = json.loads(Path(extract_path).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return 0
    if not isinstance(data, dict):
        return 0
    man = data.get("_manifest") if isinstance(data.get("_manifest"), dict) else {}
    for src in (data, man):
        v = src.get("schema_version")
        try:
            if v is not None:
                return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def _should_run(extract_path: Path, folder: str | Path) -> bool:
    """Run the analyser when there is no extract, the one we have predates the MODELS, or it
    predates the analyser CODE (its schema version is behind what the estimate now needs)."""
    if not extract_path.exists():
        return True
    # THE FIX FOR OLD JOBS. A 2019 model is older than any extract taken since, so a date-only
    # check would reuse last year's extract for ever and never pick up a new field (the weldment
    # tube, material provenance). Re-run when the extract's schema is behind the code — the data
    # we can now read out of the same unchanged models has moved on.
    if _extract_schema_version(extract_path) < _MIN_EXTRACT_SCHEMA_VERSION:
        return True
    # THE FINGERPRINT, NOT THE TIMESTAMP, WHEN THERE IS ONE.
    #
    # These two questions -- "is this extract stale" and "should I regenerate it" -- were
    # answered by DIFFERENT signals, and they disagreed on a real job. Staleness compares the
    # manifest's recorded fingerprint against the files on disk, which is exact. This compared
    # mtimes.
    #
    # Copy-Item PRESERVES LastWriteTime. Twenty-eight models copied into a job folder to build
    # a pack arrived carrying their original 2023 timestamps -- older than the extract already
    # sitting beside them. So the fingerprint said STALE, this said "nothing newer", the
    # analyser was never launched, and the estimate was built on an extract describing a
    # different set of files. The run reported the staleness and gave no hint that the fix had
    # been declined.
    #
    # A deleted or renamed model is invisible to a timestamp too, and that is the same fault
    # in its other direction.
    try:
        state = native_files_state(folder)
    except Exception:
        return False
    try:
        payload = json.loads(extract_path.read_text(encoding="utf-8"))
        manifest = payload.get("_manifest")
        recorded = manifest.get("native_files_fingerprint") if isinstance(manifest, dict) else None
    except Exception:                                        # noqa: BLE001
        recorded = None
    if recorded and state.get("fingerprint"):
        # An empty current fingerprint means the folder could not be read -- a VPN down, a
        # share not mapped -- and re-running the analyser against files it cannot see would
        # replace a good extract with an empty one. Fall through to the timestamp instead.
        return recorded != state["fingerprint"]
    try:
        return state["newest_mtime"] > extract_path.stat().st_mtime
    except Exception:
        return False


def running_elevated() -> Optional[bool]:
    """True when this process is elevated, False when it is not, None when unknowable.

    Three-valued on purpose. On anything but Windows the question does not arise, and
    guessing False there would put a confident sentence about UAC in front of somebody
    running Linux.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())     # type: ignore[attr-defined]
    except Exception:
        return None


# WHAT ELEVATION ACTUALLY DOES TO THIS, WHICH IS NARROWER THAN IT FIRST LOOKS.
#
# Windows will not hand an elevated process a COM server registered by a normal-integrity one.
# So Dispatch("SldWorks.Application") from an admin console cannot ATTACH to a SolidWorks a
# designer already has open — it tries to start a second, elevated instance, which a
# single-seat licence refuses or hangs on.
#
# IT IS NOT TRUE THAT AN ELEVATED RUN CANNOT WORK, and this comment said so for an hour.
# With SolidWorks closed there is nothing to attach to and the analyser starts its own
# instance quite happily, which is how this was run successfully before. Writing the stronger
# claim into the product would have sent somebody to reconfigure a machine that was fine —
# the same shape as the stale hazard note that kept native extraction switched off for weeks.
#
# So the hint is a CANDIDATE cause offered beside the real error, never a verdict. It is worth
# offering because "the analyser exited 1" otherwise sends somebody to check their licence,
# their share and their models, and the answer may be that a colleague has the assembly open.
_ELEVATED_HINT = (
    "This console is ELEVATED. That does not stop the analyser on its own — with SolidWorks "
    "closed it starts its own instance — but an elevated process CANNOT attach to a SolidWorks "
    "someone already has open at normal integrity. If these models are open on this machine, "
    "close them or re-run from a NORMAL PowerShell."
)


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
    # THE INTERPRETER THAT IS ALREADY RUNNING, not whatever `python` means on PATH.
    #
    # The engine is started as `.venv\Scripts\python.exe src\main.py`. Launching the
    # analyser as bare "python" hands it to a DIFFERENT interpreter — the system one, or
    # nothing at all — and that one has no pywin32, so every COM call fails on a machine
    # with a perfectly good SolidWorks seat. The failure is reported rather than silent
    # (invariants raises on analyser_error), but it is reported as "the analyser had a
    # problem" when the actual problem is which python ran it.
    #
    # sw_batch_health.py beside it already resolved this correctly; two ways of finding the
    # interpreter is the same defect as two copies of an exclusion list.
    exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or sys.executable or "python"
    produced = produced if produced is not None else []
    cmd = [exe, str(analyser), str(folder)]
    # THE MEASUREMENT A SEAT IS ACTUALLY FOR, and it had never run from here.
    #
    # The analyser can flatten a formed sheet-metal part in memory and MEASURE its blank,
    # which is the only route that cannot be fooled by SolidWorks reusing the property name
    # 'Bounding Box Length' for both a flat pattern and a weldment's folded envelope. On
    # 12120-01-01M the property route returned 126.39x82.2 where the true blank is
    # 132.39x88.2 — material under-bought, silently, on a part that looked fully sourced.
    #
    # It was gated behind --flatten, and nothing in the pipeline ever passed it. So on every
    # automated estimate the strongest geometry a SolidWorks seat can produce was skipped,
    # and the engine inferred the blank instead — which is its single largest source of
    # inaccuracy. The analyser now defaults it on and refuses to flatten a document somebody
    # already has open, so the cost of running it here is seconds of rebuild per formed part
    # that has no cut-list blank, and nothing else.
    #
    #   SDI_SW_FLATTEN=0   go back to inferring the blank
    if os.getenv("SDI_SW_FLATTEN", "").strip().lower() in {"0", "false", "no", "off"}:
        cmd.append("--no-flatten")
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
                    + (f": {_tail[-1][:300]}" if _tail else "")
                    + (f" — {_ELEVATED_HINT}" if running_elevated() else ""))
        return None
    except FileNotFoundError:
        return f"could not start the SolidWorks analyser — python executable {exe!r} not found"
    except subprocess.TimeoutExpired:
        return "the SolidWorks analyser timed out after 30 minutes"
    except Exception as exc:
        return (f"the SolidWorks analyser could not be run: {exc}"
                + (f" — {_ELEVATED_HINT}" if running_elevated() else ""))


# ── the Document Manager backup (SCRUM-184) ──────────────────────────────────────────

def docmgr_switch_on() -> bool:
    """SDI_SW_DOCMGR=1: let the Document Manager reader stand in when the COM analyser cannot
    run. OFF unless set — a reader that measures nothing is a fallback somebody chooses, and
    with it off nothing about the SolidWorks layer changes."""
    return os.getenv("SDI_SW_DOCMGR", "").strip().lower() in {"1", "true", "yes", "on"}


def solidworks_com_available() -> Tuple[bool, str]:
    """(False, why) only on DEFINITE evidence that the COM analyser cannot reach SolidWorks.

    Two facts settle it: SolidWorks COM exists only on Windows, and an installed SolidWorks
    registers the SldWorks.Application class. Anything this cannot determine counts as
    available, so the analyser is tried and its own failure — which is better evidence than a
    guess here — decides whether the backup runs. Asked only when the backup is switched on."""
    if os.name != "nt":
        return False, "SolidWorks COM exists only on Windows and this machine is not Windows"
    try:
        import winreg                                                # noqa: PLC0415
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "SldWorks.Application"))
    except FileNotFoundError:
        return False, ("SolidWorks is not registered on this machine (no SldWorks.Application "
                       "COM class)")
    except Exception:                                                # noqa: BLE001
        pass
    return True, ""


def _redact_docmgr_key(text: Any) -> str:
    """Error text with the Document Manager licence key removed — the whole key and each of
    its comma-separated grants. Whatever the reader printed before it failed may end up on
    the job record and in a log; the key must not."""
    s = "" if text is None else str(text)
    key = (os.environ.get(DOCMGR_KEY_ENV) or "").strip()
    if not key:
        return s
    for frag in sorted({key} | {f.strip() for f in re.split(r"[,;]", key)}, key=len,
                       reverse=True):
        if len(frag) >= 8:
            s = s.replace(frag, f"[{DOCMGR_KEY_ENV}]")
    return s


def _run_docmgr_analyser(folder: str | Path, analyser: Optional[str | Path] = None,
                         python_exe: Optional[str] = None,
                         out_path: Optional[str | Path] = None,
                         produced: Optional[List[str]] = None,
                         extra_args: Optional[Sequence[str]] = None) -> Optional[str]:
    """Invoke sw_docmgr_analyse.py on a folder — the same subprocess pattern as _run_analyser.
    `extra_args` passes the reader's own options, such as --only-from (D-706).

    Returns None on success or a description of the failure, with the licence key scrubbed
    out. The key is never put on the command line, where any process list would show it; the
    reader takes it from the environment this process already has."""
    if analyser is None:
        analyser = (Path(__file__).resolve().parents[2] / "tools" / "solidworks"
                    / "sw_docmgr_analyse.py")
    exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or sys.executable or "python"
    produced = produced if produced is not None else []
    if not (os.environ.get(DOCMGR_KEY_ENV) or "").strip():
        return (f"{DOCMGR_KEY_ENV} is not set — the SOLIDWORKS Document Manager reads nothing "
                f"without its licence key")
    cmd = [exe, str(analyser), str(folder)]
    if out_path:
        cmd += ["--out", str(out_path)]
    cmd += [str(a) for a in (extra_args or ())]
    try:
        r = subprocess.run(cmd, check=False, timeout=1800,
                           capture_output=True, text=True)
        for _line in reversed((r.stdout or "").splitlines()):
            if _line.startswith("EXTRACT_PATH="):
                produced.append(_line.split("=", 1)[1].strip())
                break
        if r.returncode != 0:
            _tail = (r.stderr or r.stdout or "").strip().splitlines()
            return _redact_docmgr_key(
                f"the Document Manager reader exited {r.returncode}"
                + (f": {_tail[-1][:300]}" if _tail else ""))
        return None
    except FileNotFoundError:
        return (f"could not start the Document Manager reader — python executable {exe!r} "
                f"not found")
    except subprocess.TimeoutExpired:
        return "the Document Manager reader timed out after 30 minutes"
    except Exception as exc:                                         # noqa: BLE001
        return _redact_docmgr_key(f"the Document Manager reader could not be run: {exc}")


def _docmgr_backup(jp: Optional[Path], analyse_from: str | Path, reason: str, *,
                   analyser: Optional[str | Path] = None,
                   python_exe: Optional[str] = None) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Read the models with the Document Manager because the worker could not. Returns the
    extract path to read — the backup's, when it holds a usable record, else `jp` unchanged —
    and the meta that says what happened.

    A backup extract that is still fresh for these files is reused rather than re-read, by the
    same fingerprint test the COM extract gets."""
    meta: Dict[str, Any] = {"docmgr_backup_reason": reason}
    djp = (Path(jp).parent if jp is not None else Path(analyse_from)) / DOCMGR_EXTRACT_FILENAME
    err: Optional[str] = None
    if _should_run(djp, analyse_from):
        produced: List[str] = []
        err = _run_docmgr_analyser(analyse_from, analyser=analyser, python_exe=python_exe,
                                   out_path=djp, produced=produced)
        if produced and Path(produced[0]) != djp:
            djp = Path(produced[0])
        meta["docmgr_ran"] = True
    else:
        meta["docmgr_ran"] = False
    if err:
        meta["docmgr_error"] = err
    meta["docmgr_extract_path"] = str(djp)
    usable = [r for r in (load_native_extract(djp) if djp.exists() else [])
              if isinstance(r, dict) and r.get("title") and not r.get("errors")]
    if not usable:
        return jp, meta
    if jp is not None and Path(jp).exists() and Path(jp) != djp:
        # A COM extract that no longer describes these files, set aside for the backup's read
        # of the files as they are now. Named, so the choice is on the record.
        meta["com_extract_set_aside"] = str(jp)
    return djp, meta


def _path_key(p: Any) -> str:
    return os.path.normcase(os.path.normpath(str(p or "").strip())) if str(p or "").strip() else ""


def _unread_model_paths(records: Sequence[Any]) -> List[str]:
    """The files the SolidWorks worker opened and got nothing from: an error and no title.
    A record with a title and a partial error (say, its bounding box) keeps the worker's
    values; the Document Manager has less to offer on that file, never more."""
    out: List[str] = []
    for r in records:
        if (isinstance(r, dict) and r.get("errors") and not str(r.get("title") or "").strip()
                and str(r.get("path") or "").strip()
                and _record_reader(r) != DOCMGR_SOURCE_NAME):
            out.append(str(r["path"]).strip())
    return out


def _docmgr_topup(records: List[Dict[str, Any]], jp: Path, analyse_from: str | Path, *,
                  analyser: Optional[str | Path] = None,
                  python_exe: Optional[str] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fill the files SolidWorks could not read with the Document Manager's read of them.

    Returns the records to normalise and the meta that says what happened. A top-up already
    taken for the same failures of the same files is reused; anything else is read now. The
    worker's extract is never rewritten."""
    unread = _unread_model_paths(records)
    if not unread:
        return records, {}
    meta: Dict[str, Any] = {
        "docmgr_backup_reason": (f"SolidWorks could not read {len(unread)} of "
                                 f"{sum(1 for r in records if isinstance(r, dict))} model "
                                 f"file(s) in this run"),
    }
    tp = Path(jp).parent / DOCMGR_TOPUP_FILENAME
    want = sorted({_path_key(p) for p in unread})
    have = (load_native_payload(tp) or {}).get("_manifest") if tp.exists() else None
    fresh = bool(isinstance(have, dict) and not _should_run(tp, analyse_from)
                 and sorted({_path_key(p) for p in (have.get("only") or [])}) == want
                 and tp.stat().st_mtime >= Path(jp).stat().st_mtime)
    if not fresh:
        produced: List[str] = []
        lst = Path(jp).parent / (DOCMGR_TOPUP_FILENAME + ".list")
        err: Optional[str]
        try:
            lst.write_text("\n".join(unread) + "\n", encoding="utf-8")
            err = _run_docmgr_analyser(analyse_from, analyser=analyser, python_exe=python_exe,
                                       out_path=tp, produced=produced,
                                       extra_args=["--only-from", str(lst)])
        except OSError as exc:
            err = f"could not write the list of files to read: {exc}"
        finally:
            try:
                lst.unlink()
            except OSError:
                pass
        if produced and Path(produced[0]) != tp:
            tp = Path(produced[0])
        meta["docmgr_ran"] = True
        if err:
            meta["docmgr_error"] = err
    else:
        meta["docmgr_ran"] = False
    meta["docmgr_extract_path"] = str(tp)
    got = {}
    for r in (load_native_extract(tp) if tp.exists() else []):
        if (isinstance(r, dict) and r.get("title") and not r.get("errors")
                and _path_key(r.get("path")) in set(want)):
            got[_path_key(r.get("path"))] = r
    if not got:
        return records, meta
    merged = [r for r in records
              if not (isinstance(r, dict) and _path_key(r.get("path")) in got
                      and r.get("errors") and not str(r.get("title") or "").strip())]
    merged += list(got.values())
    meta["docmgr_topped_up"] = sorted(str(r.get("path")) for r in got.values())
    left = [p for p in unread if _path_key(p) not in got]
    if left:
        meta["docmgr_still_unread"] = left
    return merged, meta


def extract_reader_summary(job: Any) -> Dict[str, Any]:
    """Which reader produced this job's extract, and why — for the estimate summary. The COM
    analyser's extract reports `solidworks_api` and nothing else, exactly as before."""
    m = getattr(job, "meta", None) or {}
    out: Dict[str, Any] = {"source": m.get("extract_source") or SOURCE_NAME,
                           "extract_reader": m.get("extract_reader") or SOURCE_NAME}
    for k in ("docmgr_backup_reason", "docmgr_error", "docmgr_extract_path",
              "docmgr_not_saved", "docmgr_needs_worker", "com_extract_set_aside",
              "docmgr_topped_up", "docmgr_still_unread", "extract_readers"):
        if m.get(k) not in (None, "", [], {}):
            out[k] = m[k]
    return out


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
    # FACED BOARD, AND THE SUBSTRATE IT IS FACED ONTO. MFC is melamine-faced CHIPBOARD,
    # MFMDF is melamine-faced MDF — different sheets at different prices. Ordered so the
    # substrate-bearing spellings are tested before the bare ones and all of them before
    # plain MDF, which would otherwise claim every faced board through the fallback
    # normaliser. This is the third module whose material vocabulary was missing the
    # commonest shop-fitting board; the connector must not depend on another one for it.
    # Only the spellings that NAME their substrate. Bare "melamine faced" says what was done
    # to the sheet, not what the sheet is, and the two candidates are bought at different
    # prices — so it stays unresolved here exactly as it does in the lexicon.
    ("MFMDF",           ("MELAMINE FACED MDF", "MFMDF", "PRE-LAM MDF", "PRELAM MDF")),
    ("MFC",             ("MELAMINE FACED CHIPBOARD", "PRE-LAM CHIPBOARD", "MFC")),
    ("CHIPBOARD",       ("CHIPBOARD",)),
    ("MDF",             ("MDF",)),
    ("PLYWOOD",         ("PLYWOOD", "PLY WOOD")),
    ("TIMBER",          ("OAK", "PINE", "BEECH", "BIRCH", "BALSA", "MAPLE", "TEAK",
                         "SPRUCE", "SOFTWOOD", "HARDWOOD", "TIMBER")),
)


# SOLIDWORKS SAYS "I HAVE NONE" IN WORDS, AND WORDS ARE NOT EVIDENCE.
#
# A model with no material assigned reports the literal string "Material <not specified>".
# That is the API's way of saying the field is EMPTY — it is silence, spelled out — and it
# was being recorded as a material observation at rank 90, the strongest source in this
# engine short of an estimator's own confirmation. So it displaced the drawing's correctly
# read material on every part whose model had none assigned.
#
# 12422-24 is what that costs. Four of its six models carry no material, so the end cap's
# stated MFC was replaced by "Material <not specified>", _is_board could not recognise that
# as board, and a 1434 x 748 melamine-faced panel was costed in the Sheet Steel block at
# steel density: GBP 367.38 of a GBP 373.72 material total, on a job whose real material
# total was GBP 5.92. The route was right, the geometry was right, and the price was wrong
# by two orders of magnitude because a placeholder outranked a measurement.
#
# Matched on the shape rather than the exact sentence: SolidWorks brackets its placeholders
# in angle brackets, and a real material never contains them.
_SW_MATERIAL_PLACEHOLDER_RE = re.compile(
    r"<[^>]*>|\bNOT\s+SPECIFIED\b|\bNONE\b|\bDEFAULT\b|\bUNSPECIFIED\b", re.IGNORECASE)


def sw_material_is_placeholder(raw: Any) -> bool:
    """True when SolidWorks is reporting the ABSENCE of a material, not a material."""
    text = str(raw or "").strip()
    return not text or bool(_SW_MATERIAL_PLACEHOLDER_RE.search(text))


def _norm_sw_material(raw: str) -> str:
    u = str(raw or "").upper().strip()
    if not u or sw_material_is_placeholder(u):
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
                  tail: Dict[str, str], lead: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Resolve a pre-estimate part to a native part number. Exact (whitespace/case
    insensitive) first; then a UNIQUE trailing-segment match, which covers the common
    case where the PDF prints '01M' against the model's '12120-01-01M'. Ambiguous tails
    are refused — a wrong match would put one part's geometry on another."""
    pk = _pn_key(part.get("part_number"))
    if not pk:
        return None
    if pk in exact:
        return exact[pk]
    _hit = tail.get(pk)
    if _hit:
        return _hit
    return (lead or {}).get(pk)


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
    # ONE RESOLVER. This function knew all three spellings and the mirror rule knew one, so
    # the mirror rule found nothing on a real record while its fixtures passed. Both now ask
    # the same question of the same module — a second copy is how one goes stale while the
    # other is fixed.
    from document_builder import flat_blank_mm
    _l, _w = flat_blank_mm(part)

    # ── AND IT MUST ACTUALLY BE THE DXF'S, BECAUSE THE CALLER SAYS SO ────────────────
    #
    # The one caller hands this pair to `arbitrate_flat`, which prints "DXF flat {l} x {w}mm"
    # in every sentence it produces. `flat_blank_mm` answers the general question — what is
    # this part's developed blank, from whichever reader put one there — so a blank written by
    # the PDF's overall dimensions or by geometry inference came back here and was reported to
    # an estimator as a DXF measurement that disagreed with the model.
    #
    # A WRONG CITATION IS WORSE THAN NO FIGURE, which this codebase has now paid for twice:
    # an unsourced number invites checking and a cited one stops it. On 0355255 that sentence
    # sent three people to the DXF reader over a pair the DXF never produced.
    #
    # Where the blank is not the DXF's, nothing is returned and the arbitration says "no DXF
    # blank could be measured" — which is true, and is the sentence that would have ended the
    # hunt on the first reading.
    if _l and _w and not _dxf_backed(part):
        return None, None
    _src = str(part.get("blank_length_mm_source") or "").strip().lower()
    if _l and _w and _src and "dxf" not in _src:
        return None, None
    return _l, _w


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
    # BOTH DIMENSIONS. Only the length was stamped, and the metal is priced on the AREA —
    # so the best source we have was attributing half of every blank it measured. It cost
    # nothing to be silent about, which is exactly why nobody noticed.
    part["blank_length_mm_source"] = SOURCE_NAME
    part["blank_width_mm_source"] = SOURCE_NAME
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


def _docmgr_flat_lands(part: Dict[str, Any], fl: float, fw: float) -> bool:
    """Submit a Document Manager flat through the resolver; True when the part now holds it.

    The COM flat is written directly, as it always has been. A backup read is not entitled to
    that: it ranks below a DXF and below the worker, so it goes through apply_field like any
    other source and a blank something stronger already holds is kept. Agreement counts as
    landing — the value is right and the provenance now names the model file."""
    _apply_field(part, "blank_length_mm", fl, DOCMGR_SOURCE_NAME)
    _apply_field(part, "blank_width_mm", fw, DOCMGR_SOURCE_NAME)
    _l, _w = _num(part.get("blank_length_mm")), _num(part.get("blank_width_mm"))
    return bool(_l is not None and _w is not None
                and abs(_l - fl) < 1e-6 and abs(_w - fw) < 1e-6)


def _docmgr_cross_check_dxf(part: Dict[str, Any], fl: float, fw: float,
                            flags: List[str], out: Dict[str, Any]) -> None:
    """A Document Manager flat held against the part's DXF — a check, never a replacement.

    The same geometric comparison the COM path runs, with one difference that is the whole
    point: the DXF is the winner whatever it says, because a SAVED flat ranks below the cut
    file. Where the two disagree beyond tolerance the part is marked unreconciled, which the
    geometry invariant reports — the size is then unconfirmed, and saying so is the honest
    outcome when the weaker reading is the one that looks complete."""
    _dl, _dw = _dxf_blank_mm(part)
    if not (_dl and _dw):
        flags.append(f"blank check NOT PERFORMED — the part is DXF-backed but no DXF blank could "
                     f"be read to compare against the SolidWorks file's saved flat {fl:g}x{fw:g}mm "
                     f"(Document Manager backup read). The DXF is kept")
        out["geometry_unchecked"] = out.get("geometry_unchecked", 0) + 1
        return
    from geometry_arbitration import arbitrate_flat, DXF
    _v = dict(arbitrate_flat(_dl, _dw, fl, fw))
    # THE ARBITER'S OWN SENTENCE IS NOT REPEATED. It is written for the COM path and may end
    # "costed from the model" — which here would describe the opposite of what was done.
    _v["arbiter_reason"] = _v.get("reason")
    _v["winner"] = DXF
    _v["unreconciled"] = not bool(_v.get("agree"))
    _v["model_reader"] = DOCMGR_SOURCE_NAME
    _ratio = _v.get("area_ratio")
    _v["reason"] = (f"DXF flat {_dl:g} x {_dw:g}mm against the SolidWorks file's SAVED flat "
                    f"{fl:g} x {fw:g}mm (Document Manager backup read)"
                    + (f", area ratio {float(_ratio):.0%}" if _ratio else "")
                    + (" — they agree" if _v["agree"] else
                       " — the DXF is kept, because a saved flat ranks below it"))
    part["flat_arbitration"] = _v
    if _v["agree"]:
        flags.append(f"blank check: {_v['reason']}")
        return
    part["flat_unreconciled"] = True
    out["geometry_conflict"] = out.get("geometry_conflict", 0) + 1
    flags.append(
        f"blank check: the DXF blank {_dl:g} x {_dw:g}mm is KEPT against the SolidWorks file's "
        f"saved flat {fl:g} x {fw:g}mm"
        + (f" (the DXF is {float(_ratio):.0%} of it by area)" if _ratio else "")
        + " — a Document Manager backup read ranks below a DXF and never replaces it. The two "
          "disagree beyond tolerance, so the blank is UNRECONCILED until the SolidWorks worker "
          "or a person settles it")


def _native_match_index(job: NativeJob):
    """The (exact, tail) index every native match runs through. ONE construction.

    It was built inline inside apply_native_to_pre_estimate, so the job-identity check
    below would have had to reproduce it — and a check that reproduces the thing it is
    checking tests its own copy, not the code. That mistake has been made twice today
    already, in fixtures; this avoids making it a third time in production.
    """
    exact = {_pn_key(pn): pn for pn in job.part_signals}
    for r in job.bom:
        exact.setdefault(_pn_key(r.part_number), r.part_number)
    for a in job.assembly_pns:
        exact.setdefault(_pn_key(a), a)
    # Unique trailing-segment index ('12120-01-01M' -> '01M'), built only from keys that are
    # unambiguous; a tail claimed by two parts is dropped from the index entirely.
    _tail_hits: Dict[str, List[str]] = {}
    for k, pn in exact.items():
        seg = k.rsplit("-", 1)[-1]
        if seg and seg != k:
            _tail_hits.setdefault(seg, []).append(pn)
    tail = {k: v[0] for k, v in _tail_hits.items() if len(v) == 1 and k not in exact}
    # LEADING-CODE INDEX. SolidWorks files are routinely named "<code> - <description>", so
    # the document title comes through as "2085-02 - Outer Tube" and the BOM's "2085-02"
    # matches neither exactly nor by trailing segment. On M&S 2085 that refused a GENUINE
    # extract: the model carries 34mm and 20mm bounding boxes for the two tubes, and both
    # were thrown away because a description was appended to the number.
    #
    # THE ALIAS COMES FROM THE DESCRIPTION BOUNDARY, NOT FROM EVERY HYPHEN.
    #
    # The first version split the whitespace-stripped key at every separator, so
    # "12120-01-103" — a code with no description at all — aliased to "12120" AND
    # "12120-01". The second of those is a real sub-assembly on that very job, and it would
    # have taken a leaf part's bounding box, material and bend count. Putting one part's
    # geometry on another is precisely what this module exists to prevent, and the fix for
    # 2085 had reintroduced it by the front door.
    #
    # So the split is done on the ORIGINAL title, at the first whitespace, and only where
    # what follows contains a letter — which is what makes it a description rather than more
    # code. "12120-01-103" has no whitespace and yields nothing.
    _lead_hits: Dict[str, List[str]] = {}
    for _pn in list(job.part_signals) + [r.part_number for r in job.bom] + list(job.assembly_pns):
        _raw = str(_pn or "").strip()
        # AN EXPLICIT DESCRIPTION BOUNDARY: " - ", and nothing looser.
        #
        # "first whitespace, if letters follow" was tried and is too broad. It aliases
        # "1450 GA" to "1450" — and GA is part of a legitimate SDI code, not a description —
        # and "M4 Male Grip Knob" to "M4", where M4 is a thread spec that a BOM line could
        # plausibly carry. Either would put one part's geometry on another.
        #
        # Space-dash-space is what SolidWorks files actually use when a description is
        # appended, and it cannot occur inside a part number. A title without it yields no
        # alias at all, which is the safe direction: an unmatched part costs a measurement,
        # a mismatched one costs a wrong price nobody can see.
        _m = re.search(r"\s+[-\u2013\u2014]\s+", _raw)
        if not _m:
            continue
        _head, _rest = _raw[:_m.start()].strip(), _raw[_m.end():].strip()
        if not _head or not _rest:
            continue
        _k = _pn_key(_head)
        if _k:
            _lead_hits.setdefault(_k, []).append(_pn)
    # Ambiguity is refused exactly as the tail rule refuses it: a code claimed by two
    # documents is dropped from the index entirely rather than resolved by luck of ordering.
    # An assembly cannot claim a part through this tier either — every assembly document is
    # in `exact`, and `k not in exact` excludes it.
    lead = {k: v[0] for k, v in _lead_hits.items()
            if len(set(v)) == 1 and k not in exact and k not in tail}

    # ── THE CODE THE FILES USE IS NOT THE CODE THE DRAWING USES ──────────────────────
    #
    # Job 11350 refused its OWN extract: two parts under top assembly '11350-01-GA' matched
    # none of the job's seven, so the whole model pack was discarded and the right arm ended
    # up priced by an AI market estimate at 97% of the material total. The models carry the
    # material suffix SDI's files have always carried — "11350-01-01M" is the drawing's
    # "11350-01-01" cut in steel — and neither the exact, tail nor lead tier knows that.
    #
    # `part_code_conventions` already encodes the two conventions, and drawing_job_merge and
    # route_compiler already read it. A private fourth copy here is how one of them goes
    # stale, so this is the same module, and a convention learned once is now honoured
    # everywhere a file code has to meet a BOM code.
    #
    # THE MIRROR'S BARE BASE IS DELIBERATELY NOT INDEXED. `alias_targets` offers it as a
    # last resort for packs whose drawing does not list the mirror separately — but on the
    # index side that means letting a MIRRORED model claim the drawing's base line, which is
    # putting one part's geometry on another: exactly what every other tier here refuses.
    # The mirror's own spellings ("<base> MIR", "<base> MIRROR", ...) are indexed and are
    # what a drawing that lists it will match.
    from part_code_conventions import alias_targets, is_mirror_code
    _alias_hits: Dict[str, List[str]] = {}
    for _pn in list(job.part_signals) + [r.part_number for r in job.bom] + list(job.assembly_pns):
        _cands = alias_targets(_pn)
        if is_mirror_code(_pn) and len(_cands) > 1:
            _cands = _cands[:-1]
        for _c in _cands:
            _k = _pn_key(_c)
            if _k and _k not in exact:
                _alias_hits.setdefault(_k, []).append(_pn)
    # Ambiguity refused as everywhere else: two models whose codes reduce to one drawing
    # line are not resolved by luck of ordering, they are dropped.
    for _k, _v in _alias_hits.items():
        if len(set(_v)) == 1:
            exact[_k] = _v[0]

    # ── AND THE CODE THE ENGINE STORES IS NOT THE CODE THE FILE CARRIES ──────────────
    #
    # Every tier above indexes the model's document title. The lookup key is the part's
    # `part_number` AFTER the pipeline has been through it — and normalize_part_code rewrites
    # several shapes on the way past: it strips description bleed from a drawing number
    # ("11650-04-01A-WALL" -> "11650-04-01A"), joins a spaced GA ("1455-C GA" -> "1455-C-GA"),
    # drops a trailing separator, and splits a glued catalogue suffix. The model's title
    # carries none of those rewrites, so on exactly those shapes the index is keyed one way
    # and queried another. The part then loses its flat pattern, its gauge, its bend count and
    # its mass, and falls back to whatever the drawing could be read for — silently, because
    # a miss here has never been an error.
    #
    # Measured against the three-rung matcher on eight realistic titles, four missed:
    # -WALL and -PANEL bleed, "1455-C GA", and "9233-12-GA-UKM". "BI-SCREW" was a fifth until
    # part_identity stopped collapsing it to "BI" this morning, which is the same defect at
    # the other end of the same join.
    #
    # So the title is indexed under the engine's own spelling as well — asking the SAME
    # function the engine asks, rather than adding another opinion about what a part number
    # is. Ambiguity is refused as everywhere else in this builder, and a key already claimed
    # by a real document is never overwritten: a part that owns its spelling outright keeps it.
    try:
        from part_identity import normalize_part_code as _engine_spelling
    except Exception:                                            # noqa: BLE001
        _engine_spelling = None                                  # type: ignore[assignment]
    if _engine_spelling is not None:
        _norm_hits: Dict[str, List[str]] = {}
        for _pn in (list(job.part_signals) + [r.part_number for r in job.bom]
                    + list(job.assembly_pns)):
            _k = _pn_key(_engine_spelling(_pn))
            if _k and _k not in exact:
                _norm_hits.setdefault(_k, []).append(_pn)
        for _k, _v in _norm_hits.items():
            if len(set(_v)) == 1:
                exact[_k] = _v[0]

    return exact, tail, lead


_JOB_NUMBER = re.compile(r"^\s*(\d{3,})")


def _job_numbers(codes: Iterable[Any]) -> Set[str]:
    """The leading job numbers in a set of codes — "11350-01-GA" -> "11350".

    Three digits minimum, so a part called "01-A" contributes nothing rather than claiming
    kinship with every job starting 01. A code that does not start with digits (DBR60,
    BI-NUT) names a catalogue item, not a job, and is silently ignored.
    """
    out: Set[str] = set()
    for code in codes or []:
        m = _JOB_NUMBER.match(str(code or ""))
        if m:
            out.add(m.group(1))
    return out


def extract_is_for_this_job(parts: List[Dict[str, Any]], job: NativeJob,
                            job_identity: Iterable[Any] = ()) -> Dict[str, Any]:
    """Does this extract actually describe the job in front of us?

    AN EXTRACT FOR ANOTHER JOB IS WORSE THAN NO EXTRACT.

    M&S 2085 was costed against `12120_sw_extract_v7.json` — top assembly 12120-01-GA, a
    different customer's job. The connector took it, matched nothing, applied nothing, and
    stamped a `native_extract_partial` BLOCKER describing 12120's unreadable file onto
    2085's estimate. An estimator reading that job was told a released component might be
    missing, about a model pack that has nothing to do with it.

    Here it produced zeros, which is survivable. The failure mode it opens is not: two jobs
    whose part numbers collide — and SDI's are sequential, so -01, -02, -03 collide
    constantly — would have had one job's bounding boxes, materials and bend counts written
    onto the other's parts, silently, at the highest rank in the waterfall.

    The test is evidence, not names. A folder can be called anything and a job can be
    renumbered, but an extract that describes THIS job matches at least one of its parts.
    Zero matches against a non-empty extract means the two are unrelated.

    TWO FAILURES LOOK IDENTICAL HERE, AND ONLY ONE OF THEM IS THIS GUARD WORKING.

    "This extract is a different job's" and "this extract is ours and our matcher does not
    know its naming convention" both produce zero matches, and for a whole session job 11350
    reported the first while suffering the second. The evidence that separates them was in
    the data the entire time: 11350-01-GA and 11350-01-01 share a job number; 12120-01-GA
    and 2085-02 do not.

    That evidence is REPORTED, not acted on. It must not relax the guard — SDI numbers
    sequentially and a shared prefix is exactly how two jobs collide — but a refusal that
    cannot say which failure it is costs days, and the best evidence in the building gets
    thrown away quietly while the sheet still prints a total.

    THE JOB'S OWN NUMBER COUNTS AS THE JOB'S (D-410). The job number was read off the PARTS
    only, so a pack that produced no part records had no job number at all, and its own
    extract — top assembly "12675-01-02 Block Model V2" under job 12675-01, a design-intent
    pack with nothing to mint — was reported as "describes a different job — the pointer is
    wrong". `job_identity` carries the drawing number and the job folder's name: the job's
    identity whether or not a part was minted. It widens only the REPORT of kinship; the
    guard itself (zero matches against a non-empty extract) is unchanged.

    Returns {"belongs", "matched", "candidates", "job_parts", "job_has_no_parts",
             "top_assembly", "shares_job_number", "extract_codes", "job_codes"}.
    """
    exact, tail, lead = _native_match_index(job)
    matched = 0
    for part in parts or []:
        if isinstance(part, dict) and _match_native(part, exact, tail, lead):
            matched += 1

    _extract_codes = sorted({str(pn) for pn in job.part_signals}
                            | {str(a) for a in job.assembly_pns})
    _job_codes = sorted({str(p.get("part_number") or "") for p in (parts or [])
                         if isinstance(p, dict) and p.get("part_number")})
    _top = str((job.meta or {}).get("top_assembly") or "")
    _identity = [str(x) for x in (job_identity or ()) if str(x or "").strip()]
    _job_parts_n = len([p for p in (parts or []) if isinstance(p, dict)])
    return {
        "belongs": bool(matched) or not job.part_signals,
        "matched": matched,
        "candidates": len(job.part_signals),
        "job_parts": _job_parts_n,
        "job_has_no_parts": _job_parts_n == 0,
        "top_assembly": _top,
        "shares_job_number": bool(
            _job_numbers(_extract_codes + ([_top] if _top else []))
            & (_job_numbers(_job_codes) | _job_numbers(_identity))),
        "extract_codes": _extract_codes[:12],
        "job_codes": _job_codes[:12],
    }


def apply_native_hierarchy_to_parts(parts: List[Dict[str, Any]],
                                    job: NativeJob) -> List[Dict[str, Any]]:
    """Stamp the model's parent->child edges onto the parts, as assembly_children.

    THE EDGES WERE READ AND NOTHING CONSUMED THEM. NativeJob.hierarchy has carried every
    SLDASM's own tree since the analyser began reporting it, and the route compiler builds
    its graph from `part["assembly_children"]` — two halves of one fact with no wire
    between them. Built, and not wired, for the fourth time on this branch.

    WHY THIS CLEARS DISCONNECTED NODES. build_part_graph flags any node that is not the top
    assembly and has NO parents. The LLM's assemblies loop ADDS edges rather than replacing
    them, so native edges can only ever give a node a parent it did not have — this cannot
    take one away, and cannot silently move a part from one owner to another.

    A part is stamped only where the model actually names children for it. Nothing is
    invented for an assembly the extract did not open.
    """
    stamped: List[Dict[str, Any]] = []
    if not parts or not getattr(job, "hierarchy", None):
        return stamped
    by_code = {_clean_pn(str(p.get("part_number") or "")).upper(): p
               for p in parts if isinstance(p, dict) and p.get("part_number")}
    # TWO PHASES: STAMP THE PARENTS THAT EXIST, THEN JUDGE THE ONES THAT DON'T. The
    # minting decision below needs to know which children the job's REAL assemblies
    # already claim — and within one call, an existing parent (7332's 101) may be
    # stamped by a later dict entry than a mint candidate (102). All existing-record
    # edges land first, so the claim census the mint consults is complete.
    _items = list((job.hierarchy or {}).items())
    _items.sort(key=lambda kv: by_code.get(_clean_pn(str(kv[0])).upper()) is None)
    for parent, kids in _items:
        target = by_code.get(_clean_pn(str(parent)).upper())
        if target is None:
            # THE PARENT THE MODEL NAMES MAY HAVE NO RECORD OF ITS OWN. On 10975-02 the
            # GA is an assembly page — a drawing number the pack detects but never a part
            # record — so this stamp found nothing to hold the children and the whole
            # tree reported NOT APPLIED while every child it named was sitting in the
            # job. The model's own assembly is the explicit, traceable commercial stage:
            # mint the parent record, but ONLY when at least one of its children names an
            # existing job part (the evidence that this tree belongs to this job), and
            # give it only those children — a model in the folder that no BOM row and no
            # record claims stays out, which is a different, named problem.
            _known_kids = [
                _clean_pn(str(c)) for c, _q in kids
                if _clean_pn(str(c)) and _clean_pn(str(c)).upper() in by_code
                and _clean_pn(str(c)).upper() != _clean_pn(str(parent)).upper()
            ]
            if not _known_kids:
                continue
            # A SECOND TREE OVER THE SAME MEMBERS IS A VARIANT, NOT A SECOND PRODUCT.
            # This mint re-opened 7332's #34: the model tree carries GA2 -> 102 over the
            # SAME five frame parts the real GA -> 101 already owns, and minting them
            # gave the job two priced weldments — legs 2 -> 4, £80.09 -> £111.01, every
            # frame quantity doubled. A candidate whose known children are ALL already
            # claimed by existing assemblies duplicates structure the job has; it is
            # recorded as evidence on the claiming parent and never becomes a record.
            _claimed = {
                _clean_pn(str(c)).upper()
                for p in parts if isinstance(p, dict)
                for c in (p.get("assembly_children") or []) if str(c).strip()
            }
            _kids_up = {k.upper() for k in _known_kids}
            # AN OPPOSITE HAND IS NOT A VARIANT. "Mirror11650-03-GA" shares the slider with
            # 11650-03-GA — that is what a handed pair is — so every member this census could
            # see was already claimed, and 11650-06's handed arm set was kept "as evidence,
            # never priced" while the kit's own BOM lists it: HANDED ARM x3. A parent the
            # naming convention marks as the mirror of a code is its own article.
            try:
                from part_code_conventions import is_mirror_code as _is_mirror
                _handed = _is_mirror(_clean_pn(str(parent)))
            except Exception:                                        # noqa: BLE001
                _handed = False
            if _kids_up and _kids_up <= _claimed and not _handed:
                print(f"   [hierarchy] '{_clean_pn(str(parent))}' NOT minted — every "
                      f"member it names ({', '.join(sorted(_known_kids))}) already "
                      f"belongs to an existing assembly. A model configuration tree over "
                      f"the same members is a VARIANT of the product, not a second one; "
                      f"kept as evidence, never priced.", flush=True)
                for p in parts:
                    if isinstance(p, dict) and any(
                            _clean_pn(str(c)).upper() in _kids_up
                            for c in (p.get("assembly_children") or [])):
                        _flags = p.setdefault("review_flags", [])
                        _msg = (f"the SolidWorks tree also shows these members under "
                                f"'{_clean_pn(str(parent))}' — treated as a model "
                                f"variant of this assembly, not a second product")
                        if _msg not in _flags:
                            _flags.append(_msg)
                        break
                continue
            target = {
                "part_number": _clean_pn(str(parent)),
                "description": "assembly (from the SolidWorks model's own tree)",
                "quantity": 1,
                "is_sub_assembly": True,
                "is_assembly_parent": True,
                "page_roles": ["assembly"],
                "review_flags": [
                    "assembly parent minted from the SolidWorks model's component tree — "
                    "no drawing sheet of its own; it owns structure and assembly labour, "
                    "never material"],
            }
            parts.append(target)
            by_code[_clean_pn(str(parent)).upper()] = target
            kids = [(c, q) for c, q in kids
                    if _clean_pn(str(c)).upper() in {k.upper() for k in _known_kids}]
        existing = [str(c) for c in (target.get("assembly_children") or [])
                    if str(c).strip()]
        seen = {c.upper() for c in existing}
        added = []
        for child, _qty in kids:
            code = _clean_pn(str(child))
            if not code or code.upper() in seen or code.upper() == _clean_pn(str(parent)).upper():
                continue
            existing.append(code)
            seen.add(code.upper())
            added.append(code)
        if not added:
            continue
        # precedence: direct-write ok — a hierarchy EDGE LIST, not an arbitrated datum; the
        # graph unions edges from every source and this only ever adds ones the model read.
        target["assembly_children"] = existing
        target["is_sub_assembly"] = True
        target.setdefault("review_flags", []).append(
            f"hierarchy from the SolidWorks model: {', '.join(added)} "
            f"{'is' if len(added) == 1 else 'are'} held by {target.get('part_number')}")
        stamped.append({"part_number": target.get("part_number"), "children": added})
    return stamped


def hollow_board_takeoff(bbox_mm: Any, volume_mm3: Any, surface_area_mm2: Any
                         ) -> Optional[Dict[str, Any]]:
    """The panel take-off of a HOLLOW board construction modelled as one body, or None.

    12678-01-01J BASE: the drawing's Section B-B shows a mitred plinth box — a top and four
    walls, open beneath, with internal rails — while the model is one part 552 x 125 x 370.
    The plate test (D-512) rightly refuses that box as a board, so nothing gauged it, nothing
    sized it, and the line went out unpriced. The model still knows what it is made of:

      FILL   volume / envelope. A solid block fills it; a board box fills a small fraction.
             Only a fill under one half is read as a hollow construction.
      GAUGE  a constant-thickness board body has volume V = A t and surface S = 2A + P t
             (both faces, plus the edges of perimeter P). Started from 2V/S and corrected
             for the edges of the panels it implies, it converges on the board's thickness.
      PANELS the envelope's faces — top, the two long walls, the two short walls, then the
             second large face — taken in that order while the measured board area (V / t)
             accounts for them; area left over is internal rails of the box's own height.

    Every figure is DERIVED from the model's own geometry, never a category default, and the
    caller enters it provisionally with a question: the drawing's construction still decides.
    """
    try:
        dims = sorted(float(x) for x in (bbox_mm or []) if x)
        V = float(volume_mm3 or 0.0)
        S = float(surface_area_mm2 or 0.0)
    except (TypeError, ValueError):
        return None
    if len(dims) != 3 or V <= 0 or S <= 0 or dims[0] <= 0:
        return None
    H, W, L = dims
    fill = V / (H * W * L)
    if fill >= 0.5:
        return None
    faces = [("top", L, W), ("long wall", L, H), ("long wall", L, H),
             ("short wall", W, H), ("short wall", W, H), ("second face", L, W)]
    t = 2.0 * V / S
    pieces: List[Tuple[str, float, float]] = []
    for _ in range(12):
        A = V / t
        pieces, acc = [], 0.0
        for name, a, b in faces:
            if acc + a * b <= A * 1.02:
                pieces.append((name, a, b))
                acc += a * b
            else:
                break
        rest = A - acc
        if rest > 0.02 * A:
            run = rest / H
            n = max(1, int(-(-run // L)))
            pieces += [("internal rail", run / n, H)] * n
        P = sum(2.0 * (a + b) for _, a, b in pieces)
        denom = S - P * t
        if denom <= 0:
            return None
        t_new = 2.0 * V / denom
        if abs(t_new - t) < 0.01:
            t = t_new
            break
        t = t_new
    if not (3.0 <= t <= min(60.0, H / 2.0)) or len(pieces) < 4:
        return None
    gauge = round(t * 2.0) / 2.0
    grouped: Dict[Tuple[str, float, float], int] = {}
    for name, a, b in pieces:
        k = (name, round(a, 1), round(b, 1))
        grouped[k] = grouped.get(k, 0) + 1
    return {
        "envelope_mm": [L, W, H], "fill": round(fill, 3),
        "volume_mm3": V, "surface_area_mm2": S,
        "gauge_mm": gauge, "gauge_measured_mm": round(t, 2),
        "board_area_m2": round(V / t / 1e6, 4),
        "panels": [{"name": n, "length_mm": a, "width_mm": b, "count": c}
                   for (n, a, b), c in grouped.items()],
    }


def mint_hollow_board_panels(parts: List[Dict[str, Any]], job: "NativeJob") -> List[str]:
    """A hollow board construction is costed as the panels it is made of (SCRUM-180).

    A board LEAF whose model fails the plate test (its thinnest extent is no gauge) but
    whose volume fills under half its envelope is a box made of boards — 12678-01-01J's
    plinth. hollow_board_takeoff reads its gauge and panels from the model's volume and
    surface area; each panel becomes a made record (<code>-P<n>) at that gauge, a child of
    the part, which then stands as their assembly: its material is carried by its panels,
    its own route (machining, edging, fitting) stays on it. Everything enters provisionally
    with one question — the drawing's construction decides. Never a part with a measured
    flat or a DXF, never a bought-in, never a part already split. Returns the parts split."""
    split: List[str] = []
    signals = getattr(job, "part_signals", None) or {}
    if not parts or not signals:
        return split
    try:
        from costed_facts import is_other_sheet_material as _board
    except Exception:                                                # noqa: BLE001
        return split
    by_key = {_pn_key(k): v for k, v in signals.items()}
    held = {_pn_key(p.get("part_number")) for p in parts if isinstance(p, dict)}
    for part in list(parts):
        if not isinstance(part, dict) or part.get("hollow_board_takeoff"):
            continue
        pn = str(part.get("part_number") or "").strip()
        nat = by_key.get(_pn_key(pn))
        if nat is None or nat.has_flat() or _dxf_backed(part):
            continue
        if (part.get("is_assembly_parent") or part.get("is_sub_assembly")
                or part.get("assembly_children") or part.get("is_bought_in")
                or getattr(nat, "likely_bought_in", False)):
            continue
        mat = (part.get("normalized_material")
               or _norm_sw_material(getattr(nat, "material", "") or ""))
        if not (mat and _board(str(mat))):
            continue
        tk = hollow_board_takeoff(nat.bbox_mm, getattr(nat, "volume_mm3", None),
                                  getattr(nat, "surface_area_mm2", None))
        if not tk:
            continue
        g = float(tk["gauge_mm"])
        L, W, H = tk["envelope_mm"]
        why = (f"HOLLOW BOARD CONSTRUCTION FROM THE MODEL: {pn}'s solid measures "
               f"{L:g} x {W:g} x {H:g} mm but fills {tk['fill']:.0%} of that envelope, so "
               f"it is a box made of boards, not a block. Its volume "
               f"({tk['volume_mm3'] / 1e6:.2f} litres) and surface "
               f"({tk['surface_area_mm2'] / 1e6:.3f} m2) give a {g:g} mm board "
               f"(measured {tk['gauge_measured_mm']:g}), {tk['board_area_m2']:.3f} m2 of it, "
               f"costed as the panels below — provisional, from the model alone; the "
               f"drawing's construction decides")
        children: List[str] = []
        for i, pnl in enumerate(tk["panels"], 1):
            code = f"{pn}-P{i}"
            if _pn_key(code) in held:
                continue
            a, b = float(pnl["length_mm"]), float(pnl["width_mm"])
            rec: Dict[str, Any] = {
                "part_number": code,
                "description": f"{part.get('description') or pn} — {pnl['name']} "
                               f"{a:g} x {b:g} x {g:g} mm (from the model's take-off)",
                "quantity": int(pnl["count"]),
                "normalized_material": mat,
                "materials": list(part.get("materials") or [mat]),
                "blank_length_mm": a, "blank_width_mm": b,
                "normalized_geometry": {"blank_length_mm": a, "blank_width_mm": b},
                "geometry_source": "solidworks_native",
                "owning_assembly": pn, "bom_parent": pn,
                "hollow_board_panel_of": pn,
                "is_bought_in": False,
                "page_roles": list(part.get("page_roles") or []),
                "pages": list(part.get("pages") or []),
                "review_flags": [f"panel of {pn}: {why}"],
            }
            for _k in ("surface_finishes", "construction_note_laminate"):
                if part.get(_k):
                    rec[_k] = part.get(_k)
            _apply_field(rec, "normalized_thickness_mm", g, "model_extents_board_gauge")
            # THE CUT TRAVELS WITH THE PANEL. Once the part stands for its panels the
            # route rules its own routing not applicable (an assembly is not routed), so
            # a panel carrying no cut would let the cutting labour vanish. A board panel
            # is cut on the router — the board convention the parent's own line used.
            try:
                from estimator import record_operation as _rec_op
                _rec_op(rec, "cnc_routing", "hollow_board_takeoff", inferred=True)
            except Exception:                                        # noqa: BLE001
                rec.setdefault("inferred_operations", []).append("cnc_routing")
            parts.append(rec)
            held.add(_pn_key(code))
            children.append(code)
        if not children:
            continue
        # precedence: direct-write ok — a structural stamp (the part now stands for its
        # panels), not an arbitrated datum; the material it no longer carries is theirs.
        part["is_assembly_parent"] = True
        part["assembly_children"] = list(part.get("assembly_children") or []) + children
        part["hollow_board_takeoff"] = dict(tk)
        part.setdefault("review_flags", []).append(why)
        try:
            from source_precedence import raise_manufacturing_question as _ask_h
            _ask_h(part,
                   f"{pn} is costed as a {g:g} mm board box from its model",
                   why + ": " + "; ".join(
                       f"{p['count']} x {p['name']} {p['length_mm']:g} x {p['width_mm']:g}"
                       for p in tk["panels"]),
                   "confirm the construction, the board gauge and the panels against the "
                   "drawing's section; correct any panel and the price follows",
                   "solidworks.hollow_board_takeoff")
        except Exception:                                            # noqa: BLE001
            pass
        split.append(pn)
        print(f"   [hierarchy] {pn}: hollow board construction — {len(children)} panel "
              f"line(s) at {g:g} mm from the model's volume and surface", flush=True)
    return split


def _shared_child_split(total: Optional[float],
                        by_parent: Dict[str, Tuple[float, float]]
                        ) -> Tuple[Optional[Dict[str, int]], str]:
    """Per-parent counts for a child under MORE THAN ONE parent, or (None, why not).

    12678-01-06M (SCRUM-105): two ribs in each of two bracket designs. No single
    per-parent count exists, the division rule refused, and 1 per parent was carried —
    the sheet charged 8 of a part the model counts 16 of. The information was there all
    along: the hierarchy held 12 under 101SA (x6) and 4 under 102SA (x2), and
    12/6 = 4/2 = 2 reassembles to exactly 16.

    `by_parent` maps each parent to (the hierarchy's edge figure, that parent's own
    product total). The edge figure is ambiguous by construction: an assembly's own
    document states the count ONE of it takes, while a full-depth document lists one
    sighting per instance — and the hierarchy builder keeps the larger. The model's own
    product total for the child arbitrates which reading the figures carry:

      reading A (already per-parent): every figure is whole and the reassembly
                                      sum(edge x parent_total) equals the total;
      reading B (one sighting per instance): every edge / parent_total divides whole
                                      and the plain sum of the edges equals the total.

    A reading the model's own total corroborates is evidence; both failing — or both
    passing with different answers — is the conflict the caller says out loud. Never a
    figure invented to make the arithmetic tidy.
    """
    if not total or total <= 0 or len(by_parent) < 2:
        return None, "a single parent or no product total is not this rule's case"
    try:
        _vals = [(float(e), float(p)) for e, p in by_parent.values()]
    except (TypeError, ValueError):
        return None, "unreadable edge figures"
    if any(e <= 0 or p <= 0 for e, p in _vals):
        return None, "an empty edge or parent count"
    _whole = lambda x: abs(x - round(x)) < 1e-9 and round(x) >= 1  # noqa: E731
    a_ok = (all(_whole(e) for e, _ in _vals)
            and abs(sum(e * p for e, p in _vals) - float(total)) < 1e-9)
    b_ok = (all(_whole(e / p) for e, p in _vals)
            and abs(sum(e for e, _ in _vals) - float(total)) < 1e-9)
    a_map = {pn: int(round(e)) for pn, (e, _p) in by_parent.items()}
    b_map = {pn: int(round(float(e) / float(p))) for pn, (e, p) in by_parent.items()}
    if a_ok and b_ok and a_map != b_map:
        return None, (f"the model's edge figures reassemble to {total:g} read either "
                      f"way and the two readings disagree")
    if b_ok:
        return b_map, (
            f"the model counts {total:g} in the whole product; its edge figures are "
            f"sightings, one per parent instance ("
            + "; ".join(f"{e:g} under {pn} = {b_map[pn]} x {p:g}"
                        for pn, (e, p) in sorted(by_parent.items()))
            + f"), reassembling to exactly {total:g}")
    if a_ok:
        return a_map, (
            f"the model counts {total:g} in the whole product and its edge figures "
            f"are already per-parent counts ("
            + "; ".join(f"{a_map[pn]} per {pn} x {p:g}"
                        for pn, (e, p) in sorted(by_parent.items()))
            + f"), reassembling to exactly {total:g}")
    return None, (f"neither reading of the edge figures reassembles the model's own "
                  f"product total of {total:g}")


def mint_model_children(parts: List[Dict[str, Any]], job: NativeJob) -> List[str]:
    """Mint a priced record for a model-only child the product reaches (SCRUM-155).

    12678-01-GA: 04M, 05M and 06M hang off the two bracket assemblies in the model tree,
    carry the welding, dressing and powder charged on their parents — and have no record,
    so no material line anywhere holds the bracket steel. reached_bom_item_unaccounted
    fired, the unit cost was short exactly that money, and the only remedy on the sheet
    was a question. The hierarchy pass above wires the EDGES; nothing minted the leaves.

    DELIBERATELY NARROW, the same shape as the D-512 board gauge:
      - only a child an EXISTING parent record claims, so the tree is this job's;
      - only when its own model file read cleanly (part_signals) with sheet geometry the
        costing can price: a flat pattern, or a plate-shaped solid whose smallest extent
        is a plausible gauge at most a quarter of the next dimension — a bolt, a tube
        and a block all fail that test and stay out;
      - never a part SDI's own conventions call bought in, and never a code that already
        has a record;
      - stamped minted_from_model with its question, so the sheet says where the line
        came from and an estimator confirms it against the drawing office.
    A child whose file failed, or whose shape this cannot read, stays unminted and keeps
    the missing-price question — short in the open, never guessed."""
    minted: List[str] = []
    if not parts or not getattr(job, "part_signals", None):
        return minted
    by_code = {_clean_pn(str(p.get("part_number") or "")).upper(): p
               for p in parts if isinstance(p, dict) and p.get("part_number")}
    # Every edge to a record-less child, PER PARENT, with the edge figures kept as a SET:
    # the analyser lists an edge once per instance, configuration and reporting SLDASM,
    # so the list records what was SEEN, never a count (_per_parent_count's own lesson,
    # 11650-06). The parent's per-unit count rides along for the division below.
    edges: Dict[str, Dict[str, Tuple[List[float], float]]] = {}
    for parent, kids in (getattr(job, "hierarchy", None) or {}).items():
        pk = _clean_pn(str(parent)).upper()
        parent_rec = by_code.get(pk)
        if parent_rec is None:
            continue
        try:
            p_qty = max(1.0, float(parent_rec.get("quantity") or 1))
        except (TypeError, ValueError):
            p_qty = 1.0
        for child, q in kids or ():
            ck = _clean_pn(str(child))
            if not ck or ck.upper() in by_code or ck.upper() == pk:
                continue
            try:
                e_qty = max(1.0, float(q or 1))
            except (TypeError, ValueError):
                e_qty = 1.0
            _slot = edges.setdefault(ck, {}).setdefault(_clean_pn(str(parent)),
                                                        ([], p_qty))
            _slot[0].append(e_qty)
    # The child's own full-depth product total, where the flattened BOM states one — the
    # reliable count the division rule needs.
    _bom_totals: Dict[str, float] = {}
    for _row in getattr(job, "bom", None) or []:
        _bk = _clean_pn(str(getattr(_row, "part_number", "") or "")).upper()
        _bq = float(getattr(_row, "quantity", 0) or 0)
        if _bk and _bq > 0:
            _bom_totals[_bk] = _bom_totals.get(_bk, 0.0) + _bq
    for ck, owned_by in edges.items():
        owns = [(pn, qtys, pq) for pn, (qtys, pq) in sorted(owned_by.items())]
        nat = (getattr(job, "part_signals", {}) or {}).get(ck)
        if nat is None:
            continue
        try:
            from bought_in_policy import is_bought_in as _bi
            if getattr(nat, "likely_bought_in", False) or _bi(
                    {"part_number": ck, "description": getattr(nat, "description", "") or ""}):
                continue
        except Exception:                                            # noqa: BLE001
            pass
        L = W = thk = None
        basis = ""
        if nat.has_flat():
            L, W = _num(nat.flat_length_mm), _num(nat.flat_width_mm)
            thk = _num(nat.thickness_mm)
            basis = "its flat pattern"
        if not (L and W):
            _dims = sorted(v for v in (_num(x) for x in (nat.bbox_mm or [])) if v)
            if (len(_dims) == 3 and 0.3 <= _dims[0] <= 60.0
                    and _dims[0] * 4 <= _dims[1]
                    and _plausible_mm(_dims[1]) and _plausible_mm(_dims[2])):
                L, W, thk = _dims[2], _dims[1], (thk or _dims[0])
                basis = "a plate-shaped solid's extents"
        if not (L and W and thk):
            continue
        # THE ROW'S OWN QUANTITY, ON _per_parent_count's OWN BASIS. Two lessons, both
        # paid for on real sheets: the first mint wrote the per-unit total and the
        # compiler multiplied by the parent again (05M on 12678's sheet as a row of
        # 216); and the edge figures are a record of what was SEEN, once per instance
        # and configuration, never a count (11650-06's extender, 3 summed to 6). So:
        # PER PARENT = THE CHILD'S PRODUCT TOTAL ÷ THE PARENT'S, where both exist and
        # divide whole — 6 ribs in the product over 6 bracket assemblies is ONE per
        # bracket. With no usable totals, the DEDUPLICATED edge figure stands where the
        # model states exactly one; and where nothing divides (a shared child whose
        # total cannot be attributed), ONE per parent is carried with the conflict said
        # out loud, for the BOM-ranked edges and the quantity check to decide — never a
        # figure invented to make the arithmetic tidy.
        _parents = sorted({pn for pn, _, _ in owns})
        _total_ck = _bom_totals.get(ck.upper())
        qty = 1
        qty_basis = ""
        if _total_ck and len(_parents) == 1:
            _p_total = owns[0][2]
            if _p_total > 0 and abs(_total_ck / _p_total
                                    - round(_total_ck / _p_total)) < 1e-9:
                qty = max(1, int(round(_total_ck / _p_total)))
                qty_basis = (f"the model counts {_total_ck:g} in the whole product and "
                             f"{_p_total:g} of {_parents[0]}, so one takes {qty}")
        # A SHARED CHILD'S SPLIT, ARBITRATED BY THE MODEL'S OWN TOTAL (SCRUM-105).
        # One figure per parent and the child's product total: _shared_child_split
        # says which reading the figures carry, or refuses out loud.
        qty_by_parent: Optional[Dict[str, int]] = None
        if not qty_basis and _total_ck and len(_parents) > 1:
            _bp: Dict[str, Tuple[float, float]] = {}
            for pn, qtys, pq in owns:
                _figs = sorted(set(qtys))
                if len(_figs) != 1:
                    _bp = {}
                    break
                _bp[pn] = (_figs[0], _bom_totals.get(pn.upper()) or pq)
            if _bp:
                qty_by_parent, _split_basis = _shared_child_split(_total_ck, _bp)
                if qty_by_parent:
                    qty_basis = _split_basis
                    _uniq = sorted(set(qty_by_parent.values()))
                    # The record's one quantity field means "per parent": it carries
                    # the count only where every parent takes the same; otherwise the
                    # per-parent map rides on the record and the route reads it edge
                    # by edge.
                    qty = _uniq[0] if len(_uniq) == 1 else 1
                    if len(_uniq) != 1:
                        qty_basis += (" — the parents take different counts, so the "
                                      "row carries its per-parent split and the route "
                                      "multiplies each edge once")
        if not qty_basis:
            _distinct = sorted({e for _, qtys, _ in owns for e in qtys})
            if len(_parents) == 1 and len(_distinct) == 1 and not _total_ck:
                qty = max(1, int(round(_distinct[0])))
                qty_basis = (f"the model's tree states {qty} per {_parents[0]} "
                             f"(deduplicated edge, no product total to divide)")
            else:
                qty = 1
                qty_basis = (f"no per-parent count divides (product total "
                             f"{_total_ck:g} across {', '.join(_parents)}" if _total_ck
                             else f"the edges state {_distinct} across "
                                  f"{', '.join(_parents)}")
                qty_basis += (" — 1 per parent is carried; the BOM edges and the "
                              "quantity check decide")
        _counts = qty_by_parent or {pn: qty for pn, _, _ in owns}
        per_unit = int(round(sum(_counts.get(pn, qty) * p for pn, _, p in owns))) or 1
        trail = " + ".join(f"{_counts.get(pn, qty):g} per {pn} x{p:g}"
                           for pn, _, p in owns)
        mat = _norm_sw_material(getattr(nat, "material", "") or "")
        rec: Dict[str, Any] = {
            "part_number": ck,
            "description": (getattr(nat, "description", "") or
                            "from the SolidWorks model's own tree"),
            "quantity": qty,
            "normalized_material": mat or None,
            "normalized_thickness_mm": float(thk),
            "blank_length_mm": float(L), "blank_width_mm": float(W),
            "normalized_geometry": {"blank_length_mm": float(L),
                                    "blank_width_mm": float(W)},
            "geometry_source": "solidworks_native",
            "minted_from_model": True,
            "owning_assembly": owns[0][0],
            "review_flags": [
                f"part minted from the SolidWorks model ({basis}): the product tree "
                f"holds it under {', '.join(sorted({pn for pn, _, _ in owns}))} and the "
                f"pack has no sheet for it — quantity basis: {qty_basis}; the tree "
                f"implies x{per_unit} a unit ({trail}); the row carries its own "
                f"per-parent count and the route multiplies, once; its material is "
                f"priced from the modelled blank so the unit is not silently short; "
                f"confirm the count and the part against the drawing office"],
        }
        if qty_by_parent:
            # precedence: direct-write ok — a per-parent COUNT MAP, not an arbitrated
            # scalar; the route reads it edge by edge and ranks it there.
            rec["quantity_by_parent"] = dict(qty_by_parent)
            rec["quantity_by_parent_source"] = (getattr(nat, "source", "") or job_source(job))
        if nat.has_flat():
            rec["native_flat_pattern"] = True
        try:
            from source_precedence import raise_manufacturing_question as _ask_m
            _ask_m(rec,
                   f"{ck} is priced from its model alone",
                   f"minted from the SolidWorks tree ({trail}): blank {float(L):g} x "
                   f"{float(W):g} x {float(thk):g} mm"
                   + (f", {mat}" if mat else "") + " — no drawing sheet of its own",
                   "confirm the part, its size and its material against the drawing "
                   "office, or rule it out of scope",
                   "solidworks.minted_from_model")
        except Exception:                                            # noqa: BLE001
            pass
        parts.append(rec)
        by_code[ck.upper()] = rec
        minted.append(ck)
    if minted:
        print(f"   [hierarchy] {len(minted)} model-only part(s) minted and priced from "
              f"their own files: {', '.join(sorted(minted))}", flush=True)
    return minted


def apply_native_to_pre_estimate(parts: List[Dict[str, Any]], job: NativeJob,
                                 drawn_counts: Optional[Dict[str, int]] = None,
                                 population: Optional[List[Dict[str, Any]]] = None
                                 ) -> Dict[str, int]:
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
      QUANTITY   the full-depth BOM roll-up. `drawn_counts` ({code: how many one parts list
                 prints}, bom_tree.drawn_counts_by_code) corroborates a handed twin the
                 drawing does not name before it is counted with its code; without it the
                 twin is counted as D-379 did. `population` is the job's whole part list
                 when `parts` is only some of it, so a hand already held still counts as
                 listed.
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

    # The TOP assembly is not a line in its own BOM, so the index covers assembly documents
    # too. Without that the GA row falls through and gets costed as if it were a leaf part —
    # the single largest over-count this connector exists to stop.
    asm_keys = {_pn_key(a) for a in job.assembly_pns}
    exact, tail, lead = _native_match_index(job)

    bom_by_pn = {_pn_key(r.part_number): r for r in job.bom}

    # THE MODEL'S OWN PER-PARENT COUNTS, from every SLDASM's edge list: child -> [(parent,
    # qty)]. See QUANTITY below for why the full-depth BOM figure may not be written as the
    # part's quantity, and why these edges are what may.
    per_parent_edges: Dict[str, List[Tuple[str, float]]] = {}
    for _parent, _kids in (getattr(job, "hierarchy", None) or {}).items():
        for _child, _q in (_kids or []):
            per_parent_edges.setdefault(_pn_key(_child), []).append(
                (_clean_pn(str(_parent)), float(_q or 1.0)))

    # A HANDED TWIN THE DRAWING DOES NOT NAME IS THIS CODE'S OTHER HAND (D-379). The model
    # files the opposite hand as its own document ("12173-07-2-02M-H"); the parts list prints
    # the code once per hand ("12173-07-2-02M" on item rows 1 and 3, "PRODUCED IN RH/LH
    # HANDED PAIRS"). Counted by its own file name the model says 1, and that 1 stood
    # against the table's 2 — one trough side. Where the job holds no record for the twin,
    # its count is this code's, so the model is asked for both hands together.
    #
    # A HAND IS LISTED UNDER ANY SPELLING THE DRAWING USES (review of D-379). "Listed" meant
    # the model's own file name, so a drawing that prints the hand as "<code> MIR",
    # "MIRROR <code>" or "Mirror<code>" — or names it by its sheet's "opposite hand of"
    # note — was counted as not listing it, and base 2 + its own line 1 made 3. The engine's
    # one hand reader (drawing_job_merge._mirror_base_of: the code's marker, else the sheet's
    # mirror_of) says which base a record is a hand of; a base with any such record has its
    # hand on the drawing. No new vocabulary: a spelling the reader does not know ("-LH") is
    # caught below by the drawing's own count instead of being guessed at here.
    try:
        from part_code_conventions import mirror_base as _mirror_base
    except Exception:                                            # noqa: BLE001
        _mirror_base = None
    try:
        from drawing_job_merge import _mirror_base_of
    except Exception:                                            # noqa: BLE001
        _mirror_base_of = None
    _held = list(population) if isinstance(population, list) else list(parts)
    _listed = {_pn_key(p.get("part_number")) for p in _held if isinstance(p, dict)}
    _hand_named = set()
    if _mirror_base_of is not None:
        for _p in _held:
            if isinstance(_p, dict):
                try:
                    _hb = _pn_key(_mirror_base_of(_p))
                except Exception:                                # noqa: BLE001
                    _hb = ""
                if _hb:
                    _hand_named.add(_hb)
    _unlisted_twins: Dict[str, List[Any]] = {}
    if _mirror_base is not None:
        for _r in job.bom:
            _base = _pn_key(_mirror_base(str(_r.part_number or "")))
            if _base and _base != _pn_key(_r.part_number) \
                    and _pn_key(_r.part_number) not in _listed \
                    and _base not in _hand_named:
                _unlisted_twins.setdefault(_base, []).append(_r)
    try:
        from source_precedence import raise_manufacturing_question as _raise_question
    except Exception:                                            # noqa: BLE001
        def _raise_question(*_a, **_k):
            return False

    def _per_parent_count(_total: int, _edges: List[Tuple[str, float]]):
        """(per-parent count or 0, its basis, the one parent or None, a note or None) for a
        product total and the model's parent edges. See QUANTITY below; one derivation,
        asked for this code alone and for this code with its unlisted other hand."""
        _parents = {e[0] for e in _edges}
        if len(_parents) == 1:
            # ── PER PARENT = CHILD'S PRODUCT TOTAL ÷ PARENT'S PRODUCT TOTAL ──────────
            #
            # The first cut SUMMED the edge list, and the 11650-06 re-run showed why that
            # is wrong: the model lists the same parent->child edge more than once (per
            # instance, per configuration, per SLDASM that reports it), so one extender
            # per set was summed to SIX per set and costed at 18 — worse than the 9 this
            # was written to fix. The edge list is a record of what was SEEN, not a count.
            #
            # Both full-depth figures ARE counts, and the model states them reliably: the
            # extender is 3 in the product and its set is 3 in the product, so one set
            # takes 3 / 3 = 1. That division is the per-parent figure, and it only stands
            # where it comes out whole. Where the parent has no product total of its own
            # (the top assembly is not a line in its own BOM), its multiplicity is 1 and
            # the child's total is the per-parent count. The edges are consulted only when
            # neither exists, and then deduplicated rather than added.
            _parent = next(iter(_parents))
            _prow = bom_by_pn.get(_pn_key(_parent))
            _ptotal = (float(_prow.quantity) if _prow is not None and _prow.quantity
                       else (1.0 if _pn_key(_parent) in asm_keys else None))
            if _ptotal and _ptotal > 0 and abs(_total / _ptotal
                                               - round(_total / _ptotal)) < 1e-9:
                _q = int(round(_total / _ptotal))
                return _q, (f"per {_parent}: the SolidWorks model counts {_total} in the "
                            f"whole product and {_ptotal:g} of {_parent}, so one takes "
                            f"{_total}/{_ptotal:g} = {_q}"), _parent, None
            if _ptotal and _ptotal > 0:
                # It does not divide. The model is saying something this cannot turn into
                # a per-parent count, so it writes nothing and says so.
                return 0, "", _parent, (
                    f"SolidWorks: {_total} in the whole product does not divide by the "
                    f"{_ptotal:g} of {_parent} — no per-{_parent} count can be derived, "
                    f"so the BOM edge decides")
            _distinct = sorted({q for _p, q in _edges})
            return ((int(round(_distinct[0])) if len(_distinct) == 1 else 0),
                    (f"per {_parent}, from the SolidWorks assembly's own tree "
                     f"({_total} in the whole product, all levels)"), _parent, None)
        if len(_parents) > 1:
            # One part under several parents: no single per-parent count exists, and the
            # full-depth figure would be multiplied again under each of them. The
            # drawing's BOM edges already carry a count per parent, so they decide.
            return 0, "", None, (
                f"SolidWorks: this part sits under {len(_parents)} assemblies "
                f"({', '.join(sorted(_parents))}), {_total} in the whole product — the "
                f"per-assembly counts on the BOM decide, not the product total")
        if getattr(job, "hierarchy", None):
            # The model has a tree and this part is not on it under any parent: the
            # total is not known to be per-parent, and writing it risks the same double
            # roll-up. Kept as the cross-check only.
            return 0, "", None, None
        return _total, "from the SolidWorks assembly BOM (component count, all levels)", \
            None, None

    # THE SOURCE EVERY VALUE BELOW ENTERS UNDER. The COM analyser's extract enters as
    # solidworks_api, exactly as it always has; a Document Manager backup read enters as
    # solidworks_docmgr, which source_precedence ranks below the worker and below a DXF.
    # Decided per part from the record that supplied it, falling back to the extract's.
    _job_src = job_source(job)
    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = _match_native(part, exact, tail, lead)
        if not pn:
            continue
        nat = job.part_signals.get(pn)
        row = bom_by_pn.get(_pn_key(pn))
        _src = (str(getattr(nat, "source", "") or "") if nat is not None else "") or _job_src
        _docmgr = _src == DOCMGR_SOURCE_NAME
        part["solidworks_native"] = True
        part["solidworks_part_number"] = pn
        if _docmgr:
            part["solidworks_reader"] = DOCMGR_SOURCE_NAME
        flags = part.setdefault("review_flags", [])

        # ── THE MODEL'S BOUNDING BOX, KEPT ─────────────────────────────────────────
        #
        # It was read for every part and used for exactly one thing: a tube's cut length.
        # For everything else it was discarded, which meant a part whose recorded blank
        # turned out to be impossible had nothing measured to fall back on — 12392's back
        # panel was rejected as 16 x 3.7 and then priced as a bought-in, on a job whose
        # model states 130 x 1435 x 1.5.
        #
        # A bounding box is NOT a blank: a folded part unfolds longer than the box it
        # folds into, so anything using it is using a floor and must say so. But it is
        # measured, it is the real envelope, and keeping it costs nothing. A reader that
        # wants a floor can now find one instead of finding nothing.
        _bbox_all = [f for f in (_num(v) for v in (getattr(nat, "bbox_mm", None) or [])) if f]
        if _bbox_all:
            part["bbox_mm"] = list(_bbox_all)
            part["bbox_mm_source"] = _src
            _ng_bb = part.setdefault("normalized_geometry", {})
            if isinstance(_ng_bb, dict):
                _ng_bb["bbox_mm"] = list(_bbox_all)

            # ── THE GAUGE IS IN THE ENVELOPE, AND NOBODY WAS READING IT ──────────
            #
            # The thickness branch below fires only when the sheet-metal cut list
            # publishes a thickness. Where it does not — a part modelled as a solid, a
            # cut list the analyser could not reach — the gauge came from whatever else
            # had guessed at it. 12392-02-01M ended up with 1.5 mm stamped
            # llm_full_extract, rank 40, on a part whose SolidWorks envelope is
            # 130 x 1435 x 1.5. The number was right and its provenance was three ranks
            # weaker than the evidence sitting on the same record.
            #
            # This never CHANGES a thickness. It submits the model's envelope depth only
            # where a thickness is already recorded and the envelope agrees with it, so
            # the value cannot move and only the rank can: agreement upgrading provenance,
            # which is what apply_field is for. A part with no recorded thickness is left
            # alone deliberately — the smallest side of a machined block is not a gauge,
            # and there is nothing here to tell a sheet part from one.
            if _bc is not None and _bc.envelope_proves_it_never_leaves_the_plane(
                    _bbox_all, part.get("normalized_thickness_mm")):
                _env_thk = min(_bbox_all)
                if _apply_field(part, "normalized_thickness_mm", _env_thk, _src):
                    flags.append(
                        f"thickness {_env_thk:g}mm confirmed by the model's bounding box "
                        f"({' x '.join(f'{v:g}' for v in sorted(_bbox_all, reverse=True))}"
                        f") — the value was already right, the provenance was not")

        # ── TUBE FRAME: adopt the section the weldment cut list carried ──────────────
        # The frame's tube sizes live in the SolidWorks weldment cut list — a sheet-metal read
        # never sees them, which is why the Wire block came through empty. The analyser now reads
        # the member profile + length from the cut list; adopt it as the part's section_stock so
        # the tube-costing path below (and the workbook's section block) prices it. Only where the
        # part has no section already — a drawing-stated one is never overwritten.
        _nat_section = getattr(nat, "section_profile", None)
        if isinstance(_nat_section, dict) and not part.get("section_stock"):
            part["section_stock"] = dict(_nat_section)
            roles = part.setdefault("page_roles", [])
            if "section" not in [str(r).lower() for r in roles]:
                roles.append("section")
            flags.append(
                f"tube section {_nat_section.get('profile_form')} "
                f"{_nat_section.get('a')}x{_nat_section.get('b')}x{_nat_section.get('t')}mm"
                + (f" x {_nat_section.get('length_mm')}mm" if _nat_section.get('length_mm') else "")
                + " read from the SolidWorks weldment cut list (member description + length) — "
                "verify the profile and length")
            out["section_from_weldment"] = out.get("section_from_weldment", 0) + 1

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
                _bent = any(o in (part.get("textual_operations") or [])
                            for o in ("tube_bending", "rolling"))
                # AN UNDER-READING NUMBER MUST NOT CARRY THE STRONGEST RANK IN THE SYSTEM.
                #
                # For a STRAIGHT section the longest bounding-box side IS the cut length —
                # a measurement, and rank 90 is right. For a BENT one it is the envelope,
                # and the comment above says so: it under-reads. Stamping that at 90 means
                # nothing may correct it — a developed length later printed on the drawing
                # (rank 70) would be REFUSED by precedence in favour of a figure we already
                # know is short, and under-reading a tube is how a job gets quoted short.
                #
                # The flag was doing the honest work and the rank was undoing it. A prose
                # warning is for a person; the rank is what the machine acts on, and the
                # two were saying opposite things. A derivation that adds an assumption
                # steps down — the same rule that puts mirror_of_measured below the flat it
                # mirrors.
                _len_src = "geometry_inference" if _bent else _src
                # THROUGH THE RESOLVER, AND UNDER THE CONVENTION. This wrote `length_source`
                # by hand — a key nothing in the codebase reads, so section length was never
                # arbitrated by anything and never appeared in a provenance trail either.
                # apply_field on a dotted path writes `length_mm_source`, which is the name
                # every reader already looks for.
                if _apply_field(part, "section_stock.length_mm", round(_len, 2), _len_src):
                    out["section_length"] = out.get("section_length", 0) + 1
                    flags.append(
                        f"section cut length {_len:.1f}mm taken from the MODEL's bounding "
                        f"box — the drawing does not print one" +
                        (". The part is also bent, so this is the ENVELOPE, not the "
                         "developed length, and it UNDER-READS: recorded as inferred so a "
                         "stated developed length can still correct it — confirm the cut "
                         "length before quoting" if _bent else ""))

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

        # ── QUANTITY: PER PARENT, NOT PER PRODUCT ────────────────────────────────
        #
        # James Gray, 22 Sep 2026, on the 11650-06 Coffret hospital kit: sliders 24 against
        # a kit of 12, locking tabs 12 against 6, RSB plates 18 against 3, extenders 9
        # against 3 — "don't buy 6 + 12", arrived at by a different road.
        #
        # TWO FACTS UNDER ONE NAME. The native BOM is FULL-DEPTH: its figure for a part is
        # how many the WHOLE PRODUCT contains, already multiplied through every assembly
        # above it. It was written into `quantity`. But `quantity` on a record means how
        # many ONE PARENT takes — route_compiler's _per_parent says so in terms ("both are
        # per-parent statements about the same thing") and multiplies it down the tree. The
        # model outranks the drawing's BOM edge, so the rolled-up total was kept as a
        # per-parent count and then rolled up AGAIN: an extender the model counts 3 of,
        # under a set the kit takes 3 of, came out at 9.
        #
        # So each fact goes under its own name. The model's edge list says how many of this
        # part each parent takes, which IS what `quantity` means, and it is written only
        # where it is unambiguous — one parent. The full-depth figure is kept beside it as
        # `quantity_total_per_unit`, a second road to the same answer that the compiler can
        # check its roll-up against. Where the model has no edges at all, nothing about a
        # parent is known and the full-depth figure is still the best per-parent reading
        # there is, so that case is unchanged.
        if row is not None and row.quantity and row.quantity > 0:
            _total = int(round(row.quantity))
            _edges = list(per_parent_edges.get(_pn_key(pn)) or [])
            _twins = _unlisted_twins.get(_pn_key(pn)) or []
            if _twins:
                # The edges, per parent, summed across the two hands: one parent takes one
                # of each, which is two of this code.
                _tw_total = _total + sum(int(round(_tw.quantity)) for _tw in _twins
                                         if _tw.quantity and _tw.quantity > 0)
                _by_parent: Dict[str, float] = {}
                for _pp, _qq in set(_edges):
                    _by_parent[_pp] = _by_parent.get(_pp, 0.0) + _qq
                for _tw in _twins:
                    for _pp, _qq in set(per_parent_edges.get(_pn_key(_tw.part_number)) or []):
                        _by_parent[_pp] = _by_parent.get(_pp, 0.0) + _qq
                _tw_edges = list(_by_parent.items())
                # ── THE DRAWING'S OWN COUNT CORROBORATES THE FOLD, OR IT IS ASKED ────────
                #
                # The fold assumes the drawing prints this code once per hand. 12173-07-2-GA
                # does — items 1 and 3, so its table counts 2 — and there the model's two
                # documents are the table's two lines. Where the table counts fewer than
                # both hands, the drawing is not carrying the other hand under this code
                # (or carries it under a spelling no reader knows, such as "-LH"), and
                # adding it would be money nobody drew. So the count stays as the drawing
                # lists it, and the question goes to a person. Compared in the unit the
                # write uses: per parent where the model gives one, else the product total.
                _drawn = None
                if drawn_counts is not None:
                    _drawn = drawn_counts.get(_pn_key(part.get("part_number")))
                    if _drawn is None:
                        _drawn = drawn_counts.get(_pn_key(pn))
                _tw_q = _per_parent_count(_tw_total, _tw_edges)[0]
                _want = _tw_q if _tw_q > 0 else _tw_total
                if _drawn is not None and _drawn < _want:
                    _names = ", ".join(str(t.part_number) for t in _twins)
                    _raise_question(
                        part,
                        (f"{part.get('part_number')}: the SolidWorks model files a second hand "
                         f"({_names}) that the drawing does not list, and the drawing's parts "
                         f"list counts this code {_drawn:g} time(s) under its parent against "
                         f"{_want} for both hands"),
                        (f"counted as the drawing lists it — {_names} is not added to "
                         f"{part.get('part_number')}"),
                        ("confirm the hands: if the other hand is made, list it on the drawing "
                         "(or state that this code is made in both hands) and the count "
                         "follows; if it is not, the model's extra document is not part of "
                         "the product"),
                        "solidworks.apply_native_to_pre_estimate")
                    _twins = []
                else:
                    _total, _edges = _tw_total, _tw_edges
            part["quantity_total_per_unit"] = _total
            part["quantity_total_per_unit_source"] = _src
            _q, _basis, _parent, _note = _per_parent_count(_total, _edges)
            # A SHARED CHILD'S SPLIT, ARBITRATED BY THE MODEL'S OWN TOTAL (SCRUM-105).
            # Where no single per-parent count exists, the per-parent figures may still
            # be derivable: one figure per parent plus the product total, and the total
            # says which reading the figures carry. On success the map rides on the
            # record for the route to read edge by edge; a uniform map also submits the
            # one `quantity` through the resolver, exactly as a single-parent count
            # would. On failure the refusal note stands unchanged.
            if _q <= 0 and len({_pp for _pp, _ in _edges}) > 1:
                _bp2: Dict[str, Tuple[float, float]] = {}
                for _pp, _qq in _edges:
                    _figs = _bp2.get(_pp)
                    if _figs is not None and abs(_figs[0] - float(_qq or 0)) > 1e-9:
                        _bp2 = {}
                        break
                    _prow2 = bom_by_pn.get(_pn_key(_pp))
                    _ptot2 = (float(_prow2.quantity)
                              if _prow2 is not None and _prow2.quantity
                              else (1.0 if _pn_key(_pp) in asm_keys else None))
                    if not _ptot2 or not _qq or _qq <= 0:
                        _bp2 = {}
                        break
                    _bp2[_pp] = (float(_qq), _ptot2)
                if len(_bp2) > 1:
                    _split_map, _split_basis = _shared_child_split(float(_total), _bp2)
                    if _split_map:
                        # precedence: direct-write ok — a per-parent COUNT MAP, not an
                        # arbitrated scalar; the route reads it edge by edge and ranks
                        # it there.
                        part["quantity_by_parent"] = dict(_split_map)
                        part["quantity_by_parent_source"] = _src
                        flags.append(f"qty per parent from the model: {_split_basis}")
                        out["qty"] += 1
                        _note = None
                        _uniq2 = sorted(set(_split_map.values()))
                        if len(_uniq2) == 1:
                            _q, _basis = _uniq2[0], _split_basis
            if _note:
                flags.append(_note)
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
                if _apply_field(part, "quantity", _q, _src):
                    flags.append(f"qty {_cur if _cur is not None else '-'} -> {_q} "
                                 f"{_basis}")
                    out["qty"] += 1
                # THE TWIN SENTENCE SAYS WHAT THE RECORD HOLDS. It was written before the
                # count was tried, so it claimed "counted with this code" where the write
                # was refused or no per-parent count could be derived. Now it is said only
                # where the record holds the count that includes the other hand.
                if _twins and _num(part.get("quantity")) == _q:
                    flags.append(
                        f"SolidWorks: the model files the other hand as "
                        f"{', '.join(str(t.part_number) for t in _twins)}, which the drawing "
                        f"does not list — counted with this code: {_q} "
                        + (f"per {_parent}" if _parent else "in the product"))

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
            # NAMED, NOT JUST COUNTED. The count reached the console and nothing else; the
            # AI Provenance tab's identity block names the part so an estimator can say
            # "that is the setup block" without opening the model folder.
            out.setdefault("not_in_bom_parts", []).append(          # type: ignore[union-attr]
                str(part.get("part_number") or part.get("name") or "?"))

        if nat is None:
            continue

        # ── WHAT THE BACKUP READER COULD NOT SUPPLY, SAID ON THE PART ─────────────
        # A Document Manager read has no bounding box, volume or surface area by construction,
        # and a mass or flat pattern only where the file saved one. Each is MISSING on this
        # record — nothing below infers it from anything nearby — and the estimator is told
        # which, once, rather than left to notice what is absent.
        if _docmgr and nat.not_saved:
            _ns = (f"SolidWorks Document Manager (backup reader): {', '.join(nat.not_saved)} — "
                   f"not saved in the file; only the SolidWorks worker measures them. Nothing was inferred "
                   f"in their place")
            if _ns not in flags:
                flags.append(_ns)
            part["solidworks_not_saved"] = list(nat.not_saved)

        # ── SURFACE THE ANALYSER'S OWN REJECTIONS ────────────────────────────────
        # A value the geometry gates threw out (a folded box read as a flat, an impossible
        # thickness) must reach the estimator. Discarding it silently leaves the part
        # looking merely un-measured, when in fact we READ something and judged it wrong —
        # which is a different thing, and the estimator needs to know which.
        _measured = any("MEASURED by flattening" in _n for _n in nat.notes)
        for _n in nat.notes:
            if _is_com_trace(_n, flatten_succeeded=_measured):
                continue
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
            # The source the material enters under depends on WHERE the model got it. A typed
            # custom property is the spec (full model rank); a library-applied appearance is a
            # default that must lose to the drawing's own callout. An older extract that never
            # recorded which it was enters at full rank, exactly as before.
            _mat_src = _material_source_token(nat)
            _applied_only = _mat_src in (APPLIED_MATERIAL_SOURCE, DOCMGR_APPLIED_MATERIAL_SOURCE)
            if new_mat and not cur_mat:
                if _apply_field(part, "normalized_material", new_mat, _mat_src):
                    flags.append(f"material '{new_mat}' from the SolidWorks model "
                                 f"(applied material: {nat.material})")
                    out["material"] += 1
            # ONE MATERIAL, TWO SPELLINGS, NO CONFLICT (D-511). The drawing reads
            # "MILD STEEL" and the model "MILD_STEEL"; flagging that as a material
            # disagreement sends an estimator to check a difference that does not exist.
            # Equality is judged with separators collapsed; the recorded value keeps the
            # spelling it arrived with.
            _same_mat = (new_mat and cur_mat
                         and re.sub(r"[\s_\-]+", " ", new_mat) == re.sub(r"[\s_\-]+", " ", cur_mat))
            if new_mat and cur_mat and _same_mat:
                # Same answer from a stronger source. Nothing changes on screen; what changes
                # is that the value now rests on the model rather than on the drawing text,
                # and a later pass can no longer quietly replace it.
                _apply_field(part, "normalized_material", cur_mat, _mat_src)
            elif new_mat and cur_mat and not _same_mat:
                _cross_family = (
                    (new_mat in _NON_METAL_FAMILIES and cur_mat in _METAL_FAMILIES)
                    or (new_mat in _METAL_FAMILIES and cur_mat in _NON_METAL_FAMILIES)
                )
                if _cross_family and not _applied_only:
                    # A wood/board part is definitively not steel (and vice versa). The
                    # model is authoritative on what the designer specified — override
                    # the engine's family default and say so. Only when the model carries a
                    # SPEC, though: a bare library appearance is not evidence of family, so an
                    # applied-only material falls through to the ranked submit below and loses
                    # to the drawing's own word.
                    # Gated on the RESULT. A rank-100 estimator correction can legitimately
                    # survive this, and claiming "overridden" when it did not is a review
                    # flag that describes something the engine did not do.
                    if _apply_field(part, "normalized_material", new_mat, _mat_src):
                        flags.append(f"material '{cur_mat}' overridden to '{new_mat}' from the "
                                     f"SolidWorks model ('{nat.material}') — wrong material FAMILY")
                        out["material"] += 1
                else:
                    # SAME FAMILY, DIFFERENT GRADE (or an applied-only material of any family) —
                    # still submitted, at whichever rank its provenance earns. This branch used
                    # to decide the outcome itself and never call the resolver at all, on the
                    # reasoning that the printed title block is what the shop buys to. That
                    # reasoning is a rank judgement, and rank is not this function's to make:
                    # it kept the drawing value even against an estimator's own correction,
                    # and it left the datum carrying the weaker source so a later pass could
                    # still move it. Submit; let apply_field decide and record the conflict.
                    if _apply_field(part, "normalized_material", new_mat, _mat_src):
                        _how = ("appearance default, not a spec" if _applied_only
                                else "same family, different grade")
                        flags.append(f"material '{cur_mat}' -> '{new_mat}' from the SolidWorks "
                                     f"model ('{nat.material}') — {_how}")
                        out["material"] += 1
                    else:
                        _why = ("SolidWorks material is a library appearance, not a spec"
                                if _applied_only else "kept the drawing value")
                        flags.append(f"material check: drawing '{cur_mat}' vs SolidWorks "
                                     f"'{new_mat}' ('{nat.material}') — {_why}")
                        out["material_conflict"] += 1

        # ── GEOMETRY: the sheet-metal cut list ───────────────────────────────────
        # A BLANK THE MODEL GAVE US AND WE REFUSED. has_flat() holds the sanity window, and
        # the comment beside that window has always said an out-of-range value is "not used
        # (and is flagged)" — it was not flagged anywhere. So the strongest measurement in the
        # building could be discarded with no trace, and the part fell back to a DXF or a
        # drawing while the sheet said nothing had been overruled. 2500mm is the long edge of
        # a standard sheet, so anything longer is usually a unit error or a multi-sheet
        # weldment, and either is worth a person's eye rather than silence.
        if (not nat.has_flat()) and (nat.flat_length_mm or nat.flat_width_mm):
            flags.append(
                f"the model's flat blank {nat.flat_length_mm}x{nat.flat_width_mm}mm falls "
                f"outside the plausible window ({_MIN_BLANK_MM:g}-{_MAX_BLANK_MM:g}mm) and "
                f"was NOT used — this part is costed from a weaker source. Check for a unit "
                f"error in the cut list, or a blank that genuinely spans more than one sheet.")
        if nat.has_flat():
            fl, fw = float(nat.flat_length_mm), float(nat.flat_width_mm)
            if _dxf_backed(part) and _docmgr:
                # A SAVED FLAT NEVER REPLACES A DXF. The arbitration below lets the model's
                # flat supersede a DXF that measured materially less — a judgement that rests
                # on the model's flat being a fresh measurement. A Document Manager read is
                # the flat as last SAVED, unrebuilt and unchecked against the solid, and it
                # ranks below the DXF; so the DXF is kept whatever the comparison says, and a
                # disagreement is recorded as unreconciled for a person to settle.
                _docmgr_cross_check_dxf(part, fl, fw, flags, out)
            elif _dxf_backed(part):
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
                            f"{_verdict['reason']}. "
                            + ("Check the DXF export — the file carries a border or another "
                               "sheet's extents beside the profile"
                               if _verdict.get("dxf_is_extents") else
                               "Check the DXF export — the file does not contain the whole "
                               "part"))
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
            elif not _docmgr or _docmgr_flat_lands(part, fl, fw):
                # The COM analyser's flat is written as it always was. A Document Manager flat
                # reaches this branch only once the resolver has accepted it under
                # solidworks_docmgr — so a blank a stronger source already holds is kept.
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
                flags.append(
                    f"flat blank {fl:g} x {fw:g}mm from the SolidWorks sheet-metal "
                    f"cut list (modelled flat pattern — measured, not inferred)" if not _docmgr
                    else
                    f"flat blank {fl:g} x {fw:g}mm from the SolidWorks sheet-metal cut list "
                    f"as SAVED in the file (Document Manager backup read: SolidWorks' own flat, "
                    f"not rebuilt and not checked against the solid; ranked below a DXF and "
                    f"below the SolidWorks worker)")
                out["flat"] += 1
                # CUT LENGTH. Laser run time is driven by profile length, so a part with a
                # real blank but no cut length would be costed as if it took no cutting at
                # all — under-costing, which is the direction that loses money.
                gr = part.setdefault("geometry_rollup", {})
                # A MEASUREMENT ARBITRATES; IT DOES NOT QUEUE.
                #
                # This wrote the model's cut length only when the rollup was EMPTY — a
                # gap-fill, where every other native datum in this module goes through the
                # resolver and wins on rank. So whatever reached the record first kept the
                # field, however weak it was, and the strongest source in the engine was
                # refused without a comparison ever being made.
                #
                # 12422-24-02M is what that costs. It has no DXF, so its outline came from
                # the GA's vector paths: 8215.26mm. Its cut list says 746.91mm, measured
                # (outer 485.32 + inner 261.59). The sheet's laser calculator was handed an
                # internal-cut distance of 7832mm against a true figure near 364mm, and only
                # the throughput floor stopped it reaching the price — so the part cut at a
                # DEFAULT rate instead of its real one, and the 20x error was invisible.
                if isinstance(gr, dict):
                    if nat.cut_length_mm and nat.cut_length_mm > 0:
                        _apply_field(part, "geometry_rollup.estimated_cut_length_mm",
                                     float(nat.cut_length_mm), _src,
                                     note=(f"cut length {nat.cut_length_mm:,.2f}mm from the "
                                           f"SolidWorks cut list — measured on the model"
                                           if not _docmgr else
                                           f"cut length {nat.cut_length_mm:,.2f}mm from the "
                                           f"SolidWorks cut list as SAVED in the file "
                                           f"(Document Manager backup read)"))
                        gr.pop("estimated_cut_length_is_floor", None)
                        gr.pop("cut_length_basis", None)
                    elif not _num(gr.get("estimated_cut_length_mm")):
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

        # ── A FORMED PART WITH NO SAVED FLAT: NEEDS THE SOLIDWORKS WORKER ──────────
        # The developed blank of a folded part is the one number a Document Manager read
        # cannot produce: it exists only if SolidWorks saved a flat pattern into the cut list,
        # and on this part it did not. The COM analyser would flatten the part and MEASURE it;
        # this reader cannot, and its bounding box is not saved either. So nothing is written
        # here — no folded envelope standing in for a blank, no floor — and the part says,
        # in the open, that its blank waits on the worker. A DXF already on the part is the
        # cut file and stands; only a part with no DXF is left with the question.
        if _docmgr and nat.needs_solidworks_worker and not nat.has_flat():
            _why_w = nat.needs_solidworks_worker_reason or (
                "formed sheet-metal part with no flat pattern saved in its file")
            if _dxf_backed(part):
                flags.append(f"SolidWorks Document Manager: {_why_w} — the DXF's blank stands; "
                             f"the model offered nothing to check it against")
            else:
                part["needs_solidworks_worker"] = True
                part["needs_solidworks_worker_reason"] = _why_w
                flags.append(
                    f"NEEDS THE SOLIDWORKS WORKER: {_why_w}. No blank was taken from the model "
                    f"and none was guessed; until the worker (or a DXF) measures it, any blank "
                    f"on this line comes from the drawing and is not a measurement")
                try:
                    from source_precedence import raise_manufacturing_question as _ask_w
                    _ask_w(part,
                           f"{part.get('part_number')}: developed blank not measured — the "
                           f"SolidWorks file saved no flat pattern",
                           f"{_why_w}; the backup reader measures nothing, so the blank is not "
                           f"taken from the model",
                           "run the SolidWorks worker (sw_native_analyse.py on a machine with a "
                           "seat) or supply the part's DXF, and re-run the estimate",
                           "solidworks.docmgr_needs_worker")
                except Exception:                                    # noqa: BLE001
                    pass
                out["needs_solidworks_worker"] = out.get("needs_solidworks_worker", 0) + 1
                out.setdefault("needs_solidworks_worker_parts", []).append(  # type: ignore[union-attr]
                    str(part.get("part_number") or pn))

        # ── THICKNESS ────────────────────────────────────────────────────────────
        # A GAUGE NEEDS A SHEET BODY BEHIND IT. On 12567-05-02M the model gave no flat
        # pattern and no mass — nothing that could be costed — and still published a
        # "thickness" of 12 mm, which is the depth of the folded end cap (its 10 mm
        # returns plus the sheet), not a gauge. Submitted at model rank it would have
        # outranked the 1.5 mm the hand it mirrors was measured at. A cut-list thickness
        # is a sheet-metal reading; with no sheet-metal body reported the figure is kept
        # on the record as a note and not offered as the gauge (D-265).
        _no_sheet_body = (not (nat.flat_length_mm or nat.flat_width_mm)
                          and not (nat.mass_kg and nat.mass_kg > 0))
        # A PLASTIC OR BOARD SHEET HAS NO FLAT PATTERN AND MAY HAVE NO MASS (D-399). The
        # rule above is a sheet-METAL rule: a flat pattern is what SolidWorks gives a
        # sheet-metal body, and a library appearance carries no density, so a 2 mm PETG lens
        # modelled as a 297 x 212 x 2 box fails both tests and its one true gauge was
        # refused, leaving the family default (3 mm) to fill the gap. Where the part's own
        # material is a sheet the Other Sheet block prices and the solid is one thickness
        # thick (_is_flat_solid), the model's thickness IS the gauge, at model rank.
        _plastic_sheet_solid = False
        if _plausible_thk(nat.thickness_mm) and _no_sheet_body and _is_flat_solid(nat):
            try:
                from costed_facts import is_other_sheet_material as _other_sheet
                _own_mats = [str(m.get("raw") if isinstance(m, dict) else m)
                             for m in (part.get("materials") or [])]
                _plastic_sheet_solid = any(_other_sheet(m) for m in _own_mats) or (
                    not part.get("material_inherited_from")
                    and _other_sheet(part.get("normalized_material") or "")) or bool(
                    _other_sheet(_norm_sw_material(nat.material)) and not _own_mats)
            except Exception:                                        # noqa: BLE001
                _plastic_sheet_solid = False
        if _plastic_sheet_solid:
            thk = float(nat.thickness_mm)
            if _apply_field(part, "normalized_thickness_mm", thk, _src):
                flags.append(f"thickness {thk:g}mm from the SolidWorks solid: a {_bbox_text(nat)} "
                             f"sheet one thickness thick, in a material the Other Sheet block "
                             f"prices — no flat pattern because it is not sheet metal")
                out["thickness"] += 1
            # A FLAT SOLID'S EXTENTS ARE ITS BLANK (D-402). A sheet one thickness thick has
            # nowhere to fold, so its envelope IS the rectangle it is cut from — and with no
            # flat pattern and no DXF the part was otherwise left to the document-text scan,
            # which handed 9598-02-02G (a 210 x 148.5 card) the frame's 471.61 flat length and
            # the sheet's 841 as an 841 x 471.61 blank. The model's extents at model rank,
            # where nothing measured the blank; a DXF or a native flat still wins.
            if not _dxf_backed(part) and not nat.has_flat():
                _ext = sorted([v for v in (_num(x) for x in (nat.bbox_mm or [])) if v],
                              reverse=True)[:2]
                if len(_ext) == 2 and all(_plausible_mm(v) for v in _ext):
                    _was = (_num(part.get("blank_length_mm")), _num(part.get("blank_width_mm")))
                    _wrote = _apply_field(part, "blank_length_mm", _ext[0], _src)
                    _wrote = _apply_field(part, "blank_width_mm", _ext[1], _src) or _wrote
                    if _wrote:
                        ng = part.get("normalized_geometry")
                        ng = dict(ng) if isinstance(ng, dict) else {}
                        ng["blank_length_mm"], ng["blank_width_mm"] = _ext[0], _ext[1]
                        part["normalized_geometry"] = ng
                        part["overall_length_mm"], part["overall_width_mm"] = _ext[0], _ext[1]
                        flags.append(
                            f"blank {_ext[0]:g} x {_ext[1]:g}mm from the SolidWorks solid's "
                            f"extents — a flat sheet one thickness thick, so its envelope is "
                            f"the rectangle it is cut from"
                            + (f"; replaces {_was[0]:g} x {_was[1]:g}mm read off the document "
                               f"text, which was another part's size"
                               if _was[0] and _was[1] else ""))
                        out["flat"] += 1
        elif _plausible_thk(nat.thickness_mm) and _no_sheet_body:
            flags.append(
                f"the model reports {float(nat.thickness_mm):g}mm as thickness for a part with "
                f"no flat pattern and no mass — not a sheet-metal cut-list reading, so it is "
                f"recorded and NOT used as the gauge; the gauge comes from the drawing or the "
                f"hand this part mirrors")
            out["rejected_values"] = out.get("rejected_values", 0) + 1
        elif _plausible_thk(nat.thickness_mm):
            thk = float(nat.thickness_mm)
            cur_thk = _num(part.get("normalized_thickness_mm"))
            if not cur_thk or abs(cur_thk - thk) <= 0.05:
                # Empty, or already agreeing: submit either way so the model's rank attaches.
                if _apply_field(part, "normalized_thickness_mm", thk, _src):
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
                if _apply_field(part, "normalized_thickness_mm", thk, _src):
                    flags.append(f"thickness {cur_thk:g}mm -> {thk:g}mm from the SolidWorks "
                                 f"cut list (modelled sheet gauge)")
                    out["thickness"] += 1
        elif (not _plausible_thk(nat.thickness_mm)
              and not _num(part.get("normalized_thickness_mm"))):
            # A FLAT BOARD'S GAUGE IS ITS MODEL'S SMALLEST EXTENT — AS A LABELLED FALLBACK
            # (D-512). 12343-01J, an 18 mm MFC shelf: the model carried the box
            # 1198 x 18 x 398, but a board has no sheet-metal cut list and the analyser's
            # gauge window (a sheet-METAL window) ends at 12 mm, so thickness_mm came
            # through None — and with no gauge the shelf had no kg, no sheet price, no
            # weight check, and was charged machining and edging on a board nobody bought.
            #
            # Deliberately NARROW, per the review that demanded it: only a part whose
            # material the Other Sheet block prices (board/plastic, never metal), that is a
            # LEAF (no assembly flags), whose box is plate-shaped (the smallest extent is a
            # board gauge, 3-60 mm, and at most a quarter of the next dimension — a shaped
            # component or a block fails this), and that still has no recorded gauge. The
            # value enters at its own provisional rank, below every stated gauge, with a
            # flag and a question — a drawing callout read later still displaces it.
            _dims = sorted(v for v in (_num(x) for x in (nat.bbox_mm or [])) if v)
            _board_mat = False
            try:
                from costed_facts import is_other_sheet_material as _other_sheet2
                _own = [str(m.get("raw") if isinstance(m, dict) else m)
                        for m in (part.get("materials") or [])]
                _board_mat = (any(_other_sheet2(m) for m in _own)
                              or _other_sheet2(part.get("normalized_material") or "")
                              or _other_sheet2(_norm_sw_material(nat.material or "")))
            except Exception:                                        # noqa: BLE001
                _board_mat = False
            _leaf = not (part.get("is_assembly_parent") or part.get("is_sub_assembly")
                         or part.get("assembly_children"))
            if (_board_mat and _leaf and len(_dims) == 3
                    and 3.0 <= _dims[0] <= 60.0 and _dims[0] * 4 <= _dims[1]):
                thk = float(_dims[0])
                if _apply_field(part, "normalized_thickness_mm", thk,
                                "model_extents_board_gauge"):
                    _why = (f"BOARD GAUGE {thk:g} mm FROM THE MODEL'S SMALLEST EXTENT — a "
                            f"labelled fallback, not a cut list: the solid measures "
                            f"{_bbox_text(nat)} and its material is priced as board, so the "
                            f"thin way through it is read as the gauge. A stated gauge (a "
                            f"drawing callout, a DXF filename) replaces it.")
                    flags.append(_why)
                    part.setdefault("review_flags", []).append(_why)
                    try:
                        from source_precedence import raise_manufacturing_question as _ask_g
                        _ask_g(part, f"Gauge of {part.get('part_number')}: {thk:g} mm from "
                                     f"the model's smallest extent (provisional)",
                               _why, "confirm the board gauge; the sheet price, weight and "
                                     "nest follow it",
                               "solidworks.board_gauge_from_model_extents")
                    except Exception:                                # noqa: BLE001
                        pass
                    out["thickness"] += 1
                # AND THE TWO LARGER EXTENTS ARE ITS BLANK (SCRUM-180). The same shelf
                # that had no gauge had no blank, so geometry_inference's category
                # default sized it: 12678-01-GA's shelves were nested, priced and
                # weighed as the "tier" default 350 x 250 while the model that measures
                # them at 520 x 370 sat in the pack. The verified plate shape above is
                # what justifies it — the board's envelope IS the rectangle it is cut
                # from — and the figures enter at the same provisional rank as the
                # gauge, under the same question; a measured flat, a DXF or a stated
                # size still displaces them. A box-shaped board (the plinth) fails the
                # plate test and is deliberately left to its own construction question.
                if (_board_mat and _leaf and len(_dims) == 3
                        and 3.0 <= _dims[0] <= 60.0 and _dims[0] * 4 <= _dims[1]
                        and not _dxf_backed(part) and not nat.has_flat()
                        and not (_num(part.get("blank_length_mm"))
                                 and _num(part.get("blank_width_mm")))):
                    _bl, _bw = float(_dims[2]), float(_dims[1])
                    if _plausible_mm(_bl) and _plausible_mm(_bw):
                        _wb2 = _apply_field(part, "blank_length_mm", _bl,
                                            "model_extents_board_gauge")
                        _wb2 = _apply_field(part, "blank_width_mm", _bw,
                                            "model_extents_board_gauge") or _wb2
                        if _wb2:
                            _ngb = part.get("normalized_geometry")
                            _ngb = dict(_ngb) if isinstance(_ngb, dict) else {}
                            _ngb["blank_length_mm"], _ngb["blank_width_mm"] = _bl, _bw
                            part["normalized_geometry"] = _ngb
                            flags.append(
                                f"blank {_bl:g} x {_bw:g}mm from the model's extents for "
                                f"the board — provisional with its gauge; a measured flat "
                                f"or a stated size displaces it")
                            out["flat"] += 1

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
            # WHOSE FIGURE THIS IS (D-514). The weight check called this "the sheet's
            # stated weight": on 12343-01J it compared the blank to the MODEL's 5.496 kg
            # and the book presented that as drawing corroboration while the drawing
            # prints 5.573 kg. The figure is kept; its origin travels with it.
            part["stated_weight_source"] = "solidworks_model_mass"
            flags.append(f"mass {nat.mass_kg:.4f}kg from the SolidWorks model")
            out["mass"] += 1

        # ── BENDS ────────────────────────────────────────────────────────────────
        _bends = int(nat.bend_count or 0)
        if _bends > 0:
            # ── CAD EVIDENCE, KEPT APART FROM THE OPERATION COUNT ────────────────────
            #
            # James Gray, 18 Sep 2026, on 401912-02: "SolidWorks is not necessarily 'wrong';
            # its feature tree may correctly contain three CAD bend-related features. The
            # defect is ours: we treated that model feature count as though it were the number
            # of press-brake operations and gave it a higher generic source rank than the
            # flat-pattern/DXF evidence. That is the wrong comparison."
            #
            # This wrote the cut-list count straight into
            # geometry_rollup.estimated_bend_line_count at rank 90 -- over the top of a flat
            # pattern that had MEASURED the bend axes. On that divider the flat said one fold
            # and the model said three, and the sheet charged three: thirty minutes of brake
            # set-up and three times the run time, on a part with one bend in it.
            #
            # 12552, WHICH THIS OVERRIDE WAS BUILT FOR, IS STILL RIGHT. The failure there was
            # a DASHED-LINE SCAN reading 26 and 28 lines against cut lists of 6 and 8. That
            # proxy now sits BELOW the model in `fold_count`, so the model still beats it --
            # what it no longer beats is a measured flat pattern or a stated fold callout,
            # neither of which 12552's parts had.
            #
            # The number is not discarded. It is recorded as what it is, and `fold_count`
            # publishes a disagreement wherever it differs from the charge.
            part["solidworks_bend_features"] = _bends
            flags.append(f"{_bends} bend(s) counted in the SolidWorks feature tree"
                         if not _docmgr else
                         f"{_bends} bend(s) saved in the SolidWorks cut list (Document Manager "
                         f"backup read — the feature tree is not readable without SolidWorks)")
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
                mf["bend_count_source"] = _src
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
                   int(nat.cut_out_count), _src)
            _w1 = _apply(part, "manufacturing_features.pierce_count",
                         _native_pierces, _src)
            _w2 = _apply(part, "geometry_rollup.estimated_pierce_count",
                         _native_pierces, _src)
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
            # The one sentence, from the one vocabulary: costed_facts recognises it and
            # replaces it with what the line's money rests on once a price has arrived.
            try:
                from plain_english import NO_GEOMETRY_SENTENCE as _NO_GEO
            except Exception:                                    # noqa: BLE001
                _NO_GEO = ("SolidWorks gave this part a material but NO usable geometry "
                           "(no flat pattern, mass or section) — material cost cannot be "
                           "derived; treat any £0 on this line as MISSING, not free")
            flags.append(_NO_GEO)
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
        # Material: native wins where the engine has nothing solid — and THROUGH the same
        # normaliser as every other native material, which is where the placeholder is
        # refused. This path read nat.material raw, so a second entrance existed for the
        # exact string the other one rejects.
        _nat_mat = _norm_sw_material(nat.material) if nat else ""
        if _nat_mat and not str(p.get("normalized_material") or "").strip():
            # Same provenance split as the pre-estimate path: an applied-library appearance
            # enters below the drawing callout, a typed spec at full model rank. This path only
            # fills a gap, but the source it records is what a later pass weighs it by.
            if _apply_field(p, "normalized_material", _nat_mat, _material_source_token(nat)):
                p.setdefault("review_flags", []).append(
                    f"Material '{_nat_mat}' from SolidWorks model")
                out["material_set"] += 1
        # Quantity: native BOM roll-up corrects fastener/bought-in counts.
        q = qty_by_pn.get(pn)
        if q is not None and int(q) > 0 and p.get("quantity") != int(q):
            _old = p.get("quantity")
            if _apply_field(p, "quantity", int(q), job_source(job)):
                p.setdefault("review_flags", []).append(
                    f"Quantity {_old} -> {int(q)} from SolidWorks BOM")
                out["qty_corrected"] += 1
        # Weld candidate → flag for the weld/dress route.
        if pn in weld_pns:
            p.setdefault("review_flags", []).append(
                "SolidWorks: welded sub-assembly — confirm weld/dress route")
            out["weld_flagged"] += 1

    return out
