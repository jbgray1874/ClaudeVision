"""The estimate's walkthrough, spoken (D-609).

JG, 31 Oct 2026: after each self-running run the estimate is e-mailed "with the files
associated with the run and a voice walk through also".

    <stem>_walkthrough.txt    the words, from the covering note's own figures
    <stem>_walkthrough.wav    the same words, spoken

THE VOICE IS THE MACHINE'S OWN. Windows' speech synthesiser (System.Speech, the SAPI voices
every Windows install carries) speaks on the estimating laptop, so no word of the job leaves
the building: a customer's drawing is internal costing only, and a cloud voice would send its
figures to a third party. A British voice is used where one is installed.

SMALL ENOUGH TO E-MAIL. 16 kHz mono 16-bit is about 1.9 MB a minute; the walkthrough is about a
minute and a half. The mail service attaches anything under its 8 MB limit.

NEVER STOPS AN ESTIMATE. A machine with no speech synthesiser (any non-Windows box, a server
without the voices) writes the words and says why there is no sound; a failure is reported,
never raised, because the estimate is the deliverable and the walkthrough is a courtesy.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

AUDIO_HZ = 16000
TIMEOUT_SECONDS = 180

# Paths travel as environment variables, never inside the command: a job folder can hold
# quotes, ampersands and dollar signs that a quoted PowerShell string would mangle.
POWERSHELL_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$gb = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and "
    "$_.VoiceInfo.Culture.Name -eq 'en-GB' } | Select-Object -First 1; "
    "if ($gb) { $s.SelectVoice($gb.VoiceInfo.Name) }; "
    "$s.Rate = 0; "
    f"$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({AUDIO_HZ}, "
    "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
    "[System.Speech.AudioFormat.AudioChannel]::Mono); "
    "$s.SetOutputToWaveFile($env:SDI_WALKTHROUGH_WAV, $fmt); "
    "$s.Speak([System.IO.File]::ReadAllText($env:SDI_WALKTHROUGH_TXT)); "
    "$s.Dispose()"
)


# ── A NATURAL VOICE, OPT-IN (D-630) ─────────────────────────────────────────────────────
# JG, 2 Nov 2026: "can we do a birmingham accent ? also make it less robotic."
#
# THE HONEST PART FIRST: neither Windows' SAPI voices nor Azure's neural catalogue carries a
# Birmingham-accented English voice today, so a true Brummie cannot be promised. What CAN
# change is how natural it sounds: SDI_WALKTHROUGH_VOICE=azure speaks every walkthrough —
# the estimate's and the parity comparison's — through the AM CRM's own Azure Speech
# resource (SDI_SPEECH_KEY, SDI_SPEECH_REGION), in the neural voice SDI_SPEECH_VOICE names
# (default en-GB-SoniaNeural, the same voice the pages' Listen buttons already use), which
# is far less robotic than SAPI. If a regional voice appears in Azure's catalogue later,
# naming it in SDI_SPEECH_VOICE is the whole change.
#
# THE PRIVACY TRADE IS EXPLICIT: with this on, the walkthrough's words — job figures
# included — leave the building to be spoken, as D-622's spoken answers already do. The
# default therefore stays the machine's own voice (D-609). Azure failing falls back to the
# Windows voice; with neither, the words are still written and the estimate never stops.

def _azure_speak(words: str, wav: Path, post: Optional[Callable[[str], bytes]] = None
                 ) -> Tuple[bool, str]:
    """Speak through Azure; (True, the voice used) or (False, why not). `post` for tests."""
    key = os.getenv("SDI_SPEECH_KEY", "").strip()
    region = os.getenv("SDI_SPEECH_REGION", "").strip().lower().replace(" ", "")
    voice = os.getenv("SDI_SPEECH_VOICE", "").strip() or "en-GB-SoniaNeural"
    if not key or not region:
        return False, "SDI_SPEECH_KEY and SDI_SPEECH_REGION are not set"
    from xml.sax.saxutils import escape
    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="en-GB"><voice name="{escape(voice)}">{escape(words)}</voice></speak>')
    try:
        if post is None:
            import urllib.request
            req = urllib.request.Request(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                data=ssml.encode("utf-8"),
                headers={"Ocp-Apim-Subscription-Key": key,
                         "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
                         "User-Agent": "SDI-Intelligence"})
            with urllib.request.urlopen(req, timeout=120) as resp:   # noqa: S310
                data = resp.read()
        else:
            data = post(ssml)
        if not data or len(data) < 1000:
            return False, "Azure returned no sound"
        wav.write_bytes(data)
        return True, voice
    except Exception as exc:                                         # noqa: BLE001
        return False, f"Azure could not speak it ({type(exc).__name__})"


def paths_for(workbook: Path) -> Tuple[Path, Path]:
    """(<stem>_walkthrough.txt, <stem>_walkthrough.wav) beside the workbook."""
    workbook = Path(workbook)
    base = workbook.with_name(f"{workbook.stem}_walkthrough")
    return base.with_suffix(".txt"), base.with_suffix(".wav")


def write_walkthrough(words: str, workbook: Path, *,
                      run: Optional[Callable[..., object]] = None,
                      windows: Optional[bool] = None,
                      post: Optional[Callable[[str], bytes]] = None) -> Tuple[bool, str]:
    """Write the words and speak them to a WAV beside the workbook. (True, what was made) or
    (False, why there is no sound). `run`, `windows` and `post` exist for the tests."""
    txt, wav = paths_for(workbook)
    words = " ".join(str(words or "").split())
    if not words:
        return False, "no walkthrough words were written for this estimate"
    try:
        txt.write_text(words + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"the walkthrough words could not be written ({exc})"
    azure_said = ""
    if os.getenv("SDI_WALKTHROUGH_VOICE", "").strip().lower() == "azure":
        ok, said = _azure_speak(words, wav, post=post)
        if ok:
            return True, (f"{wav.name} ({wav.stat().st_size / 1024 / 1024:.1f} MB, the Azure "
                          f"voice {said}) and {txt.name}")
        azure_said = f"{said}; the Windows voice speaks instead. "
    if not (os.name == "nt" if windows is None else windows):
        return False, (f"{txt.name} written; no sound, because " + (azure_said or "") +
                       f"this machine has no Windows speech synthesiser")
    env = {**os.environ, "SDI_WALKTHROUGH_TXT": str(txt), "SDI_WALKTHROUGH_WAV": str(wav)}
    try:
        (run or subprocess.run)(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", POWERSHELL_SCRIPT],
            env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True)
    except Exception as exc:                                         # noqa: BLE001
        return False, f"{txt.name} written; the voice could not be made ({type(exc).__name__})"
    try:
        size = wav.stat().st_size
    except OSError:
        return False, f"{txt.name} written; the speech synthesiser produced no sound file"
    return True, f"{wav.name} ({size / 1024 / 1024:.1f} MB) and {txt.name}"
