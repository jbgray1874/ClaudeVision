"""
SDI Intelligence AM CRM — speech through Microsoft Azure AI Speech.

Two jobs, both optional and both off until a Speech resource is configured:

  * Speech to text. On iPhones the browser's own speech recognition stops
    when the page scrolls or the phone turns, and Chrome for iPhone may not
    offer it at all. There the page records the person itself (a 16 kHz mono
    WAV per sentence) and posts it here; this sends it to Azure's short-audio
    recognition and returns the words. Laptops and Android keep the browser's
    recognition, which works well there, unless SDI_SPEECH_STT=all.

  * Text to speech. Replies are spoken by an Azure neural voice (British
    English by default) instead of the phone's built-in voice: it sounds
    natural, and on iPhone an <audio> element unlocked by a tap plays reliably
    where the built-in speech engine is often blocked.

Audio and text pass through Azure to be processed and are not kept by this
service. Nothing is written to the tracker from here.

Configuration (.env):
    SDI_SPEECH_KEY      Speech resource key (Azure portal > the resource >
                        Keys and Endpoint > KEY 1). Secret: set with Read-Host.
    SDI_SPEECH_REGION   Its region, e.g. uksouth
    SDI_SPEECH_VOICE    Neural voice, default en-GB-SoniaNeural
    SDI_SPEECH_STT      ios (default) | all | off — who records for the server
    SDI_SPEECH_TTS      on (default) | off — server voice for replies
"""
from __future__ import annotations

import os
from typing import Optional
from xml.sax.saxutils import escape

import httpx


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


KEY = _opt("SDI_SPEECH_KEY")
REGION = _opt("SDI_SPEECH_REGION").lower().replace(" ", "")
VOICE = _opt("SDI_SPEECH_VOICE", "en-GB-SoniaNeural")
STT_MODE = _opt("SDI_SPEECH_STT", "ios").lower()
TTS_ON = _opt("SDI_SPEECH_TTS", "on").lower() not in ("off", "no", "0", "false")

MAX_AUDIO_BYTES = 2_200_000      # ~60 s of 16 kHz 16-bit mono WAV, Azure's short-audio limit
MAX_SPEAK_CHARS = 4000


def ready() -> bool:
    return bool(KEY and REGION)


def status() -> dict:
    return {"speech_ready": ready(),
            "speech_stt": STT_MODE if ready() else "off",
            "speech_tts": bool(ready() and TTS_ON),
            "speech_voice": VOICE if ready() else ""}


def _looks_like_wav(data: bytes) -> bool:
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def transcribe(audio: bytes, language: str = "en-GB") -> dict:
    """One recorded sentence (16 kHz mono 16-bit WAV) to text.

    Returns {"state": "ok", "text": ...}, {"state": "no_speech"} or an error
    payload with a plain-English "detail"."""
    if not ready():
        return {"state": "speech_off", "detail": "Server speech isn't set up (SDI_SPEECH_KEY / SDI_SPEECH_REGION)."}
    if not _looks_like_wav(audio):
        return {"state": "bad_audio", "detail": "The recording wasn't a WAV file."}
    if len(audio) > MAX_AUDIO_BYTES:
        return {"state": "too_long", "detail": "That was longer than a minute — please say it in shorter parts."}
    url = (f"https://{REGION}.stt.speech.microsoft.com/speech/recognition/conversation/"
           f"cognitiveservices/v1")
    try:
        with httpx.Client(timeout=30) as client:
            res = client.post(url, params={"language": language, "format": "simple",
                                           "profanity": "raw"},
                              headers={"Ocp-Apim-Subscription-Key": KEY,
                                       "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                                       "Accept": "application/json"},
                              content=audio)
    except httpx.HTTPError as exc:
        return {"state": "unreachable", "detail": f"Couldn't reach the speech service: {exc}"}
    if res.status_code != 200:
        return {"state": "speech_error", "status": res.status_code,
                "detail": f"The speech service refused the recording (HTTP {res.status_code})."}
    try:
        body = res.json()
    except ValueError:
        return {"state": "speech_error", "detail": "The speech service sent an unreadable reply."}
    status_ = body.get("RecognitionStatus")
    text = str(body.get("DisplayText") or "").strip()
    if status_ == "Success" and text:
        return {"state": "ok", "text": text}
    if status_ in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout", "Success"):
        return {"state": "no_speech"}
    return {"state": "speech_error", "detail": f"The speech service said: {status_ or 'no result'}."}


def synthesize(text: str) -> tuple[Optional[bytes], Optional[dict]]:
    """Text to an MP3 spoken by the configured neural voice."""
    if not (ready() and TTS_ON):
        return None, {"state": "speech_off", "detail": "Server voice isn't set up."}
    text = " ".join(str(text or "").split())[:MAX_SPEAK_CHARS]
    if not text:
        return None, {"state": "empty", "detail": "Nothing to say."}
    lang = "-".join(VOICE.split("-")[:2]) or "en-GB"
    ssml = (f"<speak version='1.0' xml:lang='{escape(lang)}'>"
            f"<voice name='{escape(VOICE)}'>{escape(text)}</voice></speak>")
    url = f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    try:
        with httpx.Client(timeout=30) as client:
            res = client.post(url, headers={"Ocp-Apim-Subscription-Key": KEY,
                                            "Content-Type": "application/ssml+xml",
                                            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                                            "User-Agent": "sdi-intelligence-am-crm"},
                              content=ssml.encode("utf-8"))
    except httpx.HTTPError as exc:
        return None, {"state": "unreachable", "detail": f"Couldn't reach the speech service: {exc}"}
    if res.status_code != 200 or not res.content:
        return None, {"state": "speech_error", "status": res.status_code,
                      "detail": f"The speech service couldn't speak that (HTTP {res.status_code})."}
    return res.content, None
