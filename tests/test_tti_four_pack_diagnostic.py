import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('four_pack_diagnostic',Path(__file__).resolve().parents[1]/'tools/diagnose_tti_four_packs.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

def test_read_failure_never_becomes_missing_pack():
    def fails(*a):raise PermissionError('Design denied')
    result=d.discover('12806-00-GA',[],SimpleNamespace(rows_for_job_now=fails))
    assert result['state']=='lookup_error' and 'Design denied' in result['error']

def test_no_folder_is_distinct_from_a_read_error():
    r=SimpleNamespace(rows_for_job_now=lambda *a:([],'Design: no folder; Prototype: no folder',set()))
    assert d.discover('12806-00-GA',[],r)['state']=='no_exact_filename'

def test_exact_design_file_keeps_area_and_archive_evidence():
    folder=Path('design/job');file=folder/'12806-00-GA.pdf'
    r=SimpleNamespace(rows_for_job_now=lambda *a:([(folder,[(file,123,42)],True)],'Design read',{str(folder)}),
                      drawing_id=lambda n:n.removesuffix('.pdf'),_same=lambda a,b:a==b)
    result=d.discover('12806-00-GA',[],r)
    assert result['state']=='exact_filename_found'
    assert result['exact_files'][0]['area']=='Design' and result['exact_files'][0]['archive']
