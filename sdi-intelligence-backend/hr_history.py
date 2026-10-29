"""
Run history for the BrightHR -> InVentry sync: who ran what, when, and what changed.

One JSON line per run in HR_SNAPSHOT_DIR/hr_history.jsonl, written by the push
(every dry run and update, whoever started it) and by the app's checks. The app
shows the latest. The pipeline log has the detail; this is the summary a person
reads to answer "who signed Sam out, and when?".

Never raises: losing a history line must not fail the run it describes.
"""
import json
import os
from pathlib import Path

import hr_config as cfg

MAX_BYTES = 5 * 1024 * 1024     # past this, keep the newest KEEP_LINES
KEEP_LINES = 2000


def _path() -> Path:
    return Path(cfg.HR_SNAPSHOT_DIR) / "hr_history.jsonl"


def record(entry: dict) -> None:
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        if p.stat().st_size > MAX_BYTES:
            lines = p.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
            tmp = p.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, p)
    except OSError:
        pass


def recent(n: int = 20) -> list:
    """The newest n entries, newest first. Unreadable lines are skipped."""
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= n:
            break
    return out


def from_push(summary: dict, by: str) -> dict:
    """The history line for one push: counts, and the names that changed."""
    return {
        "time": summary.get("timestamp"),
        "kind": "dry run" if summary.get("dry_run") else "update",
        "by": by,
        "status": summary.get("status"),
        "brighthr_on_site": summary.get("brighthr_on_site"),
        "inventry_on_site_before": summary.get("inventry_on_site_before"),
        "inventry_on_site_after": len(summary.get("on_site_after") or []) or None,
        "signed_in": summary.get("signed_in_names") or [],
        "signed_out": summary.get("signed_out_names") or [],
        "held_back": len(summary.get("sign_outs_held_back") or []),
        "unmatched": len(summary.get("unmatched") or []),
        "failures": len(summary.get("failures") or []),
        "note": (summary.get("warnings") or [None])[0] if summary.get("status") != "ok" else None,
    }
