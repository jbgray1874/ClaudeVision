"""Compile and save a canonical route shadow from an existing job JSON.

Usage:
    python tools/route_shadow_compare.py JOB.json --out route_shadow.json

This is read-only with respect to the job. The output is an audit artefact for comparing
legacy part costs with the proposed job-level decisions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import compile_job_route, project_priced_route  # noqa: E402


def build_shadow(job: dict) -> dict:
    parts = job.get("parts")
    if not isinstance(parts, list):
        parts = ((job.get("manufacturing_writeup") or {}).get("parts") or [])
    extract = job.get("llm_full_extract") or {}
    estimates = ((job.get("estimate_summary") or {}).get("part_estimates") or [])
    route_graph = compile_job_route(parts, extract)
    return project_priced_route(route_graph, estimates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_json", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with args.job_json.open("r", encoding="utf-8") as handle:
        job = json.load(handle)
    shadow = build_shadow(job)
    shadow["source_job_json"] = str(args.job_json.resolve())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(f".{args.out.name}.tmp")
    temporary.write_text(
        json.dumps(shadow, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(args.out)

    codes = {}
    for issue in shadow.get("issues") or []:
        code = str(issue.get("code") or "unknown")
        codes[code] = codes.get(code, 0) + 1
    print(json.dumps({
        "output": str(args.out.resolve()),
        "counts": shadow.get("counts") or {},
        "issue_codes": codes,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
