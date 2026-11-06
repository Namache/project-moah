"""Download the multilingual speech model that desktop builds ship for offline dictation.

This runs at build time only. The app itself never downloads anything: the model goes into the
installer, and dictation works without an internet connection from the first click.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

MODEL_FILE = "ggml-base-q5_1.bin"
URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{MODEL_FILE}"
SHA256 = "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    target = Path(__file__).resolve().parents[1] / "build/dictation" / MODEL_FILE
    if target.is_file() and sha256(target) == SHA256:
        print(f"Speech model already present: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    print(f"Downloading the speech model (about 57 MB) from {URL}")
    with (
        urllib.request.urlopen(URL, timeout=60) as response,
        partial.open("wb") as file,
    ):
        while block := response.read(1 << 20):
            file.write(block)
    if (actual := sha256(partial)) != SHA256:
        partial.unlink()
        print(
            f"The speech model's checksum is wrong ({actual}); nothing was kept.",
            file=sys.stderr,
        )
        return 1
    partial.replace(target)
    print(f"Speech model saved: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
