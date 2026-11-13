"""THE FILES ONE RUN WROTE, SAID BY THE RUN ITSELF (reviewer, 12 Nov 2026).

"Use a run-specific output folder and explicit deliverable manifest. Collect the workbook,
record, report, covering note and walkthrough from that run only."

The collector worked out a run's files from what appeared in the output tree and from the
engine's summary JSON, which is written before the note, the walkthrough and the pinned
record exist. Three finished estimates were filed as a workbook and nothing else.

So the last thing a run does is write "<workbook stem>_deliverables.json" beside its
workbook: the portal run, the engine run, the drawing, the build, and every file it wrote
with what each is. The collector takes exactly those. The manifest is named for the run's
own workbook, so it cannot be another run's.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "run_deliverables.v1"
SUFFIX = "_deliverables.json"

_WHAT = (("_record.json", "the run's pinned record"),
         ("_covering_email.html", "the covering note"), ("_covering_email.txt", "the covering note, plain text"),
         ("_walkthrough.wav", "the spoken walkthrough"), ("_walkthrough.txt", "the walkthrough's words"),
         ("_report.html", "the report"), ("_quote", "the quote"), (".xlsx", "the estimate workbook"))


def path_for(xlsx_path: Any) -> Path:
    book = Path(str(xlsx_path))
    return book.with_name(book.stem + SUFFIX)


def _what(name: str) -> str:
    low = name.lower()
    return next((w for tail, w in _WHAT if tail in low), "")


def write(xlsx_path: Any, summary: Optional[Dict[str, Any]] = None,
          started_at: float = 0.0) -> Optional[Path]:
    """Write the manifest beside the workbook. Returns its path, or None when there is no
    workbook. Lists the workbook, what lies beside it that is this run's, and every existing
    file the summary's saved_output_paths names."""
    if not xlsx_path:
        return None
    book = Path(str(xlsx_path))
    if not book.is_file():
        return None
    import own_record as orc                                          # noqa: PLC0415
    summary = summary if isinstance(summary, dict) else {}
    files: Dict[str, Path] = {str(book).lower(): book}
    for p in orc.beside_the_book(book, started_at):
        files.setdefault(str(p).lower(), p)
    for v in (summary.get("saved_output_paths") or {}).values():
        if isinstance(v, str) and v and Path(v).is_file():
            files.setdefault(str(Path(v)).lower(), Path(v))
    prov = summary.get("run_provenance") if isinstance(summary.get("run_provenance"), dict) else {}
    scope = prov.get("submitted_scope") if isinstance(prov.get("submitted_scope"), dict) else {}
    out = path_for(book)
    files.pop(str(out).lower(), None)
    doc = {
        "schema": SCHEMA,
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "workbook": book.name,
        "portal_run_id": str(prov.get("service_run_id") or os.environ.get("SDI_SERVICE_RUN_ID") or ""),
        "engine_run_id": str(prov.get("run_id") or summary.get("run_id") or ""),
        "runner_id": str(prov.get("runner_id") or ""),
        "engine_build": str(prov.get("engine_build") or ""),
        "drawing_number": str(scope.get("drawing_number") or ""),
        "output_folder": str(book.parent),
        "files": [{"name": p.name, "path": str(p), "what": _what(p.name)}
                  for p in sorted(files.values(), key=lambda x: x.name.lower())],
    }
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return out


def read(xlsx_path: Any) -> Dict[str, Any]:
    """The manifest beside a workbook, or {} when there is none or it is another workbook's."""
    try:
        doc = json.loads(path_for(xlsx_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {}
    if str(doc.get("workbook") or "").lower() != Path(str(xlsx_path)).name.lower():
        return {}
    return doc


def listed(xlsx_path: Any) -> List[Path]:
    """Every file the run's manifest lists that is on disk (the manifest itself included)."""
    doc = read(xlsx_path)
    if not doc:
        return []
    out = [Path(str(f.get("path") or "")) for f in doc.get("files") or [] if isinstance(f, dict)]
    return [p for p in out if p.is_file()] + [path_for(xlsx_path)]


def absent(xlsx_path: Any) -> List[str]:
    """Names the manifest lists that are not on disk: a finding for the collector to say."""
    doc = read(xlsx_path)
    return [str(f.get("name")) for f in doc.get("files") or []
            if isinstance(f, dict) and not Path(str(f.get("path") or "")).is_file()]
