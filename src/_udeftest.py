import config, bay_rollup
# Test the UDEF lookup directly for the four codes that ARE being extracted
tests = [
    ("ELECTRICS 50cm LOOM LIGHTING ELECTRICS", "ELECTRICS"),
    ("FIXING5 4.0x10mm DOME RIVET", "FIXING5"),
    ("FIXING 236 M8 FLANGED NUTSERT", "FIXING236"),
    ("FIXING 125 M8x38mm DIA GLIDE", "FIXING125"),
]
for desc, code in tests:
    r = bay_rollup._udef_fuzzy_lookup(desc, code)
    if r:
        print(f"{code:12} -> FOUND  £{r.get('unit_cost_gbp')}  {r.get('code')!r}  {r.get('supplier_name')!r}")
    else:
        print(f"{code:12} -> NO MATCH in UDEF")
