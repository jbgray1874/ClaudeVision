"""What the estimator recorded: the commercial inputs are done, and this price may go out.

James Gray, 18 September 2026:

    "The portal must write the commercial-input completion and named release authorisation.
     Until then every quote correctly stays portal-only."

D-145 built the gate and nothing could open it. `commercial_inputs.complete` and
`quote_release.authorised_by` were read from the summary, and nothing anywhere wrote either,
so every run produced a portal copy — correct, and permanently correct, which is a gate with
no key.

WHERE IT LIVES, AND WHY NOT IN THE SUMMARY. The summary JSON is a RUN ARTEFACT: the engine
rewrites it whole on every run, so an authorisation written into it is destroyed by the next
estimate of the same job. This is the opposite kind of fact — a person's decision, made once,
outliving the run it was made about. It sits beside the deliverables in its own record, which
the engine merges in when it builds the quote.

    <output folder>/<stem>_release.json

That is not "a json file lying around being copied manually around": nobody edits it, nothing
copies it, the portal writes it through one endpoint and the engine reads it through this
module. The rate cards and the settings this codebase moved INTO config are the other thing
entirely — configuration, shared between jobs. This is one job's record of one decision.

── AND AN AUTHORISATION IS BOUND TO WHAT IT AUTHORISED ─────────────────────────────────────

THE HAZARD THAT MAKES THE SIMPLE VERSION WRONG. Dave authorises 401912-02 at £149.87. A
drawing is revised, the job is re-estimated, the unit cost comes back £212.40 — and a record
that says only "Dave authorised this job" releases the new figure on the old signature. Nobody
did anything careless and a price goes out that nobody approved.

So the record carries the figure and the cell it was signed against, and `quote_state` accepts
it only while the estimate still says the same thing. This is the same discipline as
`publishable_total`'s cell check and for the same reason: two records paired by nothing are
not evidence that they agree.

Re-running a job therefore RETURNS it to the portal when the price moves, and leaves it
released when the price is unchanged — which is what an estimator would expect of their own
signature, and is the only reading under which the signature means anything.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

SCHEMA = "quote_release_record.v1"

# The tolerance a price may move within before an authorisation stops covering it is half a
# penny, and it is applied in `quote_state.authorisation` beside the same figure it compares —
# the same tolerance `publishable_total` uses against the workbook cell. It is NOT restated
# here: a number in two files is how the two drift, and this one is not a rate.


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _safe_stem(stem: Any) -> str:
    return re.sub(r"[^\w\- ]", "", _clean(stem)).strip() or "job"


def record_path(out_dir: Any, stem: Any) -> Path:
    """Beside the deliverables, named for the job, so a folder holds one job's decision."""
    return Path(str(out_dir)) / f"{_safe_stem(stem)}_release.json"


def read_release_record(out_dir: Any, stem: Any) -> Dict[str, Any]:
    """The record, or {} — an unreadable or absent one is no authorisation, never an error.

    FAIL CLOSED AND FAIL QUIET. A corrupt record must not take a run down: the estimate is
    still wanted, it simply comes out as the portal copy, which is where it would have been
    without the file at all.
    """
    path = record_path(out_dir, stem)
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_release_record(out_dir: Any, stem: Any, *, authorised_by: Any,
                         unit_gbp: Any, unit_cell: Any = "",
                         commercial_inputs: Any = None,
                         at: Any = None) -> Dict[str, Any]:
    """Record that a named person completed the inputs and released THIS figure.

    Raises ValueError when the name or the figure is missing, because an authorisation with
    nobody's name on it is not one, and one with no figure attached is the stale-signature
    hazard this record exists to close.
    """
    who = _clean(authorised_by)
    if not who:
        raise ValueError("an authorisation needs the name of the person making it")
    figure = _num(unit_gbp)
    if figure is None:
        raise ValueError("an authorisation must name the unit figure it authorises")
    when = _clean(at) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    inputs = commercial_inputs if isinstance(commercial_inputs, Mapping) else {}
    record = {
        "schema": SCHEMA,
        "job_output_stem": _clean(stem),
        "commercial_inputs": {"complete": True, "items": dict(inputs)},
        "quote_release": {
            "authorised_by": who,
            "authorised_at": when,
            # WHAT WAS SIGNED. Read back by `quote_state`, which refuses the authorisation
            # when the estimate no longer says this.
            "authorised_unit_gbp": figure,
            "authorised_unit_cell": _clean(unit_cell),
        },
    }
    path = record_path(out_dir, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole and replaced. A half-written record would be read as a shorter one rather
    # than as a broken file, and a shorter one here means a different authorisation.
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def clear_release_record(out_dir: Any, stem: Any) -> bool:
    """Withdraw an authorisation. Returns whether there was one to withdraw."""
    path = record_path(out_dir, stem)
    try:
        path.unlink()
        return True
    except OSError:
        return False


def apply_to_summary(summary: Dict[str, Any], out_dir: Any = None,
                     stem: Any = None) -> Dict[str, Any]:
    """Merge the job's release record into the summary the renderers read.

    Called by whatever is about to build a quote. The summary is not the record's home — it is
    where every consumer already looks — so this is the one place the two meet, rather than
    each renderer learning to find a sidecar.

    A record NEVER overwrites a decision already on the summary: an estimator working in the
    current run wins over a file from an earlier one.
    """
    if not isinstance(summary, dict):
        return summary
    stem = stem or summary.get("job_output_stem")
    if out_dir is None or not stem:
        return summary
    record = read_release_record(out_dir, stem)
    if not record:
        return summary
    for key in ("commercial_inputs", "quote_release"):
        if not summary.get(key) and isinstance(record.get(key), Mapping):
            summary[key] = dict(record[key])
    return summary
