"""The quote's header carries the we.are.sdi logo, from an SVG or a picture of it (D-611).

1 Nov 2026, James, on the 12678-01-GA quote: "why is the insignia of wearesdi just a yellow
circle?" The quote looked for wearesdi.svg in the logo folder and, finding none, drew its
fallback: a plain yellow circle. The portal's own /api/brand/logo takes a PNG, JPG or WebP of
the same logo, so a folder holding a picture of it gave the portal a logo and the quote none.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import client_quote_html as q  # noqa: E402

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>we.are.sdi</text></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_an_svg_logo_is_used(tmp_path, monkeypatch):
    (tmp_path / "We Are SDI.svg").write_text(SVG, encoding="utf-8")
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    assert "we.are.sdi</text>" in q._sdi_logo_markup()


def test_a_png_of_the_logo_is_embedded_when_there_is_no_svg(tmp_path, monkeypatch):
    (tmp_path / "wearesdi.png").write_bytes(PNG)
    (tmp_path / "M&S.png").write_bytes(PNG)
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    got = q._sdi_logo_markup()
    assert 'src="data:image/png;base64,' in got and 'alt="we.are.sdi"' in got
    assert "<circle" not in got


def test_the_svg_wins_over_a_picture(tmp_path, monkeypatch):
    (tmp_path / "wearesdi.png").write_bytes(PNG)
    (tmp_path / "wearesdi.svg").write_text(SVG, encoding="utf-8")
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    assert "<svg" in q._sdi_logo_markup() and "base64" not in q._sdi_logo_markup()


def test_no_logo_file_draws_the_plain_mark_and_says_why(tmp_path, monkeypatch, capsys):
    (tmp_path / "M&S.svg").write_text(SVG, encoding="utf-8")
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    got = q._sdi_logo_markup()
    assert '<circle cx="50" cy="50" r="50" fill="#F5D947"/>' in got
    assert "no we.are.sdi logo file" in capsys.readouterr().out


def test_a_missing_folder_still_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path / "nowhere"))
    assert "<circle" in q._sdi_logo_markup()
