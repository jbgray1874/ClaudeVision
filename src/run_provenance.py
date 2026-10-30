"""Which run, which machine, which build, which mode: on the book, not only in the log (D-601).

THE ALTAVIO HPP RUNS OF 30 OCT 2026. Four books came back in one afternoon and every one of
them started the same argument. Was the fix in? Which machine claimed the job? Was it the
LLM-only button or the main one? Were the reads fresh or replayed? The answers were all
known to the run and printed in its log, and none of them was on the book. The log is the
one thing nobody forwards. So each question went back to the laptop as a request for log
lines, and the book itself could not settle any of them.

So the run records its own identity when it starts, and the internal book prints it on its
first page:

    Run ID · runner machine · engine build · normal or LLM-only · reference documents ·
    fresh or cached reads · final review status

THE BUILD IS THE ONE THE BOOK ALREADY CARRIES. AI Provenance's header has stated
`build_stamp_line()` since 7332-01. This module records that same line on the run, so the
report and the tab quote one stamp from one function. It never computes a second one.

THE MACHINE IS THE ENGINE'S OWN. The runner starts the engine on the machine it runs on, so
the engine's host name is the runner's host name. The runner adds what only it knows: its
runner id and the portal's run id, passed in the environment. A run started by hand records
that it was not started by a runner, which is itself an answer.

RECORDED AT RUN TIME, READ AT RENDER TIME. A report re-rendered tomorrow on another machine
must show the machine that RAN the job, not the one rendering it. So the record is stamped
onto the summary when the run starts, and a summary written before this record existed says
"not recorded", never a guess from the process reading it.

INTERNAL ONLY. None of this goes on the customer quotation. Machine names, build hashes and
cache counts are SDI's working detail.
"""
from __future__ import annotations

import os
import platform
import re
from typing import Any, Dict, List, Optional, Tuple

# Set by the portal runner on the engine process it starts (tools/runner/sdi_estimate_runner.py).
RUNNER_ID_ENV = "SDI_CLAIMED_BY_RUNNER"
# Not SDI_RUNNER_ID: that is the runner's own setting, and a shell that has it set would make
# a run started by hand claim a runner it never had.
SERVICE_RUN_ID_ENV = "SDI_SERVICE_RUN_ID"

NOT_RECORDED = "not recorded on this run (it predates D-601)"


def _machine() -> str:
    return (platform.node() or os.environ.get("COMPUTERNAME") or "").strip()


def _build_line() -> Tuple[str, str]:
    """(the book's build stamp, any warning about it) — the same two facts AI Provenance prints."""
    try:
        from build_stamp import (behind_origin_warning, build_stamp_line,
                                 stale_process_warning)
    except Exception:                                                # noqa: BLE001
        return "", ""
    try:
        line = build_stamp_line()
    except Exception:                                                # noqa: BLE001
        line = ""
    try:
        warn = stale_process_warning() or behind_origin_warning() or ""
    except Exception:                                                # noqa: BLE001
        warn = ""
    return line, warn


def record(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp this run's identity onto `summary["run_provenance"]` and return it.

    Called once, at the start of the run, by the process that does the costing. Never raises:
    a run that cannot name its machine still has to produce an estimate."""
    runner_id = (os.environ.get(RUNNER_ID_ENV) or "").strip()
    build, warn = _build_line()
    prov: Dict[str, Any] = {
        "machine": _machine(),
        "runner_id": runner_id,
        # The runner is this process's parent, so its pid names WHICH runner process claimed
        # the job — the question two runners on one machine left open for three days.
        "runner_pid": os.getppid() if runner_id else None,
        "service_run_id": (os.environ.get(SERVICE_RUN_ID_ENV) or "").strip(),
        "engine_build": build,
        "build_warning": warn,
    }
    if isinstance(summary, dict):
        summary["run_provenance"] = prov
    return prov


def _prov(summary: Any) -> Dict[str, Any]:
    p = (summary or {}).get("run_provenance") if isinstance(summary, dict) else None
    return p if isinstance(p, dict) else {}


def run_text(summary: Any) -> str:
    rid = str((summary or {}).get("run_id") or "").strip() if isinstance(summary, dict) else ""
    # The saved file carries it inside the record, where the quote does not look.
    rid = rid or str(_prov(summary).get("run_id") or "").strip()
    svc = str(_prov(summary).get("service_run_id") or "").strip()
    if rid and svc:
        return f"{rid} · portal run {svc}"
    return rid or (f"portal run {svc}" if svc else "not recorded")


def machine_text(summary: Any) -> str:
    p = _prov(summary)
    if not p:
        return NOT_RECORDED
    machine = str(p.get("machine") or "").strip() or "unknown machine"
    if p.get("runner_id"):
        pid = p.get("runner_pid")
        return f"{machine} · runner {p['runner_id']}" + (f" (pid {pid})" if pid else "")
    return f"{machine} · started by hand, not by a portal runner"


def build_text(summary: Any) -> str:
    p = _prov(summary)
    if not p:
        return NOT_RECORDED
    line = str(p.get("engine_build") or "").strip() or "the build could not be identified"
    warn = str(p.get("build_warning") or "").strip()
    return f"{line} · ⚠ {warn}" if warn else line


def mode_text(summary: Any) -> str:
    try:
        from run_readers import run_was_llm_only
        llm_only = run_was_llm_only(summary if isinstance(summary, dict) else None)
    except Exception:                                                # noqa: BLE001
        llm_only = bool(isinstance(summary, dict) and summary.get("llm_only"))
    if llm_only:
        return ("LLM-only — the measurement run: the bill of materials came from the vision "
                "model alone; the BOM reader, DXF flat patterns and SolidWorks extract were off")
    return "Normal — every reader on"


def _file_name(path: Any) -> str:
    """The name alone, whichever machine wrote the path: a run on the laptop records
    C:\\ paths, and a report rendered elsewhere must still drop the folders."""
    return re.split(r"[\\/]", str(path or "").strip())[-1]


def references_text(summary: Any) -> str:
    s = summary if isinstance(summary, dict) else {}
    names = [_file_name(p) for p in (s.get("reference_pack_paths") or [])
             if str(p or "").strip()]
    refs = (", ".join(names) + " (held out of the product read)") if names else "none declared"
    brief = s.get("enquiry_brief") if isinstance(s.get("enquiry_brief"), dict) else {}
    if brief.get("text"):
        b = (f"enquiry brief filed ({len(str(brief['text']))} characters, "
             f"{_file_name(brief.get('file') or 'ENQUIRY_BRIEF.txt')})")
    else:
        b = "no enquiry brief"
    return f"{refs} · {b}"


def reads_line(summary: Any) -> str:
    """"Reads: pdf_readings 3 reused / 0 made; vision_bom 11 reused / 2 made" — what each store
    gave back on the run that costed this book (D-553/D-554), from the estimate's own record,
    else from this process; "" when nothing was read through a store. A cache that never hits
    looks exactly like one that works, and the book is where somebody looks."""
    counts = ((summary or {}).get("estimate_summary") or {}).get("reads_reused") \
        if isinstance(summary, dict) else None
    if not isinstance(counts, dict) or not counts:
        try:
            import run_timing
            counts = run_timing.reuse_counts()
        except Exception:                                    # noqa: BLE001
            counts = {}
    parts = [f"{store} {int(c.get('reused', 0))} reused / {int(c.get('computed', 0))} made"
             for store, c in sorted((counts or {}).items()) if isinstance(c, dict)]
    return ("Reads: " + "; ".join(parts)) if parts else ""


def reads_text(summary: Any) -> str:
    fresh = bool(isinstance(summary, dict) and summary.get("fresh_read"))
    head = ("Fresh — the model was asked again; both LLM caches were bypassed" if fresh
            else "Cached reads allowed — a held answer for the same pages is replayed")
    counts = reads_line(summary)
    return f"{head} · {counts}" if counts else head


def facts(summary: Any, review_status: Optional[str] = None) -> List[Tuple[str, str]]:
    """The panel's rows, in the order the reviewer named them. `review_status` is the report's
    own release line, passed in so the panel and the Summary cannot disagree; the workbook
    has no final status when it is written, so it passes none."""
    rows = [("Run ID", run_text(summary)),
            ("Runner machine", machine_text(summary)),
            ("Engine build", build_text(summary)),
            ("Mode", mode_text(summary)),
            ("Reference documents", references_text(summary)),
            ("Reads", reads_text(summary))]
    if review_status:
        rows.append(("Final review status", review_status))
    return rows


def workbook_line(summary: Any) -> str:
    """The run's identity as one line for AI Provenance's header, beside the build it already
    states. Machine, mode and references only: the build and the reads have their own places
    in that header, and the review status there would be the provisional count."""
    return (f"Run: {run_text(summary)}   |   Machine: {machine_text(summary)}   |   "
            f"Mode: {mode_text(summary).split(' — ')[0]}   |   "
            f"References: {references_text(summary)}")
