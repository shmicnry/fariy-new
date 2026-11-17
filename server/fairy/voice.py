"""Local-only speech adapters; audio remains in temporary files and is never persisted."""

from __future__ import annotations

import base64
import binascii
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .service import fail


class SpeechInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)


class TranscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_base64: str = Field(min_length=1, max_length=14_000_000)
    media_type: str = Field(default="audio/webm", max_length=100)
    language: str = Field(default="zh", pattern=r"^[a-zA-Z-]{2,12}$")


class VoiceService:
    @staticmethod
    def whisper_cli():
        configured = os.getenv("FAIRY_WHISPER_CLI", "").strip()
        candidates = [
            configured,
            shutil.which("whisper-cli") or "",
            "/opt/homebrew/bin/whisper-cli",
            "/usr/local/bin/whisper-cli",
        ]
        return next(
            (Path(value) for value in candidates if value and Path(value).is_file()),
            Path(""),
        )

    def status(self):
        whisper = self.whisper_cli()
        model = Path(os.getenv("FAIRY_WHISPER_MODEL", ""))
        say = Path("/usr/bin/say")
        return {
            "local_tts": sys.platform == "darwin" and say.is_file(),
            "local_asr": whisper.is_file() and model.is_file(),
            "whisper_cli_configured": whisper.is_file(),
            "whisper_model_configured": model.is_file(),
            "audio_persisted": False,
            "cloud_used": False,
        }

    def speak(self, text):
        say = Path("/usr/bin/say")
        if sys.platform != "darwin" or not say.is_file():
            fail(503, "local_tts_unavailable")
        with tempfile.TemporaryDirectory(prefix="fairy-tts-") as directory:
            output = Path(directory) / "speech.wav"
            try:
                process = subprocess.run(
                    [
                        str(say),
                        "-o",
                        str(output),
                        "--file-format=WAVE",
                        "--data-format=LEI16@22050",
                        text,
                    ],
                    capture_output=True,
                    timeout=30,
                    check=False,
                    env={"PATH": os.defpath},
                )
            except (OSError, subprocess.TimeoutExpired):
                fail(503, "local_tts_failed")
            if process.returncode != 0 or not output.is_file():
                fail(503, "local_tts_failed")
            audio = output.read_bytes()
            if len(audio) > 8_000_000 or not audio.startswith(b"RIFF"):
                fail(503, "local_tts_invalid_output")
            return audio

    def transcribe(self, body):
        status = self.status()
        if not status["local_asr"]:
            fail(503, "local_asr_not_configured")
        suffix = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
        }.get(body.media_type.split(";", 1)[0].casefold())
        if not suffix:
            fail(415, "unsupported_audio_type")
        try:
            audio = base64.b64decode(body.audio_base64, validate=True)
        except (ValueError, binascii.Error):
            fail(422, "invalid_audio_base64")
        if not audio or len(audio) > 10_000_000:
            fail(413, "audio_too_large")
        whisper = self.whisper_cli()
        model = Path(os.getenv("FAIRY_WHISPER_MODEL", ""))
        with tempfile.TemporaryDirectory(prefix="fairy-asr-") as directory:
            audio_path = Path(directory) / ("input" + suffix)
            audio_path.write_bytes(audio)
            try:
                process = subprocess.run(
                    [
                        str(whisper),
                        "-m",
                        str(model),
                        "-f",
                        str(audio_path),
                        "-l",
                        body.language,
                        "-nt",
                        "-np",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                    env={"PATH": os.defpath},
                )
            except (OSError, subprocess.TimeoutExpired):
                fail(503, "local_asr_failed")
            if process.returncode != 0:
                fail(503, "local_asr_failed")
            text = process.stdout.strip()
            if not text:
                fail(422, "local_asr_no_speech")
            return {
                "text": text[:16000],
                "language": body.language,
                "provider": "local_whisper",
                "audio_persisted": False,
                "cloud_used": False,
            }
