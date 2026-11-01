"""Ask by voice or by typing; hear the answer, read it, or both (D-620).

JG, 1 Nov 2026: "can the prompting be by voice user only, or text only? both ways would be
ideal. summary voiced or texted back or both".

The walkthrough page uses the browser's own speech services. These checks hold the page to the
choices it offers; the flow itself was driven in Chromium with a stand-in microphone and speech
engine when it was written (spoken question asked, answer read sentence by sentence with
"£421.37" read whole, spoken-only folds the words away, text-only reads nothing).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-walkthrough.html").read_text(encoding="utf-8")


def test_a_question_can_be_spoken_or_typed():
    assert '<button id="micBtn" type="button" class="ghost">Speak</button>' in PAGE
    assert '<textarea id="question"' in PAGE and '$("askBtn").onclick = () => ask("text");' in PAGE
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in PAGE
    assert 'rec.lang = "en-GB"' in PAGE
    assert 'ask("voice")' in PAGE, "a spoken question is asked when the speaker stops"


def test_a_browser_without_recognition_says_what_to_do_instead():
    assert "This browser cannot take a spoken question" in PAGE
    assert "key on the keyboard types what you say into the box; then tap Ask." in PAGE
    assert "The microphone is blocked for this page" in PAGE


def test_answers_come_back_as_text_spoken_or_both_and_the_choice_is_remembered():
    for value in ("auto", "text", "voice", "both"):
        assert f'<input type="radio" name="reply" value="{value}">' in PAGE
    assert 'store.set("sdi.walkthrough.reply", replyMode)' in PAGE
    assert 'return askedBy === "voice" ? "both" : "text";' in PAGE, \
        "left on 'the way I asked', a spoken question is answered aloud and on screen"
    # Browser storage may be refused; the page must still work.
    assert "try{ return localStorage.getItem(k); }catch(e){ return null; }" in PAGE


def test_spoken_only_folds_the_words_away_rather_than_dropping_them():
    assert '<summary>Show the words</summary>' in PAGE
    assert 'if(mode === "voice" && SYNTH)' in PAGE


def test_the_record_figures_are_read_after_the_answer_and_figures_stay_whole():
    assert '" From the record: " + j.recorded.join(" ")' in PAGE
    assert 'replace(/([.!?])\\s+/g, "$1\\u0000")' in PAGE, \
        "a sentence ends at a stop followed by a space, so £421.37 is one figure"


def test_every_answer_and_the_commentary_can_be_read_aloud_and_stopped():
    assert 'sayBtn.textContent = "Read aloud"' in PAGE
    assert 'id="sayWords"' in PAGE and "say(w.commentary, $(\"sayWords\"))" in PAGE
    assert 'btn.textContent = "Stop"' in PAGE and "SYNTH.cancel()" in PAGE


def test_the_page_says_where_spoken_questions_go():
    flat = " ".join(PAGE.split())
    assert "Speak uses your browser's own speech service" in flat
    assert "type the question instead for anything you would not say on a call" in flat


def test_the_source_line_says_how_the_question_was_asked():
    assert '" · asked by " + (askedBy === "voice" ? "voice" : "text")' in PAGE
