"""Live shadow bridge from retained raw BOM to canonical parts and saved charged cells.

Never builds a substitute hierarchy, resolves local quantities by guess, or accepts a
positive price as proof of a stock/purchase basis. Missing source pages are explicit.
Normal packs without source requirements now report incomplete coverage instead of silence.
"""
from hashlib import sha256
import json
from requirement_coverage import audit


def evaluate(summary, snapshot):
    extract = summary.get('llm_full_extract') or {}
    rows = extract.get('bom') or []
    digest = sha256(str(extract.get('raw_response') or json.dumps(rows,sort_keys=True)).encode()).hexdigest()
    requirements, charges = [], []
    final = summary.get('final_estimate') or {}
    material = final.get('material_rows') or []
    cells = (snapshot or {}).get('cells') or {}
    # Existing contracts retain authority over commercial basis. Only their explicit
    # per-item evidence may authorise basis_verified; an absent adapter is not success.
    bases = summary.get('verified_charge_bases') or {}
    for index, source in enumerate(rows):
        pn = source.get('part_number')
        rid = f'pdf:{digest}:{index}'
        req = dict(id=rid, part_number=pn, quantity=source.get('qty'),
                   document=source.get('document'), page=source.get('page'), charge_ids=[])
        for row in material:
            # Only an exact identity. Do not infer identity from a description substring.
            if row.get('part_code') != pn:
                continue
            cell = row.get('charged_cell')
            cid = f'{cell}:{rid}'
            req['charge_ids'].append(cid)
            charges.append(dict(charge_id=cid, requirement_ids=[rid], cell=cell,
                value=row.get('total_value_gbp'), saved_value=cells.get(cell),
                basis_verified=bases.get(cell) is True))
        requirements.append(req)
    population = (summary.get('estimate_summary') or {}).get('canonical_part_estimates')
    if population is None:
        population = (summary.get('estimate_summary') or {}).get('part_estimates') or []
    if not isinstance(population,list):
        population=[]
    result = audit(requirements,population,charges)
    result.update(mode='shadow', source_sha256=digest, requirements=len(requirements),
                  scope='raw BOM material coverage only; local quantity basis, pages and assembly rollups require adapters',
                  workbook_verified=bool(snapshot))
    if rows and not extract.get('raw_response'):
        result['findings'].append('raw_response_missing')
        result['passed']=False
    return result


def record(summary, workbook):
    if summary.get('llm_only') or summary.get('concept_read'):
        result={'mode':'shadow','applicable':False,'reason':'concept path uses read ledger'}
    else:
        try:
            from final_charge_contract import snapshot_xlsx
            result=evaluate(summary,snapshot_xlsx(workbook))
            result['applicable']=True
        except Exception as exc:
            result={'mode':'shadow','applicable':True,'passed':False,
                    'coverage':'incomplete','findings':[f'checker_failed:{type(exc).__name__}:{exc}']}
        print(f"   [normal-pdf-audit:shadow] {len(result.get('findings') or [])} finding(s); "
              "not a release decision", flush=True)
    summary['normal_pdf_audit']=result
    return result
