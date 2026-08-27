"""A theme switch is only a switch if there is nothing left for it to miss.

The portal was dark-only, and not by design so much as by never having been asked. Adding a
light mode looked like writing a second palette. It was not: **two hundred and fourteen palette
values were written as literal hex inside the page** — `#6a6a72` forty-two times, `#26262b`
thirty-one, `#17171a` twenty-six — in inline `style=` attributes, in SVG fills, and in HTML that
JavaScript builds at run time. A `[data-theme="light"]` block cannot reach any of them.

WHAT THAT WOULD HAVE LOOKED LIKE, and it is worse than not shipping it: most of the page turns
light, and the two hundred-odd literals stay dark. Dark grey text on a white panel. A near-black
band across the middle of the architecture diagram. Hairlines that vanish. Not "a theme with a
few rough edges" — a page that looks broken, on the screen a director opens.

So the literals became the tokens they always should have been, and this file's job is to keep
it that way. The substitution is mechanical and easy to undo by accident: the next person who
writes `style="color:#9b9ba3"` because that is what the colour picker gave them puts one more
value beyond the switch's reach, and nothing about the dark page will look wrong.

TWO THINGS THIS FILE DELIBERATELY DOES NOT ASSERT.

It does not require the light palette to be pretty. It requires it to be COMPLETE — every token
the dark palette defines, redefined — because a missing one inherits the dark value and produces
exactly the invisible-hairline failure above.

And it does not check `prefers-color-scheme`, because there deliberately isn't one. The
estimating floor works in a dark room and half of these screens are on a wall; a page that went
light underneath somebody because their OS clock passed sunset would be worse than one that
never offered the choice. Opt-in only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PORTAL_PATH = _ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html"
_PORTAL = _PORTAL_PATH.read_text(encoding="utf-8")

_STYLE_END = _PORTAL.index("</style>")
_CSS = _PORTAL[:_STYLE_END]
_BODY = _PORTAL[_STYLE_END:]


def _tokens(selector: str) -> set:
    """The custom properties defined in one palette block."""
    at = _CSS.index(selector)
    block = _CSS[at:_CSS.index("}", at)]
    return {m.group(1) for m in re.finditer(r"(--[a-z0-9-]+)\s*:", block)}


# ── nothing is left outside the switch's reach ─────────────────────────────────

# The dark palette's own values. A literal one of these below the stylesheet is a colour the
# theme cannot change, wherever it is written.
_DARK_LITERALS = (
    "#0a0a0b", "#08080a", "#0a0a0c", "#0d0d0f", "#101013", "#121214", "#17171a",
    "#26262b", "#1e1e22", "#f0efec", "#9b9ba3", "#6a6a72",
    "#e8a33d", "#cf8c26", "#4ec97f", "#e8544f", "#6da8e8", "#a78bfa",
)


@pytest.mark.parametrize("literal", _DARK_LITERALS)
def test_no_palette_value_is_written_as_a_literal_below_the_stylesheet(literal):
    """THE ASSERTION THIS FILE EXISTS FOR. Inline styles, SVG fills and script-built HTML
    are all below `</style>`, and a hex in any of them is beyond every theme rule."""
    # `&#8629;` is an HTML entity, not a colour — the arrow on the folder breadcrumb. Ask for
    # a `#` that is not preceded by an ampersand.
    hits = re.findall(r"(?<!&)" + re.escape(literal) + r"\b", _BODY, re.I)
    assert not hits, (
        f"{literal} appears {len(hits)}x below the stylesheet. Use the token instead — a "
        f"literal here stays dark when the page goes light, and nothing about the dark page "
        f"will look wrong, so it will not be noticed until somebody switches.")


def test_the_only_bare_colours_left_are_ones_that_mean_the_same_in_both_themes():
    """Black and white are allowed and are not an oversight: `#000` is the text on an amber
    chip, which is amber on either ground. Anything else appearing here is a new leak."""
    found = {h.lower() for h in re.findall(r"(?<!&)#[0-9a-fA-F]{3,8}\b", _BODY)}
    assert found <= {"#000", "#fff", "#ffffff", "#000000"}, (
        f"new hard-coded colours below the stylesheet: {sorted(found - {'#000', '#fff'})}")


# ── the light palette is complete ──────────────────────────────────────────────

def test_no_ground_or_ink_is_written_as_an_rgba_literal():
    """THE ONE THE HEX PASS COULD NOT SEE, and it was the worst-placed of the lot.

    The sticky header's own background was `rgba(10,10,11,.82)` and the table row hover was
    `rgba(255,255,255,.015)`. Neither is a hex value, so tokenising 214 hex literals walked
    straight past both — leaving a near-black bar across the top of the light page, which is
    the first thing anybody would see, and a hover state invisible on a light ground.

    Accent washes are fine and are the reason this test looks at the CHANNELS rather than
    banning rgba outright: `rgba(232,163,61,.06)` is amber at 6% and works on either ground.
    What cannot be a literal is a colour that is nearly black or nearly white, because those
    ARE the ground and the ink.
    """
    # The palette blocks are where literal values BELONG — a token has to hold a real colour
    # somewhere, and that somewhere is the two `:root` blocks. Scanning them would flag the
    # definitions this test exists to insist on, which is the test marking its own fix wrong.
    scan = _CSS
    for block in (":root{", ':root[data-theme="light"]{'):
        at = scan.index(block)
        scan = scan[:at] + " " * (scan.index("}", at) + 1 - at) + scan[scan.index("}", at) + 1:]

    offenders = []
    for m in re.finditer(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*[\d.]+\)", scan):
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        if max(r, g, b) <= 40 or min(r, g, b) >= 215:
            line = scan[:m.start()].count("\n") + 1
            # Shadows are the exception: black at low alpha is a shadow in any theme, and a
            # shadow that flipped to white would glow rather than fall.
            context = scan[max(0, m.start() - 90):m.start()]
            if "shadow" in context.lower():
                continue
            offenders.append(f"line {line}: {m.group(0)}")
    assert not offenders, (
        "grounds and inks written as rgba() are beyond the theme switch:\n  "
        + "\n  ".join(offenders))


def test_light_redefines_every_token_dark_defines():
    """A token the light block forgets inherits the dark value — a near-black hairline on a
    white panel, which reads as a rendering fault rather than a missing line of CSS."""
    dark, light = _tokens(":root{"), _tokens(':root[data-theme="light"]{')
    colours = {t for t in dark if not t.startswith(("--r", "--mono", "--serif", "--disp", "--body"))}
    missing = colours - light
    assert not missing, f"light mode does not redefine: {', '.join(sorted(missing))}"


def test_the_aliases_are_redefined_too():
    """--acc and --good are aliases for --accent and --ok that were already in use against no
    definition once, which is how two "Done" bars rendered as empty tracks. Redefining the
    principal and forgetting the alias would reproduce that in one theme only."""
    light = _tokens(':root[data-theme="light"]{')
    assert {"--acc", "--good"} <= light


def test_the_status_colours_keep_their_meaning_in_both():
    """Amber is in progress, green is done, red is failed — on either ground. They may be
    darkened for contrast on white; they may not become a different hue, or the chips stop
    meaning what everyone reads them to mean."""
    at = _CSS.index(':root[data-theme="light"]{')
    block = _CSS[at:_CSS.index("}", at)]
    def value(tok): return re.search(rf"{tok}\s*:\s*(#[0-9a-fA-F]{{6}})", block).group(1)
    def rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    for tok, channel, name in (("--accent", 0, "amber"), ("--ok", 1, "green"),
                               ("--fail", 0, "red"), ("--info", 2, "blue")):
        r, g, b = rgb(value(tok))
        assert (r, g, b)[channel] == max(r, g, b), (
            f"{tok} in light mode is no longer recognisably {name}")


def test_the_page_says_which_way_round_it_is():
    """color-scheme is what makes form controls, scrollbars and the default focus ring come
    out the right colour instead of fighting the page."""
    assert "color-scheme:dark" in _CSS
    assert re.search(r':root\[data-theme="light"\]\{color-scheme:light\}', _CSS)


def test_light_mode_is_opt_in_and_never_automatic():
    """No prefers-color-scheme rule. The estimating floor works in a dark room, and half of
    these screens are on a wall — a page that changed underneath somebody at sunset would be
    worse than one that never offered the choice.

    Looks for the AT-RULE, not the words. The palette block explains in prose why there isn't
    one, and a plain substring search fails on that explanation — which is the exact trap
    already recorded against the credential detector and the read-only audit guard.
    """
    assert not re.search(r"@media[^{]*prefers-color-scheme", _CSS), (
        "light mode must be chosen, not inferred from the operating system")


# ── the controls exist, are peers of the user chip, and are honest ─────────────

def test_the_controls_sit_beside_the_user_chip_not_inside_it():
    """Asked for at that level because that is the level a person looks at when they want to
    change how the page treats THEM. They are preferences, not identity — so beside, not in."""
    ctl, user = _PORTAL.index('class="viewctl"'), _PORTAL.index('class="user"')
    assert ctl < user, "the view controls should precede the user chip in the header"
    between = _PORTAL[ctl:user]
    assert between.count("<div") == between.count("</div>"), (
        "the controls are nested inside the user chip rather than sitting alongside it")


@pytest.mark.parametrize("pc", [100, 125, 150, 175, 200])
def test_every_requested_size_has_a_button(pc):
    assert f'data-zoom="{pc}"' in _PORTAL


def test_the_sizes_the_buttons_offer_are_the_sizes_the_script_accepts():
    """A button the script rejects silently snaps back to 100% and looks like a dead
    control. Both lists are in this file, so they can be compared."""
    buttons = sorted(int(m) for m in re.findall(r'data-zoom="(\d+)"', _PORTAL))
    allowed = sorted(int(m) for m in
                     re.search(r"ZOOMS\s*=\s*\[([\d,\s]+)\]", _PORTAL).group(1).split(","))
    assert buttons == allowed == [100, 125, 150, 175, 200]


def test_the_size_control_survives_the_width_of_an_actual_laptop():
    """IT DID NOT, AND THIS IS WHY THE FIRST REPORT WAS "I CAN'T SEE THE RESIZING".

    The control was hidden below 1100px. A 1366-wide laptop screen at 125% Windows scaling —
    the ordinary setup — reports 1093 CSS pixels, so the control vanished on exactly the
    machine it was asked for, and looked like it had never been built.

    A breakpoint that hides a feature is a decision about who gets it. 820px is below the
    width where the sidebar itself goes, and a phone has pinch-zoom anyway.
    """
    hides = [int(m.group(1)) for m in
             re.finditer(r"@media \(max-width:(\d+)px\)\{[^}]*\.vc-zoom\{display:none", _CSS)]
    assert hides, "no rule hides the zoom control — check this test still matches the CSS"
    assert max(hides) <= 900, (
        f"the zoom control disappears below {max(hides)}px. Laptops are narrower than that "
        f"once Windows scaling is applied.")


def test_the_page_is_scaled_rather_than_the_text_alone():
    """This page is laid out in pixels — panel widths, chip heights, Gantt bars, the sidebar
    rail. Scaling the root font size grows the text and leaves all of that where it was, which
    reads as broken rather than bigger."""
    assert "root.style.zoom" in _PORTAL
    assert "fontSize" not in _PORTAL, "font-size scaling would not move the pixel layout"


def test_the_button_names_the_theme_it_will_switch_to():
    """It is a button; a button says what it will do. A sun labelled "Light" while the page is
    already light is a control that lies about pressing it."""
    assert "light ? 'Dark' : 'Light'" in _PORTAL
    assert "light ? 'Switch to dark' : 'Switch to light'" in _PORTAL


def test_both_icons_swap_with_the_label():
    """The word and the icon have to move together, or one of them is wrong half the time."""
    for rule in (':root[data-theme="light"] .vc-btn .ic-moon{display:block}',
                 ':root:not([data-theme="light"]) .vc-btn .ic-sun{display:block}'):
        assert rule in _CSS, rule


# ── remembering the choice cannot break the page ──────────────────────────────

def test_every_storage_access_is_wrapped():
    """A private window, or a policy that blocks site data, THROWS on access. A portal that
    will not render because it could not read a cosmetic preference is a bad trade — the same
    reasoning already applied to the rail toggle, and the same wrapping."""
    for m in re.finditer(r"localStorage\.(?:get|set)Item", _PORTAL):
        window = _PORTAL[max(0, m.start() - 120):m.start()]
        assert "try{" in window, (
            f"unwrapped localStorage access near: ...{_PORTAL[m.start()-60:m.start()+60]}...")


def test_the_two_preferences_are_remembered_separately():
    """Somebody who wants a bigger page does not necessarily want a lighter one. One key for
    both would tie the two choices together for no reason."""
    # Both are declared on one `const` line, so anchoring on `const` finds only the first.
    keys = set(re.findall(r"[TZ]_KEY\s*=\s*'([a-z.]+)'", _PORTAL))
    assert keys == {"sdi.view.theme", "sdi.view.zoom"}


def test_a_stored_size_that_is_not_offered_is_ignored():
    """Storage is per-browser and outlives this code. If the list of sizes ever changes, a
    remembered 133 must fall back to 100 rather than being applied."""
    assert "ZOOMS.indexOf(z)!==-1" in _PORTAL
    assert "ZOOMS.indexOf(pc)===-1 ? 100 : pc" in _PORTAL


# ── the page still parses ──────────────────────────────────────────────────────

def test_the_page_script_still_parses():
    """The substitution touched 214 values inside script-built HTML strings. A broken quote
    there takes out the whole page, not one colour."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):                              # pragma: no cover
        pytest.skip("node is not on this machine")
    blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", _PORTAL, re.S)
    assert len(blocks) == 1, f"{len(blocks)} script blocks — this check assumed one"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(blocks[0])
        path = fh.name
    out = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ── the same choice on every page a person actually opens ─────────────────────
#
# The controls went on the portal only. So 10.0.0.5:8071/estimating and /guide — the two pages
# an estimator spends the day in — stayed dark-only with no size control, and the answer to
# "can I have it lighter" depended on which page you happened to be on.
#
# These two pages carry their own stylesheet and their own token names (--bg, --panel, --line,
# --ink, --muted, --dim, --brand), so this is not the portal's palette reused; it is the same
# treatment applied to a second and third design system.

_ESTIMATING_PAGES = ("sdi-estimating-intelligence.html", "sdi-estimating-guide.html")


def _page(name: str) -> str:
    return (_ROOT / "sdi-intelligence-backend" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("page_name", _ESTIMATING_PAGES)
def test_the_estimating_pages_have_the_same_controls(page_name):
    """THE REPORT. "only appears in black and doesn't have the choice to go white or adjust
    the percentage sizes.\""""
    page = _page(page_name)
    assert 'id="theme-btn"' in page, f"{page_name} has no theme toggle"
    zooms = sorted(int(m) for m in re.findall(r'data-zoom="(\d+)"', page))
    assert zooms == [100, 125, 150, 175, 200], f"{page_name} offers {zooms}"


@pytest.mark.parametrize("page_name", _ESTIMATING_PAGES)
def test_each_page_defines_a_complete_light_palette(page_name):
    """Their tokens are NOT the portal's — --panel and --muted here, --surface and --ink-dim
    there. A light block copied from the portal would define names this page never reads and
    leave its own at their dark values, which looks like the toggle half-working."""
    page = _page(page_name)
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S))
    def tokens(sel):
        at = css.index(sel)
        return {m.group(1) for m in re.finditer(r"(--[a-z0-9-]+)\s*:", css[at:css.index("}", at)])}
    dark = {t for t in tokens(":root{")
            if not t.startswith(("--r", "--mono", "--serif", "--disp", "--body"))}
    missing = dark - tokens(':root[data-theme="light"]{')
    assert not missing, f"{page_name} light mode does not redefine: {', '.join(sorted(missing))}"


@pytest.mark.parametrize("page_name", _ESTIMATING_PAGES)
def test_no_palette_literal_survives_below_the_root_block(page_name):
    """Same audit as the portal's, on a smaller scale: 20 and 17 literals were sitting in
    these stylesheets where no [data-theme] rule could reach them."""
    page = _page(page_name)
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S))
    at = css.index(":root{")
    below = css[css.index("}", at) + 1:]
    # The light block is allowed to hold literals — that is what it is for.
    lat = below.index(':root[data-theme="light"]{')
    below = below[:lat] + below[below.index("}", lat) + 1:]
    for literal in ("#0d0d0f", "#121214", "#17171a", "#26262b", "#f0efec", "#9b9ba3",
                    "#6a6a72", "#e8a33d", "#4ec97f", "#6da8e8", "#ff6b6b"):
        assert literal not in below.lower(), (
            f"{page_name} still writes {literal} as a literal — the theme cannot reach it")


def test_all_three_pages_remember_the_choice_under_the_same_keys():
    """A preference that resets when you click from the dashboard into /estimating is not a
    preference. Three pages with three independent toggles would be worse than one page with
    a toggle, because it would look broken rather than absent."""
    keys = []
    for name in ("sdi-intelligence-portal.html",) + _ESTIMATING_PAGES:
        page = _page(name)
        keys.append(set(re.findall(r"['\"](sdi\.view\.(?:theme|zoom))['\"]", page)))
    assert keys[0] == keys[1] == keys[2] == {"sdi.view.theme", "sdi.view.zoom"}, (
        f"the three pages do not share storage keys: {keys}")


@pytest.mark.parametrize("page_name", _ESTIMATING_PAGES)
def test_storage_is_wrapped_on_the_estimating_pages_too(page_name):
    page = _page(page_name)
    for m in re.finditer(r"localStorage\.(?:get|set)Item", page):
        assert "try{" in page[max(0, m.start() - 120):m.start()], (
            f"{page_name}: unwrapped localStorage near ...{page[m.start()-50:m.start()+50]}...")


@pytest.mark.parametrize("page_name", _ESTIMATING_PAGES)
def test_light_mode_is_opt_in_here_as_well(page_name):
    assert not re.search(r"@media[^{]*prefers-color-scheme", _page(page_name)), (
        f"{page_name} infers the theme from the operating system")
