"""HTTP-shaped domain errors shared by services.

Services raise these so REST handlers and the future MCP adapter report the same
messages. Messages are written for people, not for debugging.
"""

from fastapi import HTTPException


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def invalid(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def locked(message: str) -> HTTPException:
    return HTTPException(status_code=423, detail=message)
