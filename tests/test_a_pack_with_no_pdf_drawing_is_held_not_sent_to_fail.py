"""A PACK WITH NO PDF DRAWING IS HELD, NOT SENT TO FAIL (18 Nov 2026).

7758B-01 and 12132-01-GA went out with SolidWorks files and a flat DXF only. The engine builds a
job from its PDF drawings, so each run stopped within half a minute with "No drawing files found",
every time it was tried. The row is now held with the reason, for Design to save the PDFs.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pack_store as ps  # noqa: E402
import tti_pricer as tp  # noqa: E402
from test_a_run_is_handed_the_whole_pack_with_its_top_level_drawing_or_nothing_is_sent import _batch  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal  # noqa: E402


def test_a_pack_of_models_and_flats_only_is_held_with_the_reason(tmp_path, monkeypatch):
    first = FakePortal()
    _batch(tmp_path, monkeypatch, first)
    assert first.started, "a pack with its PDF is sent"
    real = ps.stored_files
    monkeypatch.setattr(ps, "stored_files",
                        lambda kept, manifest: [p for p in real(kept, manifest) if not str(p).lower().endswith(".pdf")])
    portal = FakePortal()
    row = _batch(tmp_path, monkeypatch, portal)
    assert portal.started == [] and row["state"] == "held: pack not complete"
    assert "holds no PDF drawing" in row["why"] and "Design to save" in row["why"]
