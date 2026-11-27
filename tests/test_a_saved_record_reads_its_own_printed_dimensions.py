"""Recovery from saved evidence reads each page's printed dimensions from its OWN PDF.

A record saved before the printed-dimension reader existed has no axes, and its text alone
lets an internal dimension pass for a panel's height. The recovery copy reads the page's own
named file, on its own page, and leaves the saved record itself untouched. Synthetic only.
"""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

fitz = pytest.importorskip('fitz')
from drawing_dimension_evidence import read_saved_pages
from owned_component_manufacturing import prepare as owned_pass

ROOT = Path(__file__).resolve().parents[1]
TEXT = '6\n1866\n770\n1518\nFRONT PANEL\n18MM MR MDF 3050X1220MM\nSPRAY BROWN\n6\n'


def _pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((200, 80), '1866', fontsize=9)               # overall width, horizontal
    page.insert_text((120, 300), '770', fontsize=9, rotate=90)    # overall height, vertical
    page.insert_text((300, 200), '1518', fontsize=9)              # an internal horizontal span
    page.insert_text((200, 500), '18MM MR MDF 3050X1220MM', fontsize=9)
    doc.save(str(path))
    return path


def _record(pdf):
    return {'pages': [{'source_pdf_name': pdf.name, 'page_number': 1, 'source_page_number': 1,
                       'source_pdf_path': str(pdf), 'pypdf_text': TEXT, 'normalized_text': TEXT,
                       'pattern_summary': {'part_numbers': ['C.45678']},
                       'page_analysis': {'title_block': {'part_numbers': ['C.45678']}}}],
            'manufacturing_writeup': {'parts': [{'part_number': 'C.45678', 'quantity': 1}]}}


def test_the_panel_takes_its_printed_size_not_an_internal_dimension(tmp_path):
    rec = _record(_pdf(tmp_path / 'nc1-c45678.pdf'))
    unread = copy.deepcopy(rec)
    owned_pass(unread)
    assert unread['manufacturing_writeup']['parts'][0]['blank_width_mm'] != 770
    audit = read_saved_pages(rec)
    assert [r['axes_mm'] for r in audit['read']] == [[1866.0, 770.0]]
    owned_pass(rec)
    part = rec['manufacturing_writeup']['parts'][0]
    assert (part['blank_length_mm'], part['blank_width_mm']) == (1866.0, 770.0)
    assert part['owned_thickness_conflict']['printed_mm'] == [6]


def test_a_folder_match_must_be_one_file_and_a_missing_file_is_reported(tmp_path):
    pdf = _pdf(tmp_path / 'saved' / 'nc1-c45678.pdf') if (tmp_path / 'saved').mkdir() is None else None
    rec = _record(pdf)
    rec['pages'][0]['source_pdf_path'] = str(tmp_path / 'gone' / 'nc1-c45678.pdf')
    assert read_saved_pages(copy.deepcopy(rec))['not_read'][0]['reason'].startswith('FileNotFoundError')
    two = tmp_path / 'two'
    (two / 'a').mkdir(parents=True); (two / 'b').mkdir()
    _pdf(two / 'a' / 'nc1-c45678.pdf')
    (two / 'b' / 'nc1-c45678.pdf').write_bytes(b'%PDF-1.4 different')
    audit = read_saved_pages(copy.deepcopy(rec), two)
    assert audit['read'] == [] and 'several different files' in audit['not_read'][0]['reason']
    one = tmp_path / 'one'; one.mkdir(); _pdf(one / 'nc1-c45678.pdf')
    assert read_saved_pages(copy.deepcopy(rec), one)['read'][0]['axes_mm'] == [1866.0, 770.0]


def test_the_tool_writes_a_new_input_and_never_touches_the_saved_record(tmp_path):
    pdf = _pdf(tmp_path / 'nc1-c45678.pdf')
    saved = tmp_path / 'job_record.json'
    saved.write_text(json.dumps(_record(pdf)), encoding='utf-8')
    before = hashlib.sha256(saved.read_bytes()).hexdigest()
    out = tmp_path / 'recovery' / 'prepared.json'
    tool = ROOT / 'tools' / 'estimating' / 'prepare_saved_scope_recovery.py'
    done = subprocess.run([sys.executable, str(tool), str(saved), '--out', str(out),
                           '--read-printed-dimensions'], capture_output=True, text=True, cwd=str(tmp_path))
    assert done.returncode == 0, done.stderr[-2000:]
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == before
    assert '"source_record_sha256": "%s"' % before in done.stdout
    assert json.loads(out.read_text(encoding='utf-8'))['pages'][0]['printed_dimension_axes']['axes_mm'] == [1866.0, 770.0]
    again = subprocess.run([sys.executable, str(tool), str(saved), '--out', str(out), '--read-printed-dimensions'],
                           capture_output=True, text=True, cwd=str(tmp_path))
    assert again.returncode != 0 and 'never the source or an existing result' in again.stderr
