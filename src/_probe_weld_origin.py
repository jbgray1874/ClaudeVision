#!/usr/bin/env python3
r"""
_probe_weld_origin.py  —  READ-ONLY. Writes nothing.

We have PROVEN (DXF probe) that 1300-01 is a single flat blank with NO weld, and
we know WHERE the weld cost is computed (estimator.py:2156, gated on
`"welding" in ops`). The one remaining unknown is WHY `"welding"` is in the op
list. This probe answers that, definitively, from the summary JSON:

  1. dumps the part's operation / weld / risk-flag / manufacturing-feature fields
  2. shows any weld run/setup time already attached
  3. scans every text field the part carries for the SAME triggers the engine uses
       - re.search(r"\bWELD(?:ED|ING)?\b")           (extractor_patterns weld regex)
       - "WELD" / "MIG" / "TIG" substring membership  (extractor_patterns weld_keywords)
     and prints the exact matching substring + context, so we SEE the trigger.
  4. scans the whole document (incl. the garbled page-2 DXF-dump text) for the same.

If a WELD/MIG/TIG hit is found, that is the entry point -> suppress at that path.
If NOTHING is found, `"welding"` is NOT text-derived (default / historical /
inheritance) -> we suppress at the op-list source instead. Either way we learn
the exact trigger before writing a line.

Self-discovering: it finds the 1300-01 record wherever it lives, so it won't fail
on a wrong JSON path.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_weld_origin.py ^
      "C:\ClaudeVision\output\json\1300-01FlatShelf.json"
"""
import sys, json, re

WELD_RE = re.compile(r"\bWELD(?:ED|ING)?\b", re.IGNORECASE)
WELD_KEYWORDS = ("WELD", "MIG", "TIG")
TARGET = "1300-01"


def find_part_records(obj):
    """Return [(path, dict)] for every dict that looks like a part record."""
    out = []

    def walk(o, p):
        if isinstance(o, dict):
            k = set(o.keys())
            if ("part_number" in k or "part_no" in k) or ("operations" in k and "material" in k) \
               or ("textual_operations" in k):
                out.append((p, o))
            for kk, vv in o.items():
                walk(vv, f"{p}.{kk}")
        elif isinstance(o, list):
            for i, vv in enumerate(o):
                walk(vv, f"{p}[{i}]")
    walk(obj, "root")
    return out


def text_hits(text):
    hits = []
    for m in WELD_RE.finditer(text):
        s = max(0, m.start() - 45); e = min(len(text), m.end() + 45)
        hits.append((m.group(), text[s:e].replace("\n", " ")))
    kw = [k for k in WELD_KEYWORDS if k in text.upper()]
    return hits, kw


def collect_part_texts(part):
    t = {}
    for k, v in part.items():
        if isinstance(v, str) and len(v) > 3:
            t[k] = v
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            t[k] = " | ".join(v)
    return t


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    print("=" * 80)
    print("WELD ORIGIN PROBE  (read-only)")
    print("=" * 80)

    records = find_part_records(data)
    print(f"part-like records found: {len(records)}")
    target = None
    for p, d in records:
        pn = str(d.get("part_number") or d.get("part_no") or d.get("name") or "")
        if TARGET in pn:
            target = (p, d); break
    if not target:
        for p, d in records:
            if "WELDING" in json.dumps(d).upper():
                target = (p, d)
                print("(1300-01 not matched by name; using first record that mentions welding)")
                break
    if not target:
        print("Could not locate the 1300-01 part record."); return

    ppath, part = target
    print(f"target record at : {ppath}")
    print(f"part_number      : {part.get('part_number') or part.get('name')}")

    # 1. op / weld / flag / feature fields
    print("\n--- operation / weld / risk / manufacturing fields on the part ---")
    for k, v in part.items():
        kl = k.lower()
        if any(t in kl for t in ("operation", "weld", "risk", "flag",
                                 "manufactur", "feature", "routing")):
            sv = json.dumps(v)[:500] if isinstance(v, (dict, list)) else v
            print(f"  {k}: {sv}")

    # 2. attached weld time (proves the costed line)
    print("\n--- any weld time attached (process estimate) ---")
    found_time = False
    for key in ("process_estimate", "process", "estimate", "wb_process_estimate"):
        pe = part.get(key)
        if isinstance(pe, dict):
            for tk in ("times_min", "run_times_min_per_unit", "setup_times_min", "run_times_min"):
                tm = pe.get(tk)
                if isinstance(tm, dict):
                    weldkeys = {x: tm[x] for x in tm if "weld" in str(x).lower()}
                    if weldkeys:
                        print(f"  {key}.{tk}: {json.dumps(weldkeys)}")
                        found_time = True
    if not found_time:
        print("  (no weld time found in part-level process estimate fields)")

    # 3. scan the part's OWN text for the engine's weld triggers
    print("\n--- WELD/MIG/TIG scan of the PART's own text fields ---")
    any_part_hit = False
    for k, t in collect_part_texts(part).items():
        hits, kw = text_hits(t)
        if hits or kw:
            any_part_hit = True
            print(f"  [{k}] keyword-membership={kw}")
            for g, ctx in hits[:6]:
                print(f"      \\bWELD\\b -> {g!r}   ...{ctx}...")
    if not any_part_hit:
        print("  NONE. 'welding' did NOT come from this part's own text.")

    # 4. whole-document text scan (catches the garbled page-2 DXF dump)
    print("\n--- WELD/MIG/TIG scan of ALL document text ---")
    doc_hits = []

    def walk_txt(o, p):
        if isinstance(o, dict):
            for k, v in o.items():
                walk_txt(v, f"{p}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk_txt(v, f"{p}[{i}]")
        elif isinstance(o, str) and len(o) > 20:
            if WELD_RE.search(o) or any(k in o.upper() for k in WELD_KEYWORDS):
                doc_hits.append((p, o))
    walk_txt(data, "root")

    if doc_hits:
        for p, t in doc_hits[:10]:
            m = WELD_RE.search(t)
            kw = [k for k in WELD_KEYWORDS if k in t.upper()]
            snip = ""
            if m:
                s = max(0, m.start() - 45); e = min(len(t), m.end() + 45)
                snip = t[s:e].replace("\n", " ")
            print(f"  {p}")
            print(f"      keyword-membership={kw}  regex_match={m.group() if m else None!r}")
            if snip:
                print(f"      ...{snip}...")
    else:
        print("  NONE anywhere in the JSON text.")

    # verdict
    print("\n" + "-" * 80)
    print("VERDICT:")
    if any_part_hit:
        print("  'welding' is TEXT-DERIVED from THIS part's text -> suppress in extractor/")
        print("  json_normaliser at the weld-keyword inference (the substring shown above).")
    elif doc_hits:
        print("  No weld text on the part, but WELD/MIG/TIG appears in document text (likely the")
        print("  garbled page-2 DXF dump). The op is a FALSE POSITIVE from doc-level text bleed ->")
        print("  suppress by not inferring weld from DXF-dump / cross-part page text.")
    else:
        print("  NO weld text anywhere. 'welding' is NOT text-derived -> it comes from a default/")
        print("  historical/inheritance path. Report this; we then suppress at the op-list source.")
    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_weld_origin.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
