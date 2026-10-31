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


def paths_for(workbook: Path) -> Tuple[Path, Path]:
    """(<stem>_walkthrough.txt, <stem>_walkthrough.wav) beside the workbook."""
    workbook = Path(workbook)
    base = workbook.with_name(f"{workbook.stem}_walkthrough")
    return base.with_suffix(".txt"), base.with_suffix(".wav")


def write_walkthrough(words: str, workbook: Path, *,
                      run: Optional[Callable[..., object]] = None,
                      windows: Optional[bool] = None) -> Tuple[bool, str]:
    """Write the words and speak them to a WAV beside the workbook. (True, what was made) or
    (False, why there is no sound). `run` and `windows` exist for the tests."""
    txt, wav = paths_for(workbook)
    words = " ".join(str(words or "").split())
    if not words:
        return False, "no walkthrough words were written for this estimate"
    try:
        txt.write_text(words + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"the walkthrough words could not be written ({exc})"
    if not (os.name == "nt" if windows is None else windows):
        return False, (f"{txt.name} written; no sound, because this machine has no Windows "
                       f"speech synthesiser")
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
