import copy
import json
import pytest
import batch_job_changes as bj
import tti_pricer as tp


def payload():
    return {'accepted_by':'Estimator', 'changes':[{'part':'50001-01-11G',
        'field':'thickness_mm','value':2,'drawing_value':1,'accepted':True,
        'origin':'manual','reason':'Customer confirmed 2 mm instead of the issued 1 mm drawing'}]}


def write(tmp_path, data=None):
    p=tmp_path/'changes.json'
    p.write_text(json.dumps(data or {'client':'Example','drawings':{'50001-00-GA':payload()}}))
    return p


def test_scoped_changes_are_carried_to_customer_change_engine(tmp_path):
    from customer_changes import build_changes_file, apply_customer_changes
    changes=bj.load_changes(write(tmp_path),'Example')
    rows=[{'drawing':'50001-00-GA'}, {'drawing':'50002-00-GA'}]
    bj.bind_changes(rows,changes)
    assert '_customer_changes' not in rows[1]
    checked,errors=build_changes_file(rows[0]['_customer_changes'],'50001-00-GA')
    assert not errors
    part={'part_number':'50001-01-11G','normalized_thickness_mm':1,'thickness_source':'dxf'}
    apply_customer_changes([part],checked)
    assert part['normalized_thickness_mm']==2
    assert part['thickness_source']=='customer_change'


def test_added_changed_and_removed_decision_invalidates_reuse():
    row={'quantity':1}
    old=tp.input_key(None,row,'brief','full','Example')
    row['_customer_changes']=payload()
    new=tp.input_key(None,row,'brief','full','Example')
    assert tp.changed_inputs(old,new)==['customer_changes']
    assert tp.changed_inputs(new,old)==['customer_changes']
    row['_customer_changes']['changes'][0]['value']=3
    third=tp.input_key(None,row,'brief','full','Example')
    assert tp.changed_inputs(new,third)==['customer_changes']


def test_wrong_client_or_unselected_drawing_refused(tmp_path):
    p=write(tmp_path)
    with pytest.raises(ValueError):bj.load_changes(p,'Other')
    with pytest.raises(ValueError):bj.bind_changes([{'drawing':'50002-00-GA'}],bj.load_changes(p,'Example'))


@pytest.mark.parametrize('field,value', [('unit_price',5),('quantity',3),('thickness_mm',float('inf')),
                                       ('thickness_mm',float('nan')),('thickness_mm',True)])
def test_no_prices_quantity_changes_or_invalid_gauges(tmp_path,field,value):
    data={'client':'Example','drawings':{'50001-00-GA':payload()}}
    data['drawings']['50001-00-GA']['changes'][0].update(field=field,value=value)
    with pytest.raises(ValueError):bj.load_changes(write(tmp_path,data),'Example')


def test_no_implicit_acceptance(tmp_path):
    data={'client':'Example','drawings':{'50001-00-GA':payload()}}
    data['drawings']['50001-00-GA']['changes'][0]['accepted']='yes'
    with pytest.raises(ValueError):bj.load_changes(write(tmp_path,data),'Example')


def test_parser_exposes_changes_without_changing_run_again_semantics():
    args=tp.build_parser().parse_args(['--job-changes','x.json','--replace-costs'])
    assert args.job_changes=='x.json' and not args.run_again
