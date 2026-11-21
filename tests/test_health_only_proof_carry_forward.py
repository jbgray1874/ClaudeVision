import importlib.util
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
if not (ROOT/'src/tti_concept_inputs.py').exists():
    sys.path.insert(0,r'C:\ClaudeVision\src')  # standalone laptop package review
spec=importlib.util.spec_from_file_location('health_batch',ROOT/'src/tti_concept_batch.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

def git(changed,ancestor=True):
    def run(*args):
        if args[0]=='rev-parse': return ('a'*40 if args[1].startswith('a') else 'b'*40)
        if args[0]=='merge-base': return 'a'*40 if ancestor else 'c'*40
        return changed
    return run

def test_explicit_bridge_keeps_original_build_and_records_new():
    x=b.validate_health_only_proof_build(ROOT,'a'*7,'b'*7,git('tools/runner/sdi_estimate_runner.py'))
    assert x['proof_execution_build']=='a'*40 and x['resume_build']=='b'*40

@pytest.mark.parametrize('changed,ancestor',[('src/costing.py',True),('src/tti_concept_inputs.py',True),('',True),('tools/runner/sdi_estimate_runner.py',False)])
def test_pricing_changes_or_nonancestor_never_bypass_gate(changed,ancestor):
    with pytest.raises(ValueError): b.validate_health_only_proof_build(ROOT,'a'*7,'b'*7,git(changed,ancestor))

@pytest.mark.parametrize('switch',['--assume-missing-quantity-one','--blank-quantity-as-one'])
def test_both_quantity_aliases_survive(switch):
    a=b.argument_parser().parse_args(['--sheet','x','--plan-output','p',switch])
    assert a.assume_missing_quantity_one

def test_unknown_process_count_still_fails():
    with pytest.raises(RuntimeError): b.check_build([{'online':True,'build':'0490bf7','process_count':None}], '0490bf7',1)
