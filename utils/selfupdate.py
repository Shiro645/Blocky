"""Talking to the Blocky updater (updater/updater.py) through the shared folder.

The bot writes a request file and reads the result file; the updater, in its own
container, does the git pull and the rebuild. See the README: "Updating from Discord".
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

UPDATE_DIR = Path(os.environ.get("BLOCKY_UPDATE_DIR", "update"))
ALIVE_SECONDS = 60  # the updater writes its heartbeat every 10 s


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def updater_alive(now: float | None = None) -> bool:
    beat = _read(UPDATE_DIR / "updater.json")
    return bool(beat) and (now or time.time()) - float(beat.get("alive", 0)) < ALIVE_SECONDS


def request(action: str) -> str:
    """Ask the updater to "check" or "update". Returns the request id."""
    rid = uuid.uuid4().hex
    path = UPDATE_DIR / f"request-{rid}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"id": rid, "action": action}), encoding="utf-8")
    os.replace(tmp, path)  # the updater never sees a half-written request
    return rid


def result(rid: str) -> dict | None:
    return _read(UPDATE_DIR / f"result-{rid}.json")


def forget(rid: str) -> None:
    (UPDATE_DIR / f"result-{rid}.json").unlink(missing_ok=True)


async def wait_result(rid: str, timeout: float, step: float = 1.0) -> dict | None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = result(rid)
        if found is not None:
            return found
        await asyncio.sleep(step)
    return None
