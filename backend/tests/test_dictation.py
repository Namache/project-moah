"""Dictation: the app sends a WAV clip to the local service and gets text back."""

import io
import math
import os
import struct
import wave
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import dictation as speech

pytestmark = pytest.mark.anyio


def wav(seconds: float = 1.0, rate: int = 16_000, channels: int = 1, loud: bool = True) -> bytes:
    frames = int(seconds * rate)
    amplitude = 8000 if loud else 0
    samples = (int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(frames))
    body = b"".join(struct.pack("<h", value) * channels for value in samples)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(body)
    return buffer.getvalue()


class FakeEngine:
    loads = 0

    def __init__(self, path: Path) -> None:
        FakeEngine.loads += 1
        self.path = path

    languages: list[str] = []
    live: list[bool] = []

    def transcribe(self, samples, language: str, live: bool) -> tuple[str, str]:
        FakeEngine.languages.append(language)
        FakeEngine.live.append(live)
        detected = "en" if language == "auto" else language
        return " [BLANK_AUDIO] The save   migration needs a test. (keyboard clicking) ", detected


@pytest.fixture
def fake_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    model = tmp_path / speech.MODEL_FILE
    model.write_bytes(b"not a real model")
    monkeypatch.setenv("PROJECT_MOAH_DICTATION_MODEL", str(model))
    FakeEngine.loads = 0
    FakeEngine.languages = []
    FakeEngine.live = []
    monkeypatch.setattr(speech, "dictation", speech.Dictation(engine_factory=FakeEngine))
    return model


async def test_status_reports_a_build_without_a_model(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROJECT_MOAH_DICTATION_MODEL", str(tmp_path / "missing.bin"))
    response = await client.get("/api/dictation/status")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "model" in response.json()["reason"]


async def test_status_and_transcription_with_the_model(
    client: AsyncClient, fake_model: Path
) -> None:
    status = (await client.get("/api/dictation/status")).json()
    assert status == {"available": True, "reason": None}

    response = await client.post(
        "/api/dictation/transcribe", content=wav(), headers={"Content-Type": "audio/wav"}
    )
    assert response.status_code == 200
    # Sound markers whisper adds for non-speech are dropped, and spacing is tidied.
    assert response.json() == {"text": "The save migration needs a test.", "language": "en"}
    assert FakeEngine.languages == ["auto"]
    assert FakeEngine.live == [False]


async def test_live_words_ask_for_the_quick_pass(client: AsyncClient, fake_model: Path) -> None:
    response = await client.post("/api/dictation/transcribe?live=true&language=ru", content=wav())
    assert response.json()["language"] == "ru"
    assert FakeEngine.live == [True]


async def test_a_chosen_language_reaches_the_engine(client: AsyncClient, fake_model: Path) -> None:
    await client.post("/api/dictation/transcribe?language=ru", content=wav())
    assert FakeEngine.languages == ["ru"]
    response = await client.post("/api/dictation/transcribe?language=r!", content=wav())
    assert response.status_code == 422


async def test_the_engine_loads_once_and_only_when_someone_dictates(
    client: AsyncClient, fake_model: Path
) -> None:
    await client.get("/api/dictation/status")
    assert FakeEngine.loads == 0
    for _ in range(2):
        await client.post("/api/dictation/transcribe", content=wav())
    assert FakeEngine.loads == 1


async def test_silence_gives_no_text_without_loading_the_engine(
    client: AsyncClient, fake_model: Path
) -> None:
    response = await client.post("/api/dictation/transcribe", content=wav(loud=False))
    assert response.json() == {"text": "", "language": "auto"}
    assert FakeEngine.loads == 0


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"", "could not be read"),
        (b"RIFF not really a wave file", "could not be read"),
        (wav(rate=44_100), "16 kHz"),
        (wav(channels=2), "mono"),
    ],
)
async def test_unreadable_recordings_say_why(
    client: AsyncClient, fake_model: Path, body: bytes, message: str
) -> None:
    response = await client.post("/api/dictation/transcribe", content=body)
    assert response.status_code == 422
    assert message in response.json()["detail"]


async def test_recordings_longer_than_five_minutes_are_refused(
    client: AsyncClient, fake_model: Path
) -> None:
    response = await client.post(
        "/api/dictation/transcribe", content=b"\0" * (speech.MAX_AUDIO_BYTES + 1)
    )
    assert response.status_code == 422
    assert "5 minutes" in response.json()["detail"]


SAMPLE = os.getenv("PROJECT_MOAH_DICTATION_SAMPLE")


@pytest.mark.skipif(
    not (SAMPLE and speech.model_path()), reason="needs the speech model and a spoken sample"
)
def test_the_real_model_turns_speech_into_text() -> None:
    """Run with PROJECT_MOAH_DICTATION_SAMPLE=<16 kHz mono WAV of speech> and the model fetched."""
    language = os.getenv("PROJECT_MOAH_DICTATION_LANGUAGE", "auto")
    text, _ = speech.Dictation().transcribe_wav(Path(SAMPLE).read_bytes(), language)
    expected = os.getenv("PROJECT_MOAH_DICTATION_EXPECT", "")
    assert text
    assert expected.lower() in text.lower()
