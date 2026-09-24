"""Pull every record that mentions the given terms out of a run's JSON, small enough to send.

A run's JSON is ~47 MB and one line, so neither Select-String nor an upload gets the part of it
that answers a question. This walks it and writes each dict that mentions a term — with the
path it sits at — to a text file beside the JSON, long values shortened.

    python tools\\diag\\extract_job_facts.py output\\json\\11650-06-GA.json MIRROR FIXING YIREE DWG888000

Writes output\\json\\11650-06-GA_json_extract.txt (or --out). Terms match case-insensitively.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List, Tuple

_MAX_VALUE = 400
_MAX_HITS = 4000


def _short(v: Any) -> Any:
    if isinstance(v, str):
        return v if len(v) <= _MAX_VALUE else v[:_MAX_VALUE] + f"…(+{len(v) - _MAX_VALUE})"
    if isinstance(v, (list, tuple)):
        if all(not isinstance(x, (dict, list)) for x in v):
            out = [_short(x) for x in v[:20]]
            return out + ([f"…(+{len(v) - 20} more)"] if len(v) > 20 else [])
        return f"[list of {len(v)}]"
    if isinstance(v, dict):
        return f"{{dict of {len(v)} keys}}"
    return v


def _flat(d: dict) -> dict:
    return {k: _short(v) for k, v in d.items()}


def _mentions(d: dict, terms: List[str]) -> bool:
    for v in d.values():
        if isinstance(v, (str, int, float)) and any(t in str(v).upper() for t in terms):
            return True
        if isinstance(v, list) and any(isinstance(x, str) and any(t in x.upper() for t in terms)
                                       for x in v):
            return True
    return False


def walk(obj: Any, terms: List[str], path: str, hits: List[Tuple[str, dict]]) -> None:
    if len(hits) >= _MAX_HITS:
        return
    if isinstance(obj, dict):
        if _mentions(obj, terms):
            hits.append((path, _flat(obj)))
        for k, v in obj.items():
            walk(v, terms, f"{path}.{k}", hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, terms, f"{path}[{i}]", hits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json_path")
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    src = Path(a.json_path)
    data = json.loads(src.read_text(encoding="utf-8", errors="replace"))
    terms = [t.upper() for t in a.terms]
    hits: List[Tuple[str, dict]] = []
    walk(data, terms, "$", hits)
    out = Path(a.out) if a.out else src.with_name(src.stem + "_json_extract.txt")
    with out.open("w", encoding="utf-8") as f:
        f.write(f"{src.name} — {len(hits)} record(s) mentioning {', '.join(terms)}"
                + (" (capped)" if len(hits) >= _MAX_HITS else "") + "\n\n")
        for p, d in hits:
            f.write(p + "\n" + json.dumps(d, ensure_ascii=False, default=str) + "\n\n")
    print(f"{len(hits)} record(s) -> {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
