"""Daily database backups: when to make one and which ones to keep."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

PREFIX = "economy-"
SUFFIX = ".db"


def backup_dir(database_path: str | Path) -> Path:
    return Path(database_path).resolve().parent / "backups"


def backup_path(folder: Path, day: date) -> Path:
    return folder / f"{PREFIX}{day.isoformat()}{SUFFIX}"


def existing(folder: Path) -> list[Path]:
    """Backups made by the bot, oldest first."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(f"{PREFIX}*{SUFFIX}") if p.is_file())


def due(folder: Path, now: datetime, hour: int) -> Path | None:
    """The backup file to create now, or None (already done today, or too early)."""
    if now.hour < hour:
        return None
    target = backup_path(folder, now.date())
    return None if target.exists() else target


def prune(folder: Path, keep: int) -> list[Path]:
    """Delete the oldest backups so that only `keep` remain. Returns the deleted files."""
    files = existing(folder)
    removed = files[: max(0, len(files) - max(1, keep))]
    for p in removed:
        p.unlink()
    return removed
