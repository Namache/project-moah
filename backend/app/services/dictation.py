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
import time
import traceback
import wave
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import error_log
from app.core.resources import resource_path

MODEL_FILE = "ggml-base-q5_1.bin"
# "auto" lets whisper detect the language, which adds about a second; a fixed language is faster.
LANGUAGE = re.compile(r"^(auto|[a-z]{2,3})$")
# Live words: a shorter audio window makes each update about three times quicker, for clips up to
# about ten seconds. The final pass always uses the full window.
LIVE_AUDIO_CTX = 512
LIVE_MAX_SECONDS = 10
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
# A clip waits at most this long for the one before it; then it says the engine is busy instead
# of leaving the person looking at "Finishing the text…".
BUSY_WAIT_SECONDS = 45

# whisper marks sounds that are not speech like "[BLANK_AUDIO]" or "(keyboard clicking)".
_NON_SPEECH = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
_SPACES = re.compile(r"\s+")


class DictationError(Exception):
    """A clip that cannot be turned into text, with a reason a person can read."""


class Engine(Protocol):
    def transcribe(self, samples: Any, language: str, live: bool) -> tuple[str, str]: ...


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

    def transcribe(self, samples: Any, language: str, live: bool) -> tuple[str, str]:
        """The words, and the language they were in (detected when language is "auto")."""
        quick = live and len(samples) <= LIVE_MAX_SECONDS * SAMPLE_RATE
        # The binding keeps these settings between calls, so every call sets all of them.
        segments = self._model.transcribe(
            samples,
            language=language,
            no_context=True,
            initial_prompt=PROMPTS.get(language, ""),
            audio_ctx=LIVE_AUDIO_CTX if quick else 0,
            single_segment=quick,
            no_timestamps=quick,
        )
        return " ".join(segment.text for segment in segments), self._language(language)

    def _language(self, asked: str) -> str:
        if asked != "auto":
            return asked
        try:
            import _pywhispercpp as binding

            return binding.whisper_lang_str(binding.whisper_full_lang_id(self._model._ctx))
        except Exception:  # noqa: BLE001 - the detected language is only a speed hint
            return "auto"


@dataclass
class EngineReport:
    """What the speech engine did lately, for Settings and the diagnostic report. Times only,
    never words: what someone said is not kept."""

    loaded: bool = False
    load_seconds: float | None = None
    last_seconds: float | None = None
    last_audio_seconds: float | None = None
    last_finished: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    # Set while a clip is being turned into text: a time long past means the engine is stuck.
    busy_since: str | None = None
    threads: int = 0


@dataclass
class Status:
    available: bool
    reason: str | None = None
    engine: EngineReport = field(default_factory=EngineReport)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Dictation:
    """One shared speech engine for the whole app, used by one clip at a time."""

    def __init__(self, engine_factory=WhisperEngine, busy_wait: float = BUSY_WAIT_SECONDS) -> None:
        self._engine_factory = engine_factory
        self._engine: Engine | None = None
        self._lock = threading.Lock()
        self._unload_timer: threading.Timer | None = None
        self._busy_wait = busy_wait
        self._problem: str | None = None
        self.report = EngineReport(threads=max(1, min(8, (os.cpu_count() or 2) - 1)))

    def status(self) -> Status:
        if model_path() is None:
            return Status(False, reason="The speech model is not part of this build.")
        if problem := self._engine_problem():
            return Status(False, reason=problem)
        return Status(True, engine=EngineReport(**asdict(self.report)))

    def _engine_problem(self) -> str | None:
        """Why the speech engine cannot start, checked once per run. It loads the native part,
        not only the Python wrapper: a missing library (a DLL on Windows) then hides the
        microphone instead of failing on the first recording."""
        if self._problem is None:
            try:
                import pywhispercpp.model  # noqa: F401
            except Exception as error:  # noqa: BLE001 - a broken install says so instead of failing
                self._problem = self._record(_import_problem(error), traceback.format_exc())
            else:
                self._problem = ""
        return self._problem or None

    def transcribe_wav(
        self, data: bytes, language: str = "auto", live: bool = False
    ) -> tuple[str, str]:
        """The words in a clip and the language they were in. Live clips trade a little accuracy
        for speed; they are previews that the final pass replaces."""
        if not LANGUAGE.match(language):
            raise DictationError("Choose a language code such as en, or auto.")
        samples = decode_wav(data)
        if is_silent(samples):
            return "", language
        return self._run(samples, language, live)

    def _run(self, samples, language: str, live: bool) -> tuple[str, str]:
        # Waiting forever behind a stuck clip is what leaves "Finishing the text…" on screen.
        if not self._lock.acquire(timeout=self._busy_wait):
            raise self._failed(
                "The speech engine is still busy with an earlier recording. Wait a moment, or "
                "restart Project Moah if this keeps happening."
            )
        try:
            self.report.busy_since = _now()
            engine = self._load()
            started = time.monotonic()
            try:
                text, detected = engine.transcribe(samples, language, live)
            except DictationError:
                raise
            except Exception as error:  # noqa: BLE001 - say what broke, and log it
                raise self._failed(
                    f"The speech engine failed: {error}", traceback.format_exc()
                ) from error
            self.report.last_seconds = round(time.monotonic() - started, 2)
            self.report.last_audio_seconds = round(len(samples) / SAMPLE_RATE, 1)
            self.report.last_finished = _now()
            self._schedule_unload()
        finally:
            self.report.busy_since = None
            self._lock.release()
        return clean_text(text), detected

    def _record(self, message: str, detail: str = "") -> str:
        """Keep a problem for Settings and write it to the error log."""
        message = error_log.clean(message, 500)
        self.report.last_error, self.report.last_error_at = message, _now()
        error_log.write("service", f"Dictation: {message}", detail)
        return message

    def _failed(self, message: str, detail: str = "") -> DictationError:
        """A DictationError that is also kept for Settings and written to the error log."""
        return DictationError(self._record(message, detail))

    def _load(self) -> Engine:
        if self._engine is None:
            path = model_path()
            if path is None:
                raise self._failed("The speech model is not part of this build.")
            started = time.monotonic()
            try:
                self._engine = self._engine_factory(path)
            except ImportError as error:
                raise self._failed(_import_problem(error), traceback.format_exc()) from error
            except Exception as error:  # noqa: BLE001 - a model that will not load says why
                raise self._failed(
                    f"The speech model could not be loaded: {error}", traceback.format_exc()
                ) from error
            self.report.loaded = True
            self.report.load_seconds = round(time.monotonic() - started, 2)
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
            self.report.loaded = False


def _import_problem(error: Exception) -> str:
    """A build without the engine, or an engine whose native part will not load."""
    if isinstance(error, ImportError) and error.name in ("pywhispercpp", "pywhispercpp.model"):
        return "The speech engine is not part of this build."
    return f"The speech engine could not start: {error}"


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
