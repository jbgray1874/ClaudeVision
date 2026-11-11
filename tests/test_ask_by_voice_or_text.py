"""Ask by voice or by typing; always see the answer, hear it too if wanted (D-620, D-622).

JG, 1 Nov 2026: "can the prompting be by voice user only, or text only? both ways would be
ideal. summary voiced or texted back or both". The review: type or speak; show the recognised
words so job numbers can be corrected; always display the written answer and its source;
Listen / Stop with optional automatic spoken replies; speak the same saved answer; reuse the
AM CRM's speech because browser recognition alone is not consistently supported.

One script, /estimating/sdi-voice.js, does the speech for every estimating page. When it was
written it was driven in Chromium: the browser path (words into the box, nothing asked until
Ask; answer shown, Listen, automatic reading when ticked; "£421.37" read whole), the server
voice path (the CRM's /speak called, the device voice used when playback fails) and the server
recording path with Chromium's fake microphone (a 16 kHz WAV posted to the CRM's /transcribe,
the words into the box, nothing asked).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
PAGE = (BACKEND / "sdi-walkthrough.html").read_text(encoding="utf-8")
VOICE = (BACKEND / "sdi-voice.js").read_text(encoding="utf-8")
APP = (BACKEND / "app.py").read_text(encoding="utf-8")
ROUTES = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "tests"))


# ── the shared script ───────────────────────────────────────────────────────────────────

def test_one_script_serves_every_estimating_page():
    assert '@app.get("/estimating/sdi-voice.js")' in APP
    assert 'media_type="text/javascript"' in APP
    assert '<script src="/estimating/sdi-voice.js"></script>' in PAGE


def test_it_reuses_the_crm_speech_and_falls_back_to_the_browser():
    assert 'fetch("/api/voicecrm/transcribe"' in VOICE
    assert 'fetch("/api/voicecrm/speak"' in VOICE
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in VOICE
    # iPhones, and browsers with no recognition, record for the service where it is set up.
    assert 'ST.speech_stt === "ios" && (IOS || !SR)' in VOICE
    # A server voice that cannot play falls back to the device's own.
    assert 'markVoice(btn, "device", (err && err.message) || "server voice unavailable");\n        deviceVoice(text, btn);' in VOICE


def test_the_page_says_which_voice_spoke():
    """JG, 11 Nov 2026: a quiet fall-back to the device's voice sounded like a regression. The label
    beside the button says natural voice, or device voice and why."""
    assert 'if (p && p.then) return p.then(function () { markVoice(btn, "natural"); });' in VOICE
    assert 'markVoice(btn, "device", ST.speech_reason || "the service has no natural voice set up");' in VOICE
    assert 'throw new Error("server voice refused (HTTP " + r.status + ")")' in VOICE
    assert '"natural voice" : "device voice" + (why ? " (" + why + ")" : "")' in VOICE
    crm = (Path(__file__).resolve().parents[1] / "sdi-intelligence-backend" / "appportal" /
           "voice-crm.html").read_text(encoding="utf-8")
    assert "setVoice('natural')" in crm and "setVoice('device', VOICE_WHY" in crm
    assert "VOICE_WHY='server voice refused (HTTP '+r.status+')'" in crm


def test_the_recording_is_the_crm_format():
    assert "encodeWav(chunks, ctx.sampleRate, 16000)" in VOICE
    assert '"Content-Type": "audio/wav"' in VOICE


def test_figures_are_read_whole():
    assert 'replace(/([.!?])\\s+/g, "$1\\u0000")' in VOICE


def test_speech_status_names_only_the_speech_facts(api):
    er, _ = api
    body = er.speech_status()
    # D-744 adds why the neural voice is off: the voice's name, a reason, and the NAMES of any
    # missing settings. Never a key or any other value.
    assert set(body) == {"speech_ready", "speech_stt", "speech_tts", "speech_voice",
                         "speech_reason", "speech_missing"}
    assert set(body["speech_missing"]) <= {"SDI_SPEECH_KEY", "SDI_SPEECH_REGION"}
    import os
    key = os.getenv("SDI_SPEECH_KEY", "")
    assert not key or key not in str(body)


# ── the e-mail page ─────────────────────────────────────────────────────────────────────

def test_a_question_can_be_spoken_or_typed():
    assert '<button id="micBtn" type="button" class="ghost">Speak</button>' in PAGE
    assert '<textarea id="question"' in PAGE and '$("askBtn").onclick = ask;' in PAGE


def test_the_recognised_words_are_checked_before_anything_is_asked():
    """A misheard job number asked about would be answered about the wrong job."""
    listen = PAGE.split("function listen(){", 1)[1].split("\n}\n", 1)[0]
    assert "ask(" not in listen
    assert "Check it, especially any job number, then tap Ask." in listen
    assert "Never submits" in VOICE


def test_the_written_answer_and_its_source_are_always_shown():
    assert "Show the words" not in PAGE, "spoken-only no longer folds the answer away"
    assert 'src.textContent = "Source: "' in PAGE


def test_every_answer_has_listen_and_reading_aloud_is_optional_and_remembered():
    assert 'sayBtn.textContent = "Listen"' in PAGE
    assert '<input type="checkbox" id="autoRead">' in PAGE
    assert 'if($("autoRead").checked) V.speak(spoken, sayBtn);' in PAGE
    assert 'store.set("sdi.walkthrough.autoread"' in PAGE
    assert "try{ return localStorage.getItem(k); }catch(e){ return null; }" in PAGE


def test_the_same_saved_answer_is_spoken():
    assert '" From the record: " + j.recorded.join(" ")' in PAGE
    assert 'const spoken = (j.answer || "")' in PAGE


def test_the_commentary_can_be_heard():
    assert 'id="sayWords"' in PAGE and 'V.speak(w.commentary, $("sayWords"))' in PAGE


def test_the_page_says_where_spoken_questions_go():
    flat = " ".join(PAGE.split())
    assert "Speak uses SDI's speech service where it is set up, otherwise your browser's own" in flat
    assert "type anything you would not say on a call" in flat


def test_the_source_line_says_how_the_question_was_asked():
    assert '" · asked by " + (by === "voice" ? "voice" : "text")' in PAGE


from test_estimate_queue import api  # noqa: E402,F401
