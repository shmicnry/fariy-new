"""Opt-in live acceptance: real synthesized speech -> local Whisper on the running API."""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

PHRASE = "你好，我喜欢喝温水"


def pick_voice():
    listing = subprocess.run(
        ["say", "-v", "?"], capture_output=True, text=True, check=True
    ).stdout
    zh = [
        line.split()[0]
        for line in listing.splitlines()
        if "zh_CN" in line or "zh-CN" in line
    ]
    if not zh:
        raise SystemExit("No zh_CN voice installed; add one in System Settings")
    return "Tingting" if "Tingting" in zh else zh[0]


def main():
    base = os.getenv("FAIRY_API_BASE", "http://127.0.0.1:8010")
    token = os.getenv("FAIRY_API_TOKEN")
    if not token:
        token = (
            Path.home() / "Library/Application Support/Fairy/api-token"
        ).read_text().strip()
    c = httpx.Client(
        base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=180
    )
    status = c.get("/v2/voice/status").json()
    assert status["local_asr"], f"local ASR not configured: {status}"
    voice = pick_voice()
    with tempfile.TemporaryDirectory(prefix="fairy-whisper-") as directory:
        wav = Path(directory) / "speech.wav"
        subprocess.run(
            [
                "say", "-v", voice, "-o", str(wav),
                "--file-format=WAVE", "--data-format=LEI16@16000", PHRASE,
            ],
            check=True,
        )
        start = time.monotonic()
        r = c.post(
            "/v2/voice/transcribe",
            json={
                "audio_base64": base64.b64encode(wav.read_bytes()).decode(),
                "media_type": "audio/wav",
                "language": "zh",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        seconds = round(time.monotonic() - start, 2)
    print(
        json.dumps(
            {"step": "transcribe", "voice": voice, "text": data["text"], "seconds": seconds},
            ensure_ascii=False,
        ),
        flush=True,
    )
    assert data["provider"] == "local_whisper", data
    assert not data["cloud_used"] and not data["audio_persisted"], data
    assert "温水" in data["text"] or "溫水" in data["text"], data
    bad = c.post(
        "/v2/voice/transcribe",
        json={
            "audio_base64": base64.b64encode(b"x").decode(),
            "media_type": "audio/flac",
        },
    )
    assert bad.status_code == 415, bad.text
    report = Path(
        os.getenv("FAIRY_LIVE_REPORT", "docs/implementation/whisper-acceptance.json")
    )
    report.write_text(
        json.dumps(
            {
                "passed": True,
                "phrase": PHRASE,
                "voice": voice,
                "transcript": data["text"],
                "seconds": seconds,
                "unsupported_type_status": bad.status_code,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Live Whisper acceptance passed", flush=True)


if __name__ == "__main__":
    main()
