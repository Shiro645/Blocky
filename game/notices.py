"""Things worth telling the server about, produced by game actions.

Game functions append notices to `ctx.notices`; once the transaction is
committed, the database hands them to the bot, which announces them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelUp:
    user_id: int
    old_level: int
    new_level: int
    talent_points_gained: int


@dataclass(frozen=True)
class GearBroken:
    user_id: int
    item: str
    material: str


@dataclass(frozen=True)
class AchievementUnlocked:
    user_id: int
    code: str
    name: str
    reward: int


@dataclass(frozen=True)
class ChallengeCompleted:
    user_id: int
    text: str
    reward: int
