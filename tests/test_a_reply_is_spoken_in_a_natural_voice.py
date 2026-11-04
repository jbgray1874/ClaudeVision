"""A reply is spoken in a natural voice, and said the way a person would say it (D-673).

JG, 4 Nov 2026: "can we improve the voice readback also on the web app? the phone is pretty
good but the app is very robotic and mispronounces some words."

Three causes, each tested here:
  * the estimating pages asked the AM CRM's /api/voicecrm/speak, which needs a signed-in CRM
    user; the e-mail page and the desk page on the estimating laptop have none, so the device
    voice read every answer. /api/estimate/speak is the same voice behind the estimating gate;
  * the device voice taken was the first UK voice installed, on Windows the old desktop voice,
    and the list was often still empty on first use. Voices are now ranked and waited for;
  * the text was read as written: "£185.96", "375 x 270", "10.8mm", "12203-65-01J", "MDF".
    forSpeech puts it into its spoken form for every voice; the screen keeps the words.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
VOICE_JS = BACKEND / "sdi-voice.js"
sys.path.insert(0, str(ROOT / "tests"))

from test_estimate_queue import api  # noqa: E402,F401

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed here")


def _node(body: str, voices=None, stored: str = ""):
    """Run sdi-voice.js in node with a stub window, then `body`; returns its JSON print."""
    prelude = f"""
global.navigator = {{userAgent: "", platform: ""}};
const VOICES = {json.dumps(voices or [])};
const store = {{"sdi.voice": {json.dumps(stored)}}};
global.localStorage = {{getItem: k => store[k] || null, setItem: (k, v) => {{ store[k] = v; }},
                        removeItem: k => {{ delete store[k]; }}}};
global.window = {{speechSynthesis: {{getVoices: () => VOICES, addEventListener: () => {{}}}}}};
require({json.dumps(str(VOICE_JS))});
const V = window.SDIVoice;
"""
    out = subprocess.run([NODE, "-e", prelude + body], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _say(text: str) -> str:
    return _node(f"console.log(JSON.stringify(V.forSpeech({json.dumps(text)})));")


# ── said the way a person says it ─────────────────────────────────────────────────────

@needs_node
@pytest.mark.parametrize("text, said", [
    ("£185.96 a unit", "185 pounds 96 a unit"),
    ("£0.35 each", "35 pence each"),
    ("£1,579.20 the order", "1,579 pounds 20 the order"),
    ("£55 set-up", "55 pounds set-up"),
    ("375 x 270 x 10.8mm", "375 by 270 by 10.8 millimetres"),
    ("3 x 15 min set-ups", "3 times 15 minutes set-ups"),
    ("bumpons x4", "bumpons times 4"),
    ("12 parts/hr, 0.33 h", "12 parts per hour, 0.33 hours"),
    ("£25.37/m²", "25 pounds 37 per square metre"),
    ("board £/kg", "board pounds per kilogram"),
    ("13,465 mm2", "13,465 square millimetres"),
    ("1.94 kg, 45° bevel", "1.94 kilograms, 45 degrees bevel"),
    ("12203-65-01J", "one two two oh three, six five, oh one J"),
    ("12203-66-GA", "one two two oh three, six six, G A"),
    ("D4428OV", "D four four two eight O V"),
    ("FIXING405", "fixing four oh five"),
    ("drawing 0355452", "drawing oh three five five four five two"),
    ("MDF and CNC", "M D F and C N C"),
    ("NOT priced", "NOT priced"),
    ("1-2 days", "1 to 2 days"),
    ("ex VAT · indicative", "ex VAT, indicative"),
])
def test_the_text_is_put_into_its_spoken_form(text, said):
    assert _say(text) == said


# ── the voice ─────────────────────────────────────────────────────────────────────────

WINDOWS_EDGE = [
    {"name": "Microsoft Hazel - English (United Kingdom)", "lang": "en-GB", "localService": True,
     "default": True},
    {"name": "Microsoft George - English (United Kingdom)", "lang": "en-GB", "localService": True},
    {"name": "Microsoft David - English (United States)", "lang": "en-US", "localService": True},
    {"name": "Microsoft Sonia Online (Natural) - English (United Kingdom)", "lang": "en-GB",
     "localService": False},
    {"name": "Microsoft Denise Online (Natural) - French (France)", "lang": "fr-FR",
     "localService": False},
]
WINDOWS_CHROME = [
    {"name": "Microsoft Hazel - English (United Kingdom)", "lang": "en-GB", "localService": True,
     "default": True},
    {"name": "Google US English", "lang": "en-US", "localService": False},
    {"name": "Google UK English Female", "lang": "en-GB", "localService": False},
]
IPHONE = [
    {"name": "Daniel", "lang": "en-GB", "localService": True, "default": True},
    {"name": "Kate (Enhanced)", "lang": "en-GB", "localService": True},
    {"name": "Bad News", "lang": "en-US", "localService": True},
]


def _best(voices, stored=""):
    return _node("console.log(JSON.stringify((V.bestVoice() || {}).name || ''));", voices, stored)


@needs_node
def test_edge_on_windows_speaks_in_its_natural_voice_not_the_desktop_one():
    assert _best(WINDOWS_EDGE) == "Microsoft Sonia Online (Natural) - English (United Kingdom)"


@needs_node
def test_chrome_on_windows_speaks_in_googles_uk_voice():
    assert _best(WINDOWS_CHROME) == "Google UK English Female"


@needs_node
def test_an_iphone_takes_its_enhanced_voice():
    assert _best(IPHONE) == "Kate (Enhanced)"


@needs_node
def test_a_persons_own_choice_is_kept_on_the_device():
    assert _best(WINDOWS_EDGE, stored="Microsoft George - English (United Kingdom)") == \
        "Microsoft George - English (United Kingdom)"


@needs_node
def test_a_voice_not_in_english_is_never_chosen():
    got = _node("console.log(JSON.stringify(V.voices().map(v => v.lang)));", WINDOWS_EDGE)
    assert "fr-FR" not in got


def test_the_device_voice_waits_for_the_list_and_reads_the_spoken_form():
    js = VOICE_JS.read_text(encoding="utf-8")
    assert 'SYNTH.addEventListener("voiceschanged", loadVoices)' in js
    assert "var parts = sentences(forSpeech(text));" in js
    assert "var v = bestVoice();" in js
    assert "localService) v = all[i]" not in js, "the installed-first rule is gone"


# ── the neural voice behind the estimating gate ───────────────────────────────────────

def test_the_estimating_pages_ask_their_own_route_first_then_the_crms():
    js = VOICE_JS.read_text(encoding="utf-8")
    first = js.index('fetch("/api/estimate/speak"')
    assert first < js.index('fetch("/api/voicecrm/speak"')
    assert 'keyed["X-SDI-Key"] = KEY' in js
    page = (BACKEND / "sdi-walkthrough.html").read_text(encoding="utf-8")
    assert "V.useKey(API_KEY)" in page


def test_the_route_speaks_in_the_configured_voice(api, monkeypatch):
    er, _ = api
    import voicecrm_speech
    monkeypatch.setattr(voicecrm_speech, "synthesize", lambda text: (b"ID3-mp3", None))
    res = er.speech_speak(er.SpeakRequest(text="185 pounds 96"), x_sdi_key=None)
    assert res.media_type == "audio/mpeg" and res.body == b"ID3-mp3"


def test_the_route_says_when_there_is_no_server_voice(api, monkeypatch):
    er, _ = api
    import voicecrm_speech
    monkeypatch.setattr(voicecrm_speech, "synthesize",
                        lambda text: (None, {"state": "speech_off", "detail": "off"}))
    res = er.speech_speak(er.SpeakRequest(text="x"), x_sdi_key=None)
    assert res.status_code == 503


def test_the_route_is_behind_the_estimating_gate(api, monkeypatch):
    er, _ = api
    monkeypatch.setattr(er.config, "API_KEY", "secret", raising=False)
    with pytest.raises(er.HTTPException):
        er.speech_speak(er.SpeakRequest(text="x"), x_sdi_key="wrong")


# ── the CRM page shares the voice choice and the spoken form ──────────────────────────

def test_the_crm_page_uses_the_shared_voice_choice():
    page = (BACKEND / "appportal" / "voice-crm.html").read_text(encoding="utf-8")
    assert '<script src="/estimating/sdi-voice.js"></script>' in page
    assert "const best=SV&&SV.bestVoice(); if(best){ u.voice=best; u.lang=best.lang; }" in page
    assert "window.SDIVoice?window.SDIVoice.forSpeech(text):text" in page
