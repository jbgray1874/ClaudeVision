"""The Dyson logo was on the page the whole time. It was white, on a white letterhead.

WHAT WAS REPORTED, three times over two days: "Dyson logo missing." Then, after a rename,
"dyson is there.....". Then, having made a PNG of it: "Dyson.png is not in this drop (no PNG in
the quote or in the files I can see)."

IT WAS IN THE DROP. Decoding the delivered quote's own base64 finds a valid 3800x1600 PNG with
`alt="Dyson"`, correctly sized and correctly placed in the customer block — drawn in white on a
transparent ground, sitting on a header whose background is #ffffff.

THE FILE WAS NEVER THE PROBLEM, AND NEITHER WAS THE FORMAT. The original `Dyson.svg` was
`.st0{fill:#FFFFFF;}` on every path. The replacement PNG is white letters on transparency. Both
render perfectly and both are invisible, so every fix aimed at the file — rename it, re-export
it, change the format — produced exactly the same blank space, which is why it looked like the
loader was ignoring the file.

AND THE WHITE MARK IS THE CORRECT MARK. Dyson's brand mark is white; their own guidelines put
it on a dark ground. So the fix is the GROUND, not the file: SDI's ink behind any logo whose
visible marks are light.

MEASURED, NOT LISTED. The alternative is a set of customers-whose-logo-is-white, which is a
list somebody has to maintain and nobody will when the next one arrives.

ALPHA IS THE WHOLE POINT of the raster test. A transparent PNG of a white wordmark is mostly
transparent, so averaging every pixel says "dark" and gets it exactly backwards. Only pixels a
reader will actually see are weighed.

WHY THIS IS A TEST. Nothing failed. No exception, no missing file, no broken path — the logo
rendered, and rendered invisibly. There is no error state to catch, so the only thing that can
notice is something that asserts on the contrast.
"""
from __future__ import annotations

import base64
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                          # noqa: E402


# ── the SVG case: Dyson.svg as it actually was ───────────────────────────────

WHITE_SVG = ('<svg viewBox="0 0 100 40"><style>.st0{fill:#FFFFFF;}</style>'
             '<path class="st0" d="M0 0h100v40H0z" fill="#FFFFFF"/></svg>')
# A dark mark in a colour of its OWN, deliberately not SDI's ink — otherwise the assertion
# below cannot tell the logo's fill from the plate's background.
DARK_SVG = ('<svg viewBox="0 0 100 40">'
            '<path d="M0 0h100v40H0z" fill="#123456"/></svg>')


def test_a_white_svg_is_recognised_as_needing_a_dark_ground():
    assert q._svg_is_light(WHITE_SVG) is True


def test_a_dark_svg_is_left_alone():
    """A dark mark on a dark plate is the same bug facing the other way."""
    assert q._svg_is_light(DARK_SVG) is False


def test_an_svg_with_no_stated_colours_is_not_guessed_at():
    """`currentColor`, a CSS class the parser cannot resolve, an external stylesheet. Unknown
    is a real answer and it must not resolve to either extreme."""
    assert q._svg_is_light('<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>') is None


def test_a_light_logo_gets_sdis_ink_behind_it(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    (tmp_path / "Dyson.svg").write_text(WHITE_SVG, encoding="utf-8")
    markup = q._load_logo_markup("Dyson")
    assert markup, "the logo did not load at all"
    assert "background:#282928" in markup, (
        "a white wordmark is being placed on a white letterhead — it will render, and it will "
        "render invisibly, which is the whole failure")


def test_a_dark_logo_is_not_boxed(tmp_path, monkeypatch):
    """A plate behind a mark that did not need one is a box somebody drew round the customer's
    logo, on their own quotation."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    (tmp_path / "Acme.svg").write_text(DARK_SVG, encoding="utf-8")
    assert "background:#282928" not in q._load_logo_markup("Acme")


# ── the raster case: the PNG James made ──────────────────────────────────────

def _png(rgba: tuple, size: int = 16) -> bytes:
    """A minimal valid PNG in one colour, alpha included — the transparency is what the
    averaging has to get right."""
    r, g, b, a = rgba
    raw = b"".join(b"\x00" + bytes([r, g, b, a]) * size for _ in range(size))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def test_a_white_png_is_recognised_as_light(tmp_path):
    pytest.importorskip("PIL")
    p = tmp_path / "w.png"
    p.write_bytes(_png((255, 255, 255, 255)))
    assert q._raster_is_light(str(p)) is True


def test_a_transparent_png_is_judged_on_what_shows(tmp_path):
    """THE TRAP. A wordmark is mostly empty space. Averaging every pixel of a transparent PNG
    of white letters says "dark", puts no plate behind it, and reproduces the exact bug."""
    pytest.importorskip("PIL")
    p = tmp_path / "t.png"
    # fully transparent black pixels — a naive mean over RGB reads 0 (dark); nothing is visible
    p.write_bytes(_png((0, 0, 0, 0)))
    assert q._raster_is_light(str(p)) is None, (
        "an image with nothing visible in it is being given a verdict")


def test_a_dark_png_is_left_alone(tmp_path):
    pytest.importorskip("PIL")
    p = tmp_path / "d.png"
    p.write_bytes(_png((20, 20, 20, 255)))
    assert q._raster_is_light(str(p)) is False


def test_a_png_is_judged_without_pillow_at_all(tmp_path, monkeypatch):
    """THE POINT OF THE STDLIB DECODER. Pillow is in requirements.txt, but a logo rendering
    invisibly must not depend on whether one optional package got installed on the box running
    the job — the failure when it is missing is silent and looks exactly like success, which is
    the same shape as the bug this is here to catch. So PNG is answered from zlib alone."""
    import builtins
    real = builtins.__import__

    def _no_pil(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no pillow here")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_pil)
    p = tmp_path / "x.png"
    p.write_bytes(_png((255, 255, 255, 255)))
    assert q._raster_is_light(str(p)) is True, "a PNG still needs Pillow to be judged"


def test_a_format_neither_reader_handles_is_not_guessed_at(tmp_path, monkeypatch):
    """Unknown is a real answer. A JPEG with no Pillow leaves the logo exactly as it renders
    today rather than plating it on a hunch."""
    import builtins
    real = builtins.__import__

    def _no_pil(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no pillow here")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_pil)
    p = tmp_path / "x.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0not really a jpeg")
    assert q._raster_is_light(str(p)) is None


# ── two files, one customer, a coin toss every run ───────────────────────────

def test_one_customer_with_two_logo_files_resolves_the_same_way_every_time(tmp_path,
                                                                            monkeypatch):
    """THE BEST FIT FOR WHAT WAS ACTUALLY OBSERVED.

    "Dyson logo missing" · a rename · "dyson is there....." · missing again · a new PNG ·
    "Dyson.png is not in this drop". Every fix aimed at the file appeared to work and then
    stopped working.

    The loader walked an UNSORTED os.listdir and took the first stem that matched. Once the
    SVG had been replaced rather than deleted, two files answered to `Dyson` — a white SVG that
    vanishes on a white header, and a black-plate PNG that shows — and which one reached the
    quote was whatever order the directory enumerated in that run. Same folder, same code, same
    customer, different logo.

    Deterministic now, and newest-first, which is the right reading of intent: exporting a new
    logo for a customer means the new one."""
    import os
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    (tmp_path / "Dyson.svg").write_text(WHITE_SVG, encoding="utf-8")
    (tmp_path / "Dyson.png").write_bytes(_png((255, 255, 255, 255)))
    os.utime(tmp_path / "Dyson.svg", (1_700_000_000, 1_700_000_000))
    os.utime(tmp_path / "Dyson.png", (1_800_000_000, 1_800_000_000))

    picked = {q._load_logo_markup("Dyson") for _ in range(5)}
    assert len(picked) == 1, "the same folder produced different logos on different calls"
    markup = picked.pop()
    assert "<img" in markup and "<svg" not in markup, "the newer file did not win"


def test_the_ambiguity_is_announced_rather_than_silently_resolved(tmp_path, monkeypatch,
                                                                  capsys):
    """An ambiguity nobody is told about is one nobody tidies up — and this one presents as an
    intermittent rendering fault, which is the hardest kind to chase."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    (tmp_path / "Dyson.svg").write_text(WHITE_SVG, encoding="utf-8")
    (tmp_path / "Dyson.png").write_bytes(_png((255, 255, 255, 255)))
    q._load_logo_markup("Dyson")
    out = capsys.readouterr().out
    assert "2 logo files match" in out and "Dyson" in out


def test_one_file_says_nothing(tmp_path, monkeypatch, capsys):
    """The note must not fire on the normal case, or it becomes noise nobody reads."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    (tmp_path / "Acme.svg").write_text(DARK_SVG, encoding="utf-8")
    q._load_logo_markup("Acme")
    assert "logo files match" not in capsys.readouterr().out


# ── the real file James made ─────────────────────────────────────────────────

def test_a_black_plate_logo_is_left_alone(tmp_path):
    """THE CORRECTION I OWE THE RECORD. Decoding the delivered quote showed white lettering on
    what looked like transparency, and I reported it as an invisible white-on-white logo. It is
    not: the real Dyson.png is colour-type 3 (palette), carries NO tRNS chunk, and its mean
    visible luminance is 58 — a solid BLACK plate with white letters, which shows perfectly
    well on a white header and needs no plate of ours.

    The first measurement said 0.0 because it stopped sampling once it had enough pixels, and
    the top of a wordmark's canvas is margin. Sampling has to span the height."""
    tall = tmp_path / "tall.png"
    # black margin at the top, white content lower down — the shape that fooled the first pass
    rows = ([bytes([0]) + bytes([0, 0, 0, 255]) * 8] * 24
            + [bytes([0]) + bytes([255, 255, 255, 255]) * 8] * 8)
    import struct as _s, zlib as _z
    def _chunk(tag, data):
        return (_s.pack(">I", len(data)) + tag + data
                + _s.pack(">I", _z.crc32(tag + data) & 0xFFFFFFFF))
    tall.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + _chunk(b"IHDR", _s.pack(">IIBBBBB", 8, 32, 8, 6, 0, 0, 0))
                     + _chunk(b"IDAT", _z.compress(b"".join(rows)))
                     + _chunk(b"IEND", b""))
    lum = q._png_visible_luminance(str(tall))
    assert lum is not None
    assert lum < 200, ("sampling stopped in the top margin again — a mostly-black image with "
                       "white content is being read from its first rows only")


# ── A WEBP LOGO IS ACCEPTED, AND EMBEDDED AS PNG ────────────────────────────────────
#
# Harrods' logo arrived as .webp. The loader read .svg/.png/.jpg/.jpeg/.gif and nothing
# else, so the file was silently skipped and a Harrods quote fell back to the customer's
# name in text — no logo, no error, no reason given. WEBP is now accepted, and because the
# quote is emailed and printed to PDF (where WEBP is unreliable), it is transcoded to a PNG
# data URI rather than embedded raw.

import pytest as _pytest


def _webp(path, rgba, size=(40, 16)):
    from PIL import Image
    Image.new("RGBA", size, rgba).save(str(path), "WEBP")


def test_a_webp_logo_is_found_and_embedded_as_png(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    _webp(tmp_path / "Harrods.webp", (183, 138, 40, 255))   # a gold plate
    markup = q._load_logo_markup("Harrods")
    assert "<img" in markup, "a .webp logo whose stem matches the customer must be embedded"
    assert "data:image/png;base64," in markup, (
        "the quote is emailed and printed to PDF; the embedded logo must be PNG, not WEBP")
    assert "data:image/webp" not in markup


def test_the_webp_transcode_produces_a_valid_png(tmp_path):
    raw = q._webp_to_png_bytes(str(tmp_path / "nope.webp"))
    assert raw is None, "an unreadable file returns None, not a crash"
    p = tmp_path / "logo.webp"
    _webp(p, (10, 20, 30, 255))
    raw = q._webp_to_png_bytes(str(p))
    assert raw is not None and raw[:8] == b"\x89PNG\r\n\x1a\n", "transcode must be real PNG bytes"


def test_a_webp_customer_still_matches_by_normalised_key(tmp_path, monkeypatch):
    """The extension changed; the key rule did not. A file named to match the customer is
    found whether it is png or webp."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    _webp(tmp_path / "HARRODS.webp", (183, 138, 40, 255))
    assert "<img" in q._load_logo_markup("harrods")


def test_a_light_webp_gets_the_dark_ground_like_any_raster(tmp_path, monkeypatch):
    """The transcode does not bypass the white-logo guard: a light WEBP is plated the same
    as a light PNG, because the ground is decided by the pixels, not the container."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    _webp(tmp_path / "Pale.webp", (250, 250, 250, 255))     # a near-white mark
    assert "background:#282928" in q._load_logo_markup("Pale")


def test_a_png_logo_is_unchanged_by_the_webp_branch(tmp_path, monkeypatch):
    """Regression guard: adding WEBP must not alter how a PNG is embedded."""
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(tmp_path))
    from PIL import Image
    Image.new("RGBA", (40, 16), (183, 138, 40, 255)).save(str(tmp_path / "Boots.png"), "PNG")
    markup = q._load_logo_markup("Boots")
    assert "data:image/png;base64," in markup and "<img" in markup
