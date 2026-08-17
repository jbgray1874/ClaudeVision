"""
enquiry.py — one enquiry folder, one job per sub-folder, before anything is priced.

A PACK ARRIVES AS A FOLDER, NOT A COMMAND LINE. Estimating drops a customer's request into a
folder on the share and expects the engine to know what is in it. Until now the engine was fed
one drawing, or a search root and a glob, and the shape of the enquiry — which drawings are ONE
job and which are ANOTHER — lived only in the operator's head and in whatever they typed. Two
jobs on one enquiry with two different demand quantities is the normal case (45 cabinets and 5
sets of side panels is one enquiry and two shop jobs), and nothing read that structure from the
folder itself.

THE CONVENTION IS THE FOLDER TREE, AND IT IS DELIBERATELY BORING:

    <enquiry>/                 one customer request
        11650-00-GA/           one job — this folder's NAME is the job identity
            ga.pdf
            flats/*.dxf
        11650-04-SA01/         another job, its own demand quantity
            ...

    * Each IMMEDIATE CHILD DIRECTORY of the enquiry is exactly one job.
    * The child folder's name IS the job identity — not a filename inside it, not a title block.
    * A drawing lying LOOSE at the enquiry top has no job, so the enquiry is refused rather than
      guessed: a flat with no folder could belong to either neighbour, and inventing which is
      the kind of silent decision this engine does not make.
    * A job folder with NO readable drawing is refused too — an empty pack priced at nothing
      reads as a free job, and a zero nobody chose is worse than a stop.

EVERYTHING HERE IS GENERAL. It keys on the folder tree and the file extensions the readers
already accept, never on a customer, a job number pattern, or a filename. A new enquiry with new
numbers is read by the same rules with no code change, which is the whole point.

WHAT THIS DOES NOT DO. It does not read a drawing, price a part, or open a file. It answers one
question — "what jobs are in this enquiry, and is each one something the engine can be asked to
cost?" — and hands a manifest to the pricing run. Reading is the next stage's job; this is the
gate that stops a malformed drop before an estimator is handed a confident number built on it.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

try:
    import config
    _CONFIG_EXT = set(getattr(config, "SUPPORTED_EXTENSIONS", None) or {".pdf", ".dxf"})
except Exception:                                                    # noqa: BLE001
    _CONFIG_EXT = {".pdf", ".dxf"}

SCHEMA = "enquiry.v1"

# The drawings a job can be built from. The readers accept PDF and DXF; DWG is converted to DXF
# offline before reading, so a job that arrives as DWG flats is NOT empty. Drawn from config so
# that adding a reader adds a recognised pack type in one place, not two.
DRAWING_EXTENSIONS = set(_CONFIG_EXT) | {".dwg"}

# Below this order quantity the setup a job carries — programming, first-off, fixturing — is
# amortised over so few units that the per-unit figure is mostly setup, and a demand quantity
# typed in haste changes the unit price more than any material choice. It is FLAGGED, never
# refused and never altered: the number is whatever the estimator confirms. One config line
# moves it for every enquiry.
SETUP_HEAVY_BELOW_QTY = 10

# What a job folder is CALLED tells you nothing you can price, but a name that does not look like
# a job at all ("New folder", "scans") is worth a second look before it becomes a line on a
# quote. Matches a job number with optional suffix (11650, 11650-04, 8352_010-GA). A miss is a
# note, never a refusal — the folder is still one job, it is just named unusually.
_JOB_NUMBER = re.compile(r"^\d{3,6}([-_].*)?$")


def _num(v: Any) -> Optional[int]:
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _drawings_under(folder: str) -> List[str]:
    """Every readable drawing inside a job folder, at any depth.

    A job's flats often sit in a sub-folder ("flats/", "DXF/") beside the GA, so the search is
    recursive WITHIN the job — but the job boundary itself is the enquiry's immediate child, set
    by the caller, never crossed here.
    """
    found: List[str] = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if os.path.splitext(name)[1].lower() in DRAWING_EXTENSIONS:
                found.append(os.path.join(root, name))
    return sorted(found)


def job_card(job_dir: str, order_qty: Any = None) -> Dict[str, Any]:
    """One job, described in the terms the pricing run and the estimator both need.

    The identity is the folder name — the one label that survives from the customer's drop to
    the quote. The order quantity is stamped as "priced at N off" so a per-unit figure is never
    read without the divisor it was built on, and a quantity low enough to be setup-dominated is
    flagged for confirmation rather than quietly costed.
    """
    identity = os.path.basename(os.path.normpath(job_dir))
    drawings = _drawings_under(job_dir)
    warnings: List[str] = []

    if not _JOB_NUMBER.match(identity):
        warnings.append(
            f"'{identity}' is not shaped like a job number, so the identity on the quote will "
            f"be the folder name as typed. Rename the folder if this should be a job number.")

    qty = _num(order_qty)
    priced_at = f"priced at {qty} off" if qty else "priced at the quantity the engine infers"
    if qty and qty < SETUP_HEAVY_BELOW_QTY:
        warnings.append(
            f"{qty} off is a short run: setup (programming, first-off, fixturing) is amortised "
            f"over {qty} unit(s), so the per-unit price is setup-dominated and moves sharply "
            f"with the quantity. Confirm the demand quantity before the unit figure is used.")

    return {
        "schema": SCHEMA,
        "identity": identity,
        "path": os.path.abspath(job_dir),
        "drawings": drawings,
        "drawing_count": len(drawings),
        "order_quantity": qty,
        "priced_at": priced_at,
        "setup_heavy": bool(qty and qty < SETUP_HEAVY_BELOW_QTY),
        "empty": not drawings,
        "warnings": warnings,
    }


def read_enquiry(enquiry_root: str,
                 order_qty_by_job: Optional[Dict[str, Any]] = None,
                 default_order_qty: Any = None) -> Dict[str, Any]:
    """Read one enquiry folder into a manifest of jobs, refusing what cannot be priced.

    order_qty_by_job maps a job's folder name to its demand quantity; a job not named there
    falls back to default_order_qty, and a job with neither is costed at the inferred quantity
    with that said on its card. The manifest carries the jobs it CAN hand on and, separately,
    the reasons it will not hand on the rest — because a pack that is silently dropped is the
    same failure as a zero that is silently summed.
    """
    order_qty_by_job = order_qty_by_job or {}
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "enquiry_root": os.path.abspath(enquiry_root),
        "enquiry_name": os.path.basename(os.path.normpath(enquiry_root)),
        "jobs": [],
        "loose_drawings": [],
        "loose_other_files": [],
        "empty_job_folders": [],
        "refusals": [],
        "ok": False,
    }

    if not os.path.isdir(enquiry_root):
        out["refusals"].append(
            f"'{enquiry_root}' is not a folder, so there is no enquiry to read.")
        return out

    entries = sorted(os.listdir(enquiry_root))
    child_dirs = [e for e in entries if os.path.isdir(os.path.join(enquiry_root, e))]
    top_files = [e for e in entries if os.path.isfile(os.path.join(enquiry_root, e))]

    # A DRAWING lying loose at the top has no job to belong to. It is not dropped silently and it
    # is not guessed onto a neighbour — it blocks the enquiry until it is filed under a job.
    for f in top_files:
        if os.path.splitext(f)[1].lower() in DRAWING_EXTENSIONS:
            out["loose_drawings"].append(f)
        else:
            # A covering email or an enquiry spreadsheet legitimately lives at enquiry level.
            # Surfaced so it is not mistaken for a job, but it does not block anything.
            out["loose_other_files"].append(f)

    if out["loose_drawings"]:
        out["refusals"].append(
            "Drawings are loose at the enquiry top with no job folder: "
            + ", ".join(out["loose_drawings"])
            + ". A drawing with no folder could belong to either neighbouring job, so put each "
              "under the job folder it belongs to and the enquiry reads cleanly.")

    if not child_dirs:
        out["refusals"].append(
            "The enquiry has no job sub-folders. Each job is one immediate sub-folder whose name "
            "is the job identity; create one per job and put its drawings inside.")

    for name in child_dirs:
        card = job_card(os.path.join(enquiry_root, name),
                        order_qty_by_job.get(name, default_order_qty))
        if card["empty"]:
            # An empty pack priced at nothing reads as a free job. It is held out of the run with
            # its reason on the record, not costed at zero.
            out["empty_job_folders"].append(name)
            out["refusals"].append(
                f"Job folder '{name}' holds no readable drawing "
                f"({', '.join(sorted(DRAWING_EXTENSIONS))}). An empty pack cannot be priced; add "
                f"its drawings or remove the folder.")
            continue
        out["jobs"].append(card)

    # The enquiry is handable only if at least one job survived AND nothing was refused outright.
    # A partial drop — three good jobs and one loose flat — is still refused, because the loose
    # flat may be the fourth job and pricing three of four silently under-scopes the enquiry.
    out["ok"] = bool(out["jobs"]) and not out["refusals"]
    return out


def run_plan(manifest: Dict[str, Any]) -> List[str]:
    """The jobs an enquiry hands to the batch runner, as run-packs.ps1 arguments.

    Each token is 'PATH:QTY' where the quantity is known and 'PATH' where it is not — the exact
    shape run-packs.ps1 already parses (it splits on the last colon only when digits follow, so
    a Windows drive letter in the path is safe). Nothing is recomputed here: the engine that
    prices a job is the same one run-job.ps1 drives, and this only lists what to run.

    A REFUSED ENQUIRY PRODUCES NO PLAN. A drop with a loose drawing or an empty pack returns an
    empty list, not a partial one — running three of four jobs silently under-scopes the enquiry,
    which is the failure read_enquiry exists to catch. The caller sees the refusals and fixes the
    drop before anything runs.
    """
    if not manifest.get("ok"):
        return []
    plan: List[str] = []
    for job in manifest.get("jobs") or []:
        qty = job.get("order_quantity")
        plan.append(f"{job['path']}:{int(qty)}" if qty else str(job["path"]))
    return plan


def one_line(manifest: Dict[str, Any]) -> str:
    """What an operator reads the moment the folder is pointed at, before any drawing is opened."""
    jobs = manifest.get("jobs") or []
    if manifest.get("ok"):
        setup_heavy = [j["identity"] for j in jobs if j.get("setup_heavy")]
        tail = (" — short runs to confirm: " + ", ".join(setup_heavy)) if setup_heavy else ""
        return (f"{manifest.get('enquiry_name')}: {len(jobs)} job(s) ready to price"
                + tail)
    refusals = manifest.get("refusals") or []
    head = f"{manifest.get('enquiry_name')}: not ready — {len(refusals)} thing(s) to fix"
    return head + (" — " + refusals[0] if refusals else "")
