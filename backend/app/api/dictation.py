"""Dictation: the app sends a short WAV clip and gets the words back, all on this computer."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from app.services import dictation as speech
from app.services.errors import invalid

router = APIRouter(prefix="/api/dictation", tags=["dictation"])


@router.get("/status")
def get_status() -> dict[str, Any]:
    """Whether this build can dictate, so the app shows the microphone only when it works."""
    return asdict(speech.dictation.status())


@router.post("/transcribe")
async def transcribe(
    request: Request,
    language: Annotated[str, Query(max_length=5)] = "auto",
    live: bool = False,
) -> dict[str, str]:
    """The words in a WAV clip. live=true is for words shown while someone is still speaking:
    quicker and a little less exact. The response names the language, detected or as asked."""
    too_long = f"Recordings can be at most {speech.MAX_AUDIO_SECONDS // 60} minutes."
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > speech.MAX_AUDIO_BYTES:
        raise invalid(too_long)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > speech.MAX_AUDIO_BYTES:
            raise invalid(too_long)
    try:
        text, detected = await run_in_threadpool(
            speech.dictation.transcribe_wav, bytes(data), language, live
        )
    except speech.DictationError as error:
        raise invalid(str(error)) from error
    return {"text": text, "language": detected}
