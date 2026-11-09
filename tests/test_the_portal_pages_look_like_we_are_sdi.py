"""The portal pages carry the we.are.sdi look on their dark ground (D-754).

JG, 8 Nov 2026: "re brand the SDI Intelligence portal pages ... slightly more in line with
wearesdi.com without changing the overall dark theme ... still make it we are sdi
recognisable." The site is SDI yellow (#F6D946) on black and white, a lower-case "we.are.sdi"
wordmark, a geometric sans and an elegant serif, pill buttons and halftone dot circles. The
pages keep their dark ground and their light mode; the brand moves from amber to SDI yellow,
and amber stays as the warning colour so the two never read as one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"
PAGES = ("sdi-intelligence-portal.html", "sdi-estimating-intelligence.html",
         "sdi-estimating-guide.html", "sdi-walkthrough.html", "sdi-estimating-wall.html")


def _page(name):
    return (BACKEND / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PAGES)
def test_every_page_carries_the_wordmark_with_its_two_yellow_dots(name):
    page = _page(name)
    m = re.search(r'<svg class="sdi-word[^"]*" viewBox="0 0 950 169" role="img" '
                  r'aria-label="we\.are\.sdi" fill="currentColor">(.*?)</svg>', page, re.S)
    assert m, f"{name} has no we.are.sdi wordmark"
    assert m.group(1).count('<path class="d"') == 2, "the two dots of we.are.sdi take the brand"
    assert ".sdi-word .d{fill:var(" in page
    assert "sdi-dots" in page, "the halftone circle of the site"


@pytest.mark.parametrize("name, token", [
    ("sdi-intelligence-portal.html", "--accent"),
    ("sdi-estimating-intelligence.html", "--brand"),
    ("sdi-estimating-guide.html", "--brand"),
    ("sdi-walkthrough.html", "--brand"),
    ("sdi-estimating-wall.html", "--accent"),
])
def test_the_brand_is_sdi_yellow_and_the_warning_keeps_its_amber(name, token):
    page = _page(name)
    root = page[page.index(":root{"):]
    root = root[:root.index("}")]
    assert f"{token}:#F6D946" in root, f"{name}: the brand token is not SDI yellow"
    warn = re.search(r"--warn:(#[0-9a-fA-F]{6})", page)
    if warn:
        assert warn.group(1).upper() != "#F6D946", "a warning must not look like the brand"


@pytest.mark.parametrize("name, fill", [
    ("sdi-intelligence-portal.html", "--accent-fill"),
    ("sdi-estimating-intelligence.html", "--brand-fill"),
    ("sdi-estimating-guide.html", "--brand-fill"),
])
def test_on_white_the_brand_text_goes_mustard_and_the_buttons_stay_yellow(name, fill):
    """SDI yellow carries no text on white (1.3:1), so light mode writes the brand in a deep
    mustard of the same hue (5.8:1) and keeps the filled buttons yellow under black ink."""
    page = _page(name)
    light = page[page.index(':root[data-theme="light"]{'):]
    light = light[:light.index("}")]
    assert "#7a6300" in light and f"{fill}:#F6D946" in light
    assert f"background:var({fill}" in page      # alone, or with a fallback as the sidebar writes it


def test_the_wall_has_no_cyan_left_and_still_loads_nothing_from_outside():
    wall = _page("sdi-estimating-wall.html")
    assert "22d3ee" not in wall.lower() and not re.search(r"rgba\(34, *211, *238", wall)
    assert "<link " not in wall


def test_the_display_faces_are_the_sites_kind():
    """A geometric sans for headings (the site's Sofia Pro is licensed; Outfit is its kin) and
    an elegant serif for the tagline (the site's Juana; Fraunces light)."""
    portal = _page("sdi-intelligence-portal.html")
    assert "family=Outfit" in portal and "family=Fraunces" in portal
    assert "--disp:'Outfit'" in portal and "h1.tagline{font-family:var(--serif-disp)" in portal
    assert "--disp:'Outfit'" in _page("sdi-estimating-intelligence.html")


def test_the_fallback_mark_is_sdi_yellow_everywhere_it_is_written():
    app = (BACKEND / "app.py").read_text(encoding="utf-8")
    assert '<circle cx="50" cy="50" r="50" fill="#F6D946"/>' in app
    for name in ("_inject_sidebar.py", "sdi-intelligence-portal.html",
                 "sdi-estimating-intelligence.html", "sdi-estimating-guide.html"):
        text = (BACKEND / name).read_text(encoding="utf-8")
        assert "fill=%22%23F6D946%22" in text and "fill=%22%23e8a33d%22" not in text, name


# ── D-754a: the shared sidebar comes from its generator, and light-mode warnings are legible ──

def _generator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_inject_sidebar_under_test",
                                                  BACKEND / "_inject_sidebar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ("sdi-estimating-intelligence.html", "sdi-estimating-guide.html"))
def test_running_the_sidebar_generator_would_change_nothing_on_the_page(name):
    """Reviewer, 8 Nov: the sidebar's shared source must be repaired, or regeneration could undo
    the manual changes. The generator read a SERVICES array the portal no longer has and refused
    to run. It now reads services.json, as the portal does, and what it would write is exactly
    what each page carries, so a run cannot take the brand back out."""
    gen = _generator()
    assert len(gen.AI_SERVICES) >= 20, "the generator read too few services from services.json"
    page = _page(name)
    block = page[page.index(gen.START):page.index(gen.END) + len(gen.END)]
    assert block == gen._markup(gen.PAGES[name]).rstrip("\n")
    assert "var(--brand-fill,var(--brand))" in block


def _contrast(fg, bg):
    def lum(h):
        h = h.lstrip("#")
        def f(v):
            v = int(v, 16) / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = f(h[0:2]), f(h[2:4]), f(h[4:6])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize("name", ("sdi-intelligence-portal.html", "sdi-estimating-intelligence.html",
                                  "sdi-estimating-guide.html"))
def test_a_light_mode_warning_reads_on_the_page_and_on_a_panel(name):
    """The light amber (#a9701a) was 3.8:1 on the page ground and 4.2:1 on white, under the
    4.5:1 small text needs, and the estimating page writes its field warnings in 11 px. The same
    hue, darker, clears both and stays apart from the brand's mustard."""
    page = _page(name)
    light = page[page.index(':root[data-theme="light"]{'):]
    light = light[:light.index("}")]
    warn = re.search(r"--warn:(#[0-9a-fA-F]{6})", light).group(1)
    bg = re.search(r"--bg:(#[0-9a-fA-F]{6})", light).group(1)
    assert _contrast(warn, bg) >= 4.5 and _contrast(warn, "#ffffff") >= 4.5, warn
    assert warn.lower() != "#7a6300", "a warning must not look like the brand"
