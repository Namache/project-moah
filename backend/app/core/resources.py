"""Locate files shipped beside the source or inside a frozen desktop executable."""

import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    """Resolve a repository resource from source or PyInstaller's extraction directory."""
    if bundle_root := getattr(sys, "_MEIPASS", None):
        return Path(bundle_root) / relative_path
    return Path(__file__).resolve().parents[3] / relative_path
