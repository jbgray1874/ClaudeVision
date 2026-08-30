r"""READ-ONLY. Confirm each top-level section compares engine vs Tim against the CORRECT
counterpart — i.e. the label-scan matched the right engine JSON field to the right Tim cell.
For each money_cell_comparison, show: the label, which engine JSON path it read, the engine
value, the Tim cell + value, and a sanity check that they're the same KIND of number.
Also cross-check against Tim's known sheet values (Material £90.60, Labour £55.92, Unit £168.68)
and the engine's known values, so we prove nothing is mispaired. No edits."""
import json
b=r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
J=json.load(open(b,encoding="utf-8"))

# Tim's known-correct values (read directly from his sheet earlier)
tim_known = {
    "material": 90.59844, "labour": 55.920177, "unit": 168.679765, "sell": 168.679765, "qty": 100.0,
}
# Engine's known values
eng_known = {
    "material": 108.63, "labour": 75.35, "unit": 214.1095, "qty": 100.0,  # normalised
}

print("="*74)
print("TOP-LEVEL SECTION PAIRINGS — engine field  ->  Tim cell")
print("="*74)
for r in (J.get("money_cell_comparisons") or []):
    if r.get("section")!="money_cell": continue
    label=r.get("label")
    jpath=r.get("json_path","")
    eng=r.get("json_numeric")
    tim=r.get("workbook_cached_numeric")
    cell=r.get("cell")
    status=r.get("status")
    # which engine field short-name
    short=jpath.split(".")[-1] if jpath else "?"
    print(f"\n  [{label}]")
    print(f"     engine <- {short}  = {eng}")
    print(f"     Tim    <- cell {cell} = {tim}")
    print(f"     status: {status}")
    # sanity: does Tim's value match the known-correct section value?
    lab_l=str(label).lower()
    for key,val in tim_known.items():
        if key in lab_l and tim is not None:
            ok = abs(tim-val)<0.5
            print(f"     CHECK: Tim {key} expected ~{val:.2f}, got {tim:.2f} -> {'CORRECT PAIR' if ok else 'MISPAIRED?'}")
    for key,val in eng_known.items():
        if key in lab_l and eng is not None:
            ok = abs(eng-val)<0.5
            print(f"     CHECK: Engine {key} expected ~{val:.2f}, got {eng:.2f} -> {'CORRECT' if ok else 'CHECK'}")

print("\n"+"="*74)
print("SUMMARY: are the three key levels correctly paired?")
print("="*74)
def find(lbl_contains):
    for r in (J.get("money_cell_comparisons") or []):
        if lbl_contains in str(r.get("label","")).lower():
            return r
    return None
for name,needle,te,ee in [("MATERIAL","material",90.60,108.63),
                          ("LABOUR","labour",55.92,75.35),
                          ("UNIT COST","unit",168.68,214.11)]:
    r=find(needle)
    if r:
        t=r.get("workbook_cached_numeric"); e=r.get("json_numeric")
        tok = t is not None and abs(t-te)<0.5
        eok = e is not None and abs(e-ee)<0.5
        print(f"  {name:<10}: engine {e} (exp {ee}) {'OK' if eok else 'X'} | Tim {t} (exp {te}) {'OK' if tok else 'X'} | "
              f"{'CORRECTLY PAIRED' if (tok and eok) else 'MISPAIRED'}")
    else:
        print(f"  {name:<10}: NOT FOUND in comparisons")
