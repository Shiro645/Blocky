"""Database backups: the nightly ones and the ones staff ask for, and which ones to keep.

Nightly: economy-YYYY-MM-DD.db. Manual (/backup_now): manual-YYYY-MM-DD-HHMMSS.db.
Each kind is pruned on its own, so manual copies never push nightly ones out.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

PREFIX = "economy-"
MANUAL_PREFIX = "manual-"
SUFFIX = ".db"
_NIGHTLY = re.compile(r"^economy-\d{4}-\d{2}-\d{2}\.db$")
_MANUAL = re.compile(r"^manual-\d{4}-\d{2}-\d{2}-\d{6}\.db$")


def backup_dir(database_path: str | Path) -> Path:
    return Path(database_path).resolve().parent / "backups"


def backup_path(folder: Path, day: date) -> Path:
    return folder / f"{PREFIX}{day.isoformat()}{SUFFIX}"


def manual_path(folder: Path, now: datetime) -> Path:
    return folder / f"{MANUAL_PREFIX}{now:%Y-%m-%d-%H%M%S}{SUFFIX}"


def existing(folder: Path, manual: bool = False) -> list[Path]:
    """Nightly (or manual) backups, oldest first."""
    if not folder.is_dir():
        return []
    pattern = _MANUAL if manual else _NIGHTLY
    return sorted(p for p in folder.iterdir() if p.is_file() and pattern.match(p.name))


def due(folder: Path, now: datetime, hour: int) -> Path | None:
    """The backup file to create now, or None (already done today, or too early)."""
    if now.hour < hour:
        return None
    target = backup_path(folder, now.date())
    return None if target.exists() else target


def prune(folder: Path, keep: int, manual: bool = False) -> list[Path]:
    """Delete the oldest nightly (or manual) backups so that only `keep` remain. Returns the deleted files."""
    files = existing(folder, manual)
    removed = files[: max(0, len(files) - max(1, keep))]
    for p in removed:
        p.unlink()
    return removed
