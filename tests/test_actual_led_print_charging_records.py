"""Private records stay external. Skipping missing evidence is not real-run proof."""
import contextlib
import io
import os
from pathlib import Path
import socket
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_led_print_charging_offline import replay

def test_actual_records_and_drawing_pages(monkeypatch):
    names=('SDI_12133_LED_RECORD','SDI_12133_LED_DRAWINGS','SDI_12713_CHARGE_RECORD','SDI_12713_CHARGE_DRAWINGS')
    args=[os.environ.get(n) for n in names]
    if not all(args):pytest.skip('Set external private record/drawing paths: '+', '.join(names))
    def no_network(*a,**kw):raise AssertionError('Offline real-record regression attempted network access')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    with contextlib.redirect_stdout(io.StringIO()):report=replay(*(Path(a) for a in args))
    assert report['passed'],report
