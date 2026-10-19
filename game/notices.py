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
class AllChallengesCompleted:
    user_id: int
    book: str


@dataclass(frozen=True)
class ChallengeCompleted:
    user_id: int
    text: str
    reward: int
    daily: bool = False


@dataclass(frozen=True)
class LoanRepaid:
    loan_id: int
    lender_id: int
    borrower_id: int
    total: int
    auto: bool  # collected by the bot from a late borrower (not with /loan repay)


@dataclass(frozen=True)
class GuideProgress:
    user_id: int
    channel_id: int | None  # the player's guide channel (None if it was deleted)
    message_id: int | None  # its checklist message
    steps: tuple[str, ...]  # steps just done
    done: int
    total: int
    completed: bool
    reward: int  # paid now (0 if it was already paid once)


@dataclass(frozen=True)
class BountyPlaced:
    payer_id: int  # never shown publicly (only in the staff log)
    target_id: int
    amount: int
    total: int  # everything on the target's head now
    expires_at: int


@dataclass(frozen=True)
class BountyClaimed:
    hunter_id: int
    target_id: int
    amount: int
    via: str  # duel | rob | raid


@dataclass(frozen=True)
class BountyExpired:
    payer_id: int
    target_id: int
    amount: int
    refund: int
