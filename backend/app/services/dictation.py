"""Offline speech to text for dictating tasks and memory.

Speech never leaves the computer: the app records the microphone itself, sends the clip to this
local service, and whisper.cpp turns it into text with a multilingual model shipped inside the app.
The speech engine and its model load on the first dictation, not at startup, so agent sessions
and the MCP server start as fast as before, and they are released again after a quiet spell.
"""

import io
import os
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.resources import resource_path

MODEL_FILE = "ggml-base-q5_1.bin"
# "auto" lets whisper detect the language, which adds about a second; a fixed language is faster.
LANGUAGE = re.compile(r"^(auto|[a-z]{2,3})$")
# whisper often writes Mandarin in traditional characters; a simplified hint steers it.
PROMPTS = {"zh": "以下是普通话的句子。"}
SAMPLE_RATE = 16_000
# Five minutes of 16 kHz mono 16-bit audio, plus room for the WAV header.
MAX_AUDIO_SECONDS = 300
MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * SAMPLE_RATE * 2 + 1024
# Free the model's memory when nobody has dictated for this long.
IDLE_UNLOAD_SECONDS = 600
# Below this loudness a clip counts as silence; whisper tends to invent words for silence.
SILENCE_RMS = 0.004

# whisper marks sounds that are not speech like "[BLANK_AUDIO]" or "(keyboard clicking)".
_NON_SPEECH = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
_SPACES = re.compile(r"\s+")


class DictationError(Exception):
    """A clip that cannot be turned into text, with a reason a person can read."""


class Engine(Protocol):
    def transcribe(self, samples: Any, language: str) -> str: ...


def model_path() -> Path | None:
    """The bundled model, or a model a developer points to; None when neither exists."""
    if explicit := os.getenv("PROJECT_MOAH_DICTATION_MODEL"):
        candidates = [Path(explicit)]
    else:
        candidates = [
            resource_path(f"backend/models/{MODEL_FILE}"),
            resource_path(f"build/dictation/{MODEL_FILE}"),
        ]
    return next((path for path in candidates if path.is_file()), None)


class WhisperEngine:
    """whisper.cpp through its Python binding, loaded from a local file only."""

    def __init__(self, path: Path) -> None:
        from pywhispercpp.model import Model

        threads = max(1, min(8, (os.cpu_count() or 2) - 1))
        # A file path, never a model name: a name would make the binding download it.
        self._model = Model(
            str(path),
            n_threads=threads,
            print_progress=False,
            print_realtime=False,
            redirect_whispercpp_logs_to=None,
        )

    def transcribe(self, samples: Any, language: str) -> str:
        segments = self._model.transcribe(
            samples, language=language, no_context=True, initial_prompt=PROMPTS.get(language, "")
        )
        return " ".join(segment.text for segment in segments)


@dataclass
class Status:
    available: bool
    reason: str | None = None


class Dictation:
    """One shared speech engine for the whole app, used by one clip at a time."""

    def __init__(self, engine_factory=WhisperEngine) -> None:
        self._engine_factory = engine_factory
        self._engine: Engine | None = None
        self._lock = threading.Lock()
        self._unload_timer: threading.Timer | None = None

    def status(self) -> Status:
        if model_path() is None:
            return Status(False, reason="The speech model is not part of this build.")
        try:
            import pywhispercpp  # noqa: F401
        except ImportError:
            return Status(False, reason="The speech engine is not part of this build.")
        return Status(True)

    def transcribe_wav(self, data: bytes, language: str = "auto") -> str:
        if not LANGUAGE.match(language):
            raise DictationError("Choose a language code such as en, or auto.")
        samples = decode_wav(data)
        if is_silent(samples):
            return ""
        with self._lock:
            engine = self._load()
            text = engine.transcribe(samples, language)
            self._schedule_unload()
        return clean_text(text)

    def _load(self) -> Engine:
        if self._engine is None:
            path = model_path()
            if path is None:
                raise DictationError("The speech model is not part of this build.")
            try:
                self._engine = self._engine_factory(path)
            except ImportError as error:
                raise DictationError("The speech engine is not part of this build.") from error
        return self._engine

    def _schedule_unload(self) -> None:
        if self._unload_timer is not None:
            self._unload_timer.cancel()
        self._unload_timer = threading.Timer(IDLE_UNLOAD_SECONDS, self._unload)
        self._unload_timer.daemon = True
        self._unload_timer.start()

    def _unload(self) -> None:
        with self._lock:
            self._engine = None
            self._unload_timer = None


def decode_wav(data: bytes):
    """16 kHz mono 16-bit PCM WAV, as the app records it, to float samples for whisper."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as clip:
            if clip.getnchannels() != 1 or clip.getsampwidth() != 2:
                raise DictationError("Send mono 16-bit audio.")
            if clip.getframerate() != SAMPLE_RATE:
                raise DictationError("Send audio recorded at 16 kHz.")
            frames = clip.readframes(clip.getnframes())
    except (wave.Error, EOFError) as error:
        raise DictationError("The recording could not be read.") from error
    if not frames:
        raise DictationError("The recording is empty.")
    if len(frames) // 2 > MAX_AUDIO_SECONDS * SAMPLE_RATE:
        raise DictationError(f"Recordings can be at most {MAX_AUDIO_SECONDS // 60} minutes.")
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def is_silent(samples) -> bool:
    import numpy as np

    return float(np.sqrt(np.mean(np.square(samples)))) < SILENCE_RMS


def clean_text(text: str) -> str:
    return _SPACES.sub(" ", _NON_SPEECH.sub(" ", text)).strip()


dictation = Dictation()
