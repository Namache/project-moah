"""Claude's token factor, measured from Claude Code's own logs on this computer.

Claude's tokenizer is not public, and it changes between models, so services/tokens.py counts
Claude tokens as a local o200k estimate times a factor. Each context pack Claude Code fetched is
a measurement: its log shows how much the next request grew (services/usage.PackSample). The
factor is the median of real / estimated over the latest model's packs, so one odd pack moves
it little. It replaces the fixed 1.2 once ``MIN_PACKS`` packs were measured, and is stored so the
MCP server, a separate process, sizes packs with it too. Nothing leaves the computer.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import median

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.services.tokens import PROVIDER_FACTOR, use_measured
from app.services.usage import PackSample

KEY = "claude_token_factor"
MIN_PACKS = 5
MIN_TOKENS = 60  # smaller packs are mostly the tool result's own wrapping
LOWEST, HIGHEST = 0.8, 3.0
TARGET_ERROR = 0.10


def _error(estimates: list[float], actual: list[int]) -> float:
    """Median of |estimate - actual| / actual."""
    return median(abs(e - a) / a for e, a in zip(estimates, actual, strict=True))


def measure(samples: list[PackSample], fixed: float = PROVIDER_FACTOR["claude"]) -> dict:
    """Per Claude model: packs measured, the factor they give, and how far estimates are off
    with the fixed factor and with the measured one (each pack checked against a factor from
    the other packs, so a pack never grades itself)."""
    usable = [s for s in samples if s.estimate_base >= MIN_TOKENS and s.actual > 0]
    models: dict[str, list[PackSample]] = defaultdict(list)
    for sample in usable:
        models[sample.model or "unknown"].append(sample)
    rows = []
    for model, items in models.items():
        ratios = [s.actual / s.estimate_base for s in items]
        actual = [s.actual for s in items]
        row = {
            "model": model,
            "packs": len(items),
            "factor": round(median(ratios), 3),
            "estimated_tokens": round(sum(s.estimate_base * fixed for s in items)),
            "actual_tokens": sum(actual),
            "error_fixed": round(_error([s.estimate_base * fixed for s in items], actual), 3),
            "error_measured": None,
            "last_at": max(s.at for s in items).isoformat(),
        }
        if len(items) >= 2:
            held_out = [
                items[i].estimate_base * median(ratios[:i] + ratios[i + 1 :])
                for i in range(len(items))
            ]
            row["error_measured"] = round(_error(held_out, actual), 3)
        rows.append(row)
    rows.sort(key=lambda r: r["last_at"], reverse=True)
    current = next((r for r in rows if r["packs"] >= MIN_PACKS), None)
    return {
        "fixed_factor": fixed,
        "min_packs": MIN_PACKS,
        "target_error": TARGET_ERROR,
        "models": rows,
        "in_use": (
            {"model": current["model"], "factor": _clamp(current["factor"])} if current else None
        ),
    }


def _clamp(value: float) -> float:
    return round(min(HIGHEST, max(LOWEST, value)), 3)


def save(session: Session, measured: dict) -> None:
    """Store the factor in use when it changed, and use it in this process."""
    in_use = measured.get("in_use")
    if not in_use:
        return
    row = session.get(AppSetting, KEY)
    stored = row.value if row is not None and isinstance(row.value, dict) else {}
    if (
        stored.get("model") == in_use["model"]
        and isinstance(stored.get("factor"), int | float)
        and math.isclose(stored["factor"], in_use["factor"], abs_tol=0.005)
    ):
        use_measured("claude", float(stored["factor"]))
        return
    row = row or AppSetting(key=KEY)
    row.value = {
        **in_use,
        "packs": next((r["packs"] for r in measured["models"] if r["model"] == in_use["model"]), 0),
    }
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    use_measured("claude", in_use["factor"])


def load(session: Session) -> float | None:
    """Use the stored factor, if there is one. Called before a pack is sized."""
    row = session.get(AppSetting, KEY)
    value = row.value.get("factor") if row is not None and isinstance(row.value, dict) else None
    if isinstance(value, int | float) and LOWEST <= value <= HIGHEST:
        use_measured("claude", float(value))
        return float(value)
    use_measured("claude", None)
    return None
