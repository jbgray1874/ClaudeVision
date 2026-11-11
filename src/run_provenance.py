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
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Set by the portal runner on the engine process it starts (tools/runner/sdi_estimate_runner.py).
RUNNER_ID_ENV = "SDI_CLAIMED_BY_RUNNER"
# The scope the portal submitted, handed down by the runner as JSON (D-604).
SUBMITTED_SCOPE_ENV = "SDI_SUBMITTED_SCOPE"
# Not SDI_RUNNER_ID: that is the runner's own setting, and a shell that has it set would make
# a run started by hand claim a runner it never had.
SERVICE_RUN_ID_ENV = "SDI_SERVICE_RUN_ID"
# Which portal service the runner claimed the job from, and the commit it reported (D-607).
# Not SDI_SERVICE_URL: that is the runner's own setting for where to poll.
CLAIMED_FROM_ENV = "SDI_CLAIMED_FROM"

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


def brief_fingerprint(text: Any) -> str:
    """The brief's content as a short hash, whitespace collapsed (D-604a). The service computes
    the same, so the book compares what was sent with what arrived, not just whether a brief
    exists. Kept identical to estimate_routes.brief_fingerprint; a test holds them together."""
    import hashlib
    norm = " ".join(str(text or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16] if norm else ""


def _json_env(name: str) -> Dict[str, Any]:
    try:
        import json
        got = json.loads(os.environ.get(name) or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _submitted() -> Dict[str, Any]:
    return _json_env(SUBMITTED_SCOPE_ENV)


def _claimed_from() -> Dict[str, str]:
    got = _json_env(CLAIMED_FROM_ENV)
    return {"service": str(got.get("service") or "").strip(),
            "commit": str(got.get("commit") or "").strip()} if got else {}


def _submission_gap(service_run_id: str) -> str:
    """Which link sent no scope, when none arrived (D-607). The HPP 03:18 book said only "no
    submission recorded", and a service on old code, a runner on old code and a route that
    records none all read the same. Each leaves a different trace in the environment, so the
    book names the one it sees. These are what the current code does, not guesses: the
    runner always passes the variable, and the service always puts the field in the claim."""
    if not service_run_id:
        return "started by hand, so nothing was submitted"
    raw = os.environ.get(SUBMITTED_SCOPE_ENV)
    if raw is None:
        return ("the runner passed none: a runner process started before D-604 passes none, "
                "so restart the runner")
    if raw.strip() in ("", "null"):
        return ("the portal service sent no scope with the job: a service started before "
                "D-604 sends none, so check the service's commit")
    if raw.strip() == "{}":
        # A runner started before D-607 passes {} for no scope as well as for an empty one.
        return ("the portal service sent no scope or an empty one: a service started before "
                "D-604 sends none, and before D-607 a batch run or a run claimed before its "
                "scope was recorded had an empty one, so check the service's commit")
    return "the scope the runner passed could not be read"


def _received(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """What reached the engine's job folder: the brief file and the reference declaration.
    Read from the folder itself, because a measured pack never uses the brief and so never
    records it — and the question here is whether it ARRIVED, not whether it was used."""
    folders = [summary.get("job_folder")] if isinstance(summary, Mapping) else []
    brief_chars, brief_sha, refs = 0, "", []
    try:
        import concept_scan
        text, _f = concept_scan.find_brief(folders)
        brief_chars = len(str(text or "").strip())
        brief_sha = brief_fingerprint(text)
        refs = list(concept_scan.reference_documents_declared(folders))
    except Exception:                                                # noqa: BLE001
        pass
    return {"brief_chars": brief_chars, "brief_sha256": brief_sha, "reference_documents": refs}


def record(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp this run's identity onto `summary["run_provenance"]` and return it.

    Called once, at the start of the run, by the process that does the costing. Never raises:
    a run that cannot name its machine still has to produce an estimate."""
    runner_id = (os.environ.get(RUNNER_ID_ENV) or "").strip()
    service_run_id = (os.environ.get(SERVICE_RUN_ID_ENV) or "").strip()
    submitted = _submitted()
    build, warn = _build_line()
    prov: Dict[str, Any] = {
        "machine": _machine(),
        "runner_id": runner_id,
        # The runner is this process's parent, so its pid names WHICH runner process claimed
        # the job — the question two runners on one machine left open for three days.
        "runner_pid": os.getppid() if runner_id else None,
        "service_run_id": service_run_id,
        "claimed_from": _claimed_from(),
        "engine_build": build,
        "build_warning": warn,
        "submitted_scope": submitted,
        "submission_gap": "" if submitted else _submission_gap(service_run_id),
        "received_scope": _received(summary) if isinstance(summary, dict) else {},
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
    line = f"{line} · ⚠ {warn}" if warn else line
    service = service_text(summary)
    return f"{line} · {service}" if service else line


def _same_commit(a: str, b: str) -> Optional[bool]:
    """Two short or long hashes of one commit agree on their common prefix. None when either
    side is unknown, which is not a match and not a mismatch."""
    a, b = a.strip().lower(), b.strip().lower()
    n = min(len(a), len(b))
    # Fewer than seven characters is not enough to call two commits one (D-607a).
    if "unknown" in (a, b) or a == "no" or n < 7:
        return None
    return a[:n] == b[:n]


def service_text(summary: Any) -> str:
    """The portal service the job was claimed from and the commit it reported (D-607), with a
    warning when that is not the engine's own commit. The service and the engine run from one
    checkout, so two commits mean one of the two processes is not on the code on disk; the
    HPP 03:18 run was claimed from a service on 8071 that a restart of 8072 had not touched."""
    p = _prov(summary)
    claimed = p.get("claimed_from") if isinstance(p.get("claimed_from"), dict) else {}
    if not claimed:
        return ""
    where = claimed.get("service") or "an unnamed service"
    commit = claimed.get("commit") or ""
    if not commit:
        return f"portal service {where}, which reported no commit · ⚠ its build is not verified"
    engine = str(p.get("engine_build") or "").split(" ")[0]
    same = _same_commit(engine, commit)
    text = f"portal service {where} on {commit}"
    if same is False:
        text += f" · ⚠ NOT the engine's commit {engine}: restart that service before trusting the run"
    elif same is None:
        # AN UNAVAILABLE COMMIT IS UNVERIFIED, NEVER A MATCH (D-607a).
        text += " · ⚠ not verified against the engine's commit"
    return text


# The prefix that marks a check which could not run, not a difference it found (D-604b).
UNVERIFIED = "could not verify: "


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def scope_mismatches(summary: Any) -> List[str]:
    """Each way the scope that reached the engine differs from the scope submitted (D-604).

    Empty when they agree, and empty when nothing was submitted (a run started by hand, or a
    service older than this record): there is nothing to compare against, and the Scope row
    says so instead."""
    s = summary if isinstance(summary, dict) else {}
    p = _prov(s)
    sub = p.get("submitted_scope") if isinstance(p.get("submitted_scope"), dict) else {}
    if not sub:
        return []
    rec = p.get("received_scope") if isinstance(p.get("received_scope"), dict) else {}
    out: List[str] = []
    # NOTHING RECORDED OF WHAT ARRIVED IS NOT AGREEMENT (D-604b): the brief and the references
    # cannot be checked, so the check failed; it did not pass.
    if not isinstance(p.get("received_scope"), dict):
        out.append(UNVERIFIED + "nothing was recorded of what reached the job folder, so the "
                   "brief and the reference documents were not checked")
    # A MISSING EXPECTED FIELD IS A MISMATCH (D-604a): a customer, drawing or quantity that was
    # submitted and is absent on the record did not arrive, which is not "as submitted".
    got_cust = s.get("customer") or p.get("received_customer")
    if sub.get("client"):
        if not got_cust:
            out.append(f"customer submitted as {sub['client']}, none received")
        elif _norm(sub["client"]) != _norm(got_cust):
            out.append(f"customer submitted as {sub['client']}, received as {got_cust}")
    got_dwg = s.get("declared_product")
    if sub.get("drawing_number"):
        if not got_dwg:
            out.append(f"drawing submitted as {sub['drawing_number']}, none received")
        elif _norm(sub["drawing_number"]) != _norm(got_dwg):
            out.append(f"drawing submitted as {sub['drawing_number']}, received as {got_dwg}")
    got_qty = s.get("requested_order_quantity")
    if sub.get("units"):
        try:
            if not got_qty:
                out.append(f"quantity submitted as {sub['units']}, none received")
            elif int(sub["units"]) != int(got_qty):
                out.append(f"quantity submitted as {sub['units']}, received as {got_qty}")
        except (TypeError, ValueError):
            out.append(f"quantity submitted as {sub['units']}, received as {got_qty}")
    # THE BRIEF'S CONTENT, NOT ITS PRESENCE (D-604a): 200 characters sent and one received
    # read "as submitted". Compared by fingerprint where the service sent one, else by length.
    sent_b, got_b = int(sub.get("brief_chars") or 0), int(rec.get("brief_chars") or 0)
    sent_h, got_h = str(sub.get("brief_sha256") or ""), str(rec.get("brief_sha256") or "")
    if sent_b and not got_b:
        out.append(f"a brief of {sent_b} characters was submitted and none reached the job folder")
    elif got_b and not sent_b:
        out.append(f"no brief was submitted, yet one of {got_b} characters is in the job folder")
    elif sent_b and sent_h and not got_h and isinstance(p.get("received_scope"), dict):
        # A FINGERPRINT SENT AND NONE TO COMPARE IT WITH (D-604b): the reviewer reproduced
        # "as submitted" here. Verification failed; it is not agreement.
        out.append(UNVERIFIED + f"a brief of {sent_b} characters was submitted with its "
                   f"fingerprint, and the brief received has none to compare it with")
    elif sent_b and ((sent_h and got_h and sent_h != got_h) or (not sent_h and sent_b != got_b)):
        out.append(f"the brief in the job folder is not the brief submitted ({sent_b} "
                   f"characters submitted, {got_b} received)")
    # THE EXACT REFERENCE LIST (D-604a): every declared name, each one, on both sides.
    sent_r = sorted(_file_name(n) for n in (sub.get("reference_documents") or []))
    got_r = sorted(_file_name(n) for n in (rec.get("reference_documents") or []))
    if sent_r != got_r:
        missing = sorted(set(sent_r) - set(got_r))
        extra = sorted(set(got_r) - set(sent_r))
        if missing:
            out.append("declared reference not received: " + ", ".join(missing))
        if extra:
            out.append("reference declared in the folder but not submitted: " + ", ".join(extra))
        if not missing and not extra:
            out.append(f"reference list differs: submitted {sent_r}, received {got_r}")
    return out


def scope_text(summary: Any) -> str:
    """The scope this book priced, and whether it is the scope that was submitted."""
    s = summary if isinstance(summary, dict) else {}
    qty = s.get("requested_order_quantity") or s.get("assumed_job_quantity")
    cust = s.get("customer") or _prov(s).get("received_customer")
    got = (f"customer {cust or '—'} · drawing {s.get('declared_product') or '—'}"
           f" · {qty or '—'} off")
    p = _prov(s)
    if not p:
        return got
    if not p.get("submitted_scope"):
        gap = str(p.get("submission_gap") or "")
        # A PORTAL RUN THAT RECEIVED NO SCOPE COULD NOT BE CHECKED (D-607), and a check that
        # could not run is not agreement (D-604b). A run started by hand had nothing to check.
        if gap and p.get("service_run_id"):
            return got + " · ⚠ NOT VERIFIED: no submitted scope reached the engine; " + gap
        return got + " · no submission recorded to compare with" + (f": {gap}" if gap else "")
    bad = scope_mismatches(s)
    if not bad:
        return got + " · as submitted"
    # A CHECK THAT COULD NOT RUN IS SAID AS ONE (D-604b), apart from a difference it found.
    differ = [b for b in bad if not b.startswith(UNVERIFIED)]
    unver = [b[len(UNVERIFIED):] for b in bad if b.startswith(UNVERIFIED)]
    return (got + (" · ⚠ NOT AS SUBMITTED: " + "; ".join(differ) if differ else "")
            + (" · ⚠ NOT VERIFIED: " + "; ".join(unver) if unver else ""))


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
            ("Scope", scope_text(summary)),
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
    service = service_text(summary)
    return (f"Run: {run_text(summary)}   |   Scope: {scope_text(summary)}   |   "
            f"Machine: {machine_text(summary)}   |   "
            + (f"Service: {service}   |   " if service else "")
            + f"Mode: {mode_text(summary).split(' — ')[0]}   |   "
            f"References: {references_text(summary)}")
