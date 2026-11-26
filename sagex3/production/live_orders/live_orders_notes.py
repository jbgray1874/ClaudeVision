"""Production's notes on Live Orders - typed in the portal (shared, live) or in the workbook - merged at each
Regenerate so neither loses anything. Written 25 Nov 2026 (James: "ok, do it" - notes typed in the portal).

The five typed columns, by works order: Comments, Prog, Tube req, Material (blank for Production's notes since 25 Nov,
Dave) and Notes (added 25 Nov, Dave). Keys: comments, prog, tube, mat, notes.

Where they live:
  * the portal's store, one per environment: <runs>\\notes.json  {wo: {key: {"v": text, "by": name, "at": iso time}}}
    written by live_orders_routes.py (POST /api/live-orders/notes), every change also appended to notes_log.jsonl;
  * the newest workbook's yellow columns (build_live_orders.read_carry), for anyone who types in Excel.

At Regenerate (run_x3.py), per works order and column, against what the newest workbook was generated with (its .json):
  * changed in the portal only (a note after that generation)  -> the portal's;
  * changed in the workbook only (differs from what it was generated with) -> the workbook's;
  * changed in both -> the later one (the note's time against the workbook's saved time);
  * neither -> as generated.
The result goes into the new workbook and its .json, so the portal and the spreadsheet agree again.
"""
import datetime as dt
import json
from pathlib import Path

KEYS = ("comments", "prog", "tube", "mat", "notes")
LABELS = {"comments": "Comments", "prog": "Prog", "tube": "Tube req", "mat": "Material", "notes": "Notes"}


def load_store(runs):
    f = Path(runs) / "notes.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}


def _t(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace(" ", "T")[:19])
    except ValueError:
        return None


def generated(book):
    """What the workbook was generated with (the .json beside it) and when: ({wo: {key: text}}, datetime)."""
    j = Path(book).with_suffix(".json")
    gen, when = {}, None
    try:
        d = json.loads(j.read_text(encoding="utf-8"))
        for w in d.get("wos", []):
            n = dict(w.get("n") or {})
            if "note" in n and "mat" not in n:         # runs before 25 Nov called the material note "note"
                n["mat"] = n.pop("note")
            gen[str(w.get("wo"))] = {k: str(n.get(k) or "") for k in KEYS}
        when = _t(d.get("built_at") or "")
    except (OSError, ValueError, AttributeError):
        pass
    if when is None:                                   # no record: the time in the workbook's name (when it was saved)
        import re
        m = re.search(r"(\d{4}-\d\d-\d\d)_(\d\d)(\d\d)", Path(book).stem)
        when = dt.datetime.fromisoformat(f"{m[1]}T{m[2]}:{m[3]}") if m else dt.datetime.min
    return gen, when


def merge(book, runs, read_carry):
    """The notes for the next generation: {wo: {key: text}} (non-empty records only), and what came from where."""
    store = load_store(runs)
    excel, gen, when, saved = {}, {}, dt.datetime.min, dt.datetime.min
    if book and Path(book).exists():
        excel = read_carry(book)
        gen, when = generated(book)
        saved = dt.datetime.fromtimestamp(Path(book).stat().st_mtime)
    info = dict(from_portal=0, from_workbook=0, both_changed=0, workbook=str(book or ""), store_entries=0)
    out = {}
    for wo in set(excel) | set(gen) | set(store):
        rec = {}
        for k in KEYS:
            g = (gen.get(wo) or {}).get(k, "")
            # the workbook's value: a works order it has with nothing typed reads "" (cleared in Excel)
            e = (excel.get(wo) or {}).get(k, "") if (wo in excel or wo in gen) else g
            p = (store.get(wo) or {}).get(k)
            p_new = bool(p) and (_t(p.get("at")) or dt.datetime.min) > when
            e_new = e != g
            if p:
                info["store_entries"] += 1
            if p_new and e_new:
                info["both_changed"] += 1
                v = p.get("v", "") if (_t(p.get("at")) or dt.datetime.min) >= saved else e
            elif p_new:
                info["from_portal"] += 1
                v = p.get("v", "")
            elif e_new:
                info["from_workbook"] += 1
                v = e
            else:
                v = g
            rec[k] = str(v or "").strip()
        if any(rec.values()):
            out[wo] = rec
    return out, info
