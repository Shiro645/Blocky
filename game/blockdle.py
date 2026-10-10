"""Blockdle: guess the Minecraft block of the day (like Wordle / MCdle).

Every day one block is picked at random (and kept secret in the database).
After each guess the player sees, for 6 properties, whether the guessed block
matches the secret one: the tool to mine it, its hardness, its blast
resistance, whether it's transparent, whether it can be crafted, and the
version it was added in. For numbers and versions an arrow says if the secret
block's value is higher (newer) or lower (older). Guesses are unlimited; the
fewer guesses, the bigger the reward.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from game import players, settings
from game.blockdle_blocks import BLOCKS as _ROWS, VERSIONS
from game.db import Ctx
from game.errors import GameError

NO_REPEAT_DAYS = 60  # a block isn't picked again before this many days


@dataclass(frozen=True)
class Block:
    id: str
    name: str
    tool: str
    hardness: float  # -1 = unbreakable
    resistance: float
    transparent: bool
    craftable: bool
    version: str


BLOCKS: tuple[Block, ...] = tuple(Block(*row) for row in _ROWS)
BY_ID: dict[str, Block] = {b.id: b for b in BLOCKS}

# What is compared, in this order: (key, label).
COLUMNS = (
    ("tool", "Tool"), ("hardness", "Hardness"), ("resistance", "Blast resistance"),
    ("transparent", "Transparent"), ("craftable", "Craftable"), ("version", "Version"),
)


def find(text: str) -> Block:
    """A block from its id or its name (any case)."""
    key = text.strip().lower()
    block = BY_ID.get(key) or next((b for b in BLOCKS if b.name.lower() == key), None)
    if block is None:
        raise GameError("Unknown block. Pick one from the suggestions.")
    return block


def search(text: str, limit: int = 25) -> list[Block]:
    """Blocks for an autocomplete: names starting with the text first, then names containing it."""
    key = text.strip().lower()
    first = [b for b in BLOCKS if b.name.lower().startswith(key)]
    then = [b for b in BLOCKS if key in b.name.lower() and b not in first]
    return sorted(first, key=lambda b: b.name)[:limit] + sorted(then, key=lambda b: b.name)[: max(0, limit - len(first))]


def _number(value: float) -> float:
    return float("inf") if value < 0 else value  # unbreakable is the hardest


def compare(guess: Block, secret: Block) -> dict[str, str]:
    """For each column: "yes", "no", or for numbers and versions "higher" / "lower" (the secret's value)."""
    out = {
        "tool": "yes" if guess.tool == secret.tool else "no",
        "transparent": "yes" if guess.transparent == secret.transparent else "no",
        "craftable": "yes" if guess.craftable == secret.craftable else "no",
    }
    for key in ("hardness", "resistance"):
        g, s = _number(getattr(guess, key)), _number(getattr(secret, key))
        out[key] = "yes" if g == s else "higher" if s > g else "lower"
    g, s = VERSIONS.index(guess.version), VERSIONS.index(secret.version)
    out["version"] = "yes" if g == s else "higher" if s > g else "lower"
    return out


def value_text(block: Block, key: str) -> str:
    value = getattr(block, key)
    if key == "hardness" and value < 0:
        return "Unbreakable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def reward_for(tries: int) -> int:
    rewards = [int(r) for r in settings.get()["games"]["blockdle_rewards"]]
    return rewards[min(tries, len(rewards)) - 1] if rewards else 0


# ---------------- the day's block ----------------
def block_of_day(ctx: Ctx, day: str | None = None) -> Block:
    """The secret block of a day, picked the first time someone needs it (not one of the last 60 days)."""
    day = day or ctx.today.isoformat()
    row = ctx.one("SELECT block FROM blockdle_days WHERE day=?;", (day,))
    if row and row["block"] in BY_ID:
        return BY_ID[row["block"]]
    since = (ctx.today - timedelta(days=NO_REPEAT_DAYS)).isoformat()
    recent = {r["block"] for r in ctx.all("SELECT block FROM blockdle_days WHERE day >= ?;", (since,))}
    choices = [b for b in BLOCKS if b.id not in recent] or list(BLOCKS)
    block = ctx.rng.choice(choices)
    ctx.execute(
        "INSERT INTO blockdle_days(day, block) VALUES(?, ?) ON CONFLICT(day) DO UPDATE SET block=excluded.block;",
        (day, block.id),
    )
    return block


def state(ctx: Ctx, user_id: int) -> dict:
    """Today's guesses of a player (with the comparison of each) and whether they found it."""
    day = ctx.today.isoformat()
    secret = block_of_day(ctx, day)
    rows = ctx.all("SELECT block FROM blockdle_guesses WHERE day=? AND user_id=? ORDER BY n;", (day, user_id))
    guesses = [(BY_ID[r["block"]], compare(BY_ID[r["block"]], secret)) for r in rows if r["block"] in BY_ID]
    win = ctx.one("SELECT tries, reward FROM blockdle_wins WHERE day=? AND user_id=?;", (day, user_id))
    return {
        "day": day, "guesses": guesses, "found": win is not None,
        "tries": win["tries"] if win else len(guesses), "reward": win["reward"] if win else 0,
        "secret": secret if win else None,
        "winners": ctx.one("SELECT COUNT(*) AS n FROM blockdle_wins WHERE day=?;", (day,))["n"],
    }


def guess(ctx: Ctx, user_id: int, text: str) -> dict:
    block = find(text)
    day = ctx.today.isoformat()
    players.ensure_user(ctx, user_id)
    if ctx.one("SELECT 1 FROM blockdle_wins WHERE day=? AND user_id=?;", (day, user_id)):
        raise GameError("You already found today's block! A new one comes at midnight.")
    if ctx.one("SELECT 1 FROM blockdle_guesses WHERE day=? AND user_id=? AND block=?;", (day, user_id, block.id)):
        raise GameError(f"You already tried **{block.name}** today.")
    secret = block_of_day(ctx, day)
    n = ctx.one("SELECT COUNT(*) AS n FROM blockdle_guesses WHERE day=? AND user_id=?;", (day, user_id))["n"] + 1
    ctx.execute(
        "INSERT INTO blockdle_guesses(day, user_id, n, block, guessed_at) VALUES(?, ?, ?, ?, ?);",
        (day, user_id, n, block.id, int(ctx.now)),
    )
    players.bump_stat(ctx, user_id, "blockdle_guesses")
    if block.id == secret.id:
        reward = reward_for(n)
        ctx.execute(
            "INSERT INTO blockdle_wins(day, user_id, tries, reward, won_at) VALUES(?, ?, ?, ?, ?);",
            (day, user_id, n, reward, int(ctx.now)),
        )
        players.earn_emeralds(ctx, user_id, reward)
        players.add_xp(ctx, user_id, int(settings.get()["games"]["blockdle_xp"]))
        players.bump_stat(ctx, user_id, "blockdle_wins")
    out = state(ctx, user_id)
    out["last"] = block
    return out


def winners(ctx: Ctx, day: str | None = None, limit: int = 10) -> list[dict]:
    """Who found the block of a day: fewest guesses first, then the fastest."""
    day = day or ctx.today.isoformat()
    rows = ctx.all(
        "SELECT user_id, tries, reward, won_at FROM blockdle_wins WHERE day=? ORDER BY tries, won_at LIMIT ?;",
        (day, limit),
    )
    return [dict(r) for r in rows]


def yesterday(ctx: Ctx) -> Block | None:
    """Yesterday's block, once it can be told (None if nobody played)."""
    row = ctx.one("SELECT block FROM blockdle_days WHERE day=?;", ((ctx.today - timedelta(days=1)).isoformat(),))
    return BY_ID.get(row["block"]) if row else None
