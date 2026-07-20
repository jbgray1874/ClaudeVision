# Read-only: for 3886-02 and 3886-03, dump EVERYTHING the engine captured that could
# carry fold intent — note-scan text, textual_operations, manufacturing observations,
# any field mentioning fold/bend/down/up/degree/R. Answers: are the "DOWN 90 R1" callouts
# already in the JSON (just not turned into a Fold op), or do we need to parse the PDF fresh?
import json, glob, os, re

d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("reading:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

TARGETS = ("3886-02", "3886-03")
FOLD_RE = re.compile(r"\b(DOWN|UP)\b|\bR\s*\d|°|\bdeg\b|\bfold\b|\bbend\b|\bflange\b|90\.?0?0?", re.I)

def walk(o, path="root"):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")

# find the part records for the targets and dump their text-bearing fields
for tgt in TARGETS:
    print("="*70)
    print(f"PART {tgt}")
    print("="*70)
    found_any = False
    for path, node in walk(J):
        if not isinstance(node, dict): continue
        pn = str(node.get("part_number") or "")
        if pn != tgt: continue
        # this node is a record for the target — dump its text-ish fields
        for k, v in node.items():
            if k in ("part_number",): continue
            txt = None
            if isinstance(v, str) and len(v) > 0:
                txt = v
            elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                txt = " | ".join(v)
            if txt and (FOLD_RE.search(txt) or k in ("note_scan","notes","textual_operations",
                        "operations","manufacturing_observations","surface_finishes","all_text",
                        "process_notes","drawing_notes")):
                found_any = True
                snippet = txt[:400]
                hit = "  <-- FOLD SIGNAL" if FOLD_RE.search(txt) else ""
                print(f"  [{path.split('.')[-1]}::{k}]{hit}")
                print(f"     {snippet}")
    if not found_any:
        print("  (no fold-signal text fields found on this part's records)")
    print()

# Also: search the WHOLE json for any DOWN/UP + degree callout, to see if the raw
# annotation text was captured anywhere at all (even not attached to the part).
print("="*70)
print("ANY 'DOWN/UP ... 90 ... R' callout anywhere in the JSON?")
print("="*70)
DOWN_CALL = re.compile(r"(DOWN|UP)\s*9?0?\.?0?°?\s*R?\s*\d", re.I)
hits = 0
for path, node in walk(J):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and DOWN_CALL.search(v):
                hits += 1
                if hits <= 15:
                    m = DOWN_CALL.search(v)
                    print(f"  {path.split('.')[-1]}.{k}: ...{v[max(0,m.start()-20):m.end()+30]}...")
print(f"  total DOWN/UP-degree-R hits in JSON: {hits}")
if hits == 0:
    print("  -> The explicit fold callouts are NOT in the JSON. They live only in the PDF")
    print("     annotations and would need fresh parsing. (Or note-scan's char cap missed them.)")
