"""Profile customization (/customize) and team banners (/team banner).

- Bio and showcase (3 achievements shown first) are free.
- Colors: the 16 Minecraft dye colors, bought once each (`color_price`), or any
  #hex color once `hex_price` is paid. The default color is free.
- Frames (the patterned border of the profile card): some are sold
  (`frame_prices`), the rarest are earned (tournament, dungeon, gate bosses...).
- Titles are earned by playing (see TITLES); the staff can also give a custom one.
- Team banners, like Minecraft banners: a base color and up to 3 patterns, each
  with its color. The leader changes it for `banner_cost` emeralds.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from game import players, progress, settings, teams
from game.db import Ctx
from game.errors import GameError

# The 16 Minecraft dye colors (name, RGB).
DYES: dict[str, tuple[str, tuple[int, int, int]]] = {
    "white": ("White", (233, 236, 236)), "orange": ("Orange", (240, 118, 19)),
    "magenta": ("Magenta", (189, 68, 179)), "light_blue": ("Light Blue", (58, 175, 217)),
    "yellow": ("Yellow", (248, 197, 39)), "lime": ("Lime", (112, 185, 25)),
    "pink": ("Pink", (237, 141, 172)), "gray": ("Gray", (62, 68, 71)),
    "light_gray": ("Light Gray", (142, 142, 134)), "cyan": ("Cyan", (21, 137, 145)),
    "purple": ("Purple", (121, 42, 172)), "blue": ("Blue", (53, 57, 157)),
    "brown": ("Brown", (114, 71, 40)), "green": ("Green", (84, 109, 27)),
    "red": ("Red", (161, 39, 34)), "black": ("Black", (20, 21, 25)),
}
DEFAULT_COLOR = (88, 101, 242)  # Discord blurple, free
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _goal(kind: str, key: str) -> int:
    return int(settings.get()["profiles"][f"{kind}_goals"][key])


def _plural(n: int, one: str, many: str) -> str:
    """'1 block', '5 blocks'; a singular with its article stays as is: 'a boss'."""
    if n == 1:
        return one if one.startswith(("a ", "an ")) else f"1 {one}"
    return f"{n:,} {many}"


@dataclass(frozen=True)
class Frame:
    key: str
    name: str
    colors: tuple[tuple[int, int, int], ...]  # base, light, dark
    style: str  # how render draws the pattern: ore, bricks, stripes, checker, flames, stars
    what: str = ""  # earned frames: "stat:<name>" (the goal is in settings profiles.frame_goals); sold: ""
    text: Callable[[int], str] | None = None  # how to earn it, for a goal

    @property
    def unlock(self) -> str:
        return f"{self.what}:{_goal('frame', self.key)}" if self.what else ""

    @property
    def how(self) -> str:
        return self.text(_goal("frame", self.key)) if self.text else ""


FRAMES: dict[str, Frame] = {f.key: f for f in (
    Frame("stone", "Stone", ((125, 125, 125), (160, 160, 160), (90, 90, 90)), "ore"),
    Frame("gold", "Gold", ((230, 190, 40), (255, 236, 120), (170, 120, 20)), "bricks"),
    Frame("redstone", "Redstone", ((120, 20, 20), (230, 40, 30), (70, 10, 10)), "ore"),
    Frame("lapis", "Lapis", ((30, 60, 160), (80, 120, 230), (20, 35, 100)), "checker"),
    Frame("diamond", "Diamond", ((40, 170, 190), (120, 230, 240), (20, 100, 120)), "ore"),
    Frame("emerald", "Emerald", ((20, 160, 70), (90, 230, 130), (10, 100, 40)), "checker"),
    Frame("netherite", "Netherite", ((60, 52, 58), (110, 95, 100), (35, 30, 34)), "bricks",
          "stat:tournaments_won", lambda n: f"Win {_plural(n, 'a weekend tournament', 'weekend tournaments')}"),
    Frame("ender", "Ender", ((25, 15, 45), (190, 110, 240), (60, 30, 100)), "stars",
          "stat:pve_clears_nightmare", lambda n: f"Clear the Nightmare dungeon{'' if n == 1 else f' {n:,} times'}"),
    Frame("nether", "Nether Flames", ((120, 30, 10), (255, 160, 30), (200, 60, 10)), "flames",
          "stat:bosses_defeated", lambda n: f"Help defeat {_plural(n, 'a boss', 'bosses')}"),
    Frame("champion", "Champion", ((200, 160, 40), (255, 240, 170), (120, 80, 10)), "stripes",
          "stat:seasons_won", lambda n: f"Win {_plural(n, 'a weekly season', 'weekly seasons')}"),
)}


@dataclass(frozen=True)
class Title:
    key: str
    name: str
    what: str  # "stat:<name>", "level" or "dummy" (best dummy series); the goal is in profiles.title_goals
    text: Callable[[int], str]  # how to earn it, for a goal

    @property
    def unlock(self) -> str:
        return f"{self.what}:{_goal('title', self.key)}"

    @property
    def how(self) -> str:
        return self.text(_goal("title", self.key))


TITLES: dict[str, Title] = {t.key: t for t in (
    Title("miner", "Miner", "stat:blocks_mined", lambda n: f"Mine {_plural(n, 'block', 'blocks')}"),
    Title("quarry_master", "Quarry Master", "stat:blocks_mined", lambda n: f"Mine {_plural(n, 'block', 'blocks')}"),
    Title("bedrock_hunter", "Bedrock Hunter", "stat:bedrock_found", lambda n: f"Find {n:,} bedrock"),
    Title("blacksmith", "Blacksmith", "stat:items_crafted", lambda n: f"Craft {_plural(n, 'piece', 'pieces')} of gear"),
    Title("duelist", "Duelist", "stat:duels_won", lambda n: f"Win {_plural(n, 'duel', 'duels')}"),
    Title("gladiator", "Gladiator", "stat:duels_won", lambda n: f"Win {_plural(n, 'duel', 'duels')}"),
    Title("boss_slayer", "Boss Slayer", "stat:bosses_defeated", lambda n: f"Help defeat {_plural(n, 'a boss', 'bosses')}"),
    Title("season_champion", "Season Champion", "stat:seasons_won",
          lambda n: f"Win {_plural(n, 'a weekly season', 'weekly seasons')}"),
    Title("arena_champion", "Arena Champion", "stat:tournaments_won",
          lambda n: f"Win {_plural(n, 'a weekend tournament', 'weekend tournaments')}"),
    Title("team_champion", "Team Champion", "stat:team_seasons_won",
          lambda n: f"Win {_plural(n, 'a team season', 'team seasons')}"),
    Title("dungeon_crawler", "Dungeon Crawler", "stat:pve_clears_hard",
          lambda n: f"Clear the Hard dungeon{'' if n == 1 else f' {n:,} times'}"),
    Title("nightmare_survivor", "Nightmare Survivor", "stat:pve_clears_nightmare",
          lambda n: f"Clear the Nightmare dungeon{'' if n == 1 else f' {n:,} times'}"),
    Title("tycoon", "Tycoon", "stat:emeralds_earned", lambda n: f"Earn {_plural(n, 'emerald', 'emeralds')}"),
    Title("banker", "Banker", "stat:emeralds_lent", lambda n: f"Lend {_plural(n, 'emerald', 'emeralds')}"),
    Title("merchant", "Merchant", "stat:trades_completed", lambda n: f"Complete {_plural(n, 'trade', 'trades')}"),
    Title("heavy_hitter", "Heavy Hitter", "dummy", lambda n: f"Deal {n:,} damage in one /dummy hit series"),
    Title("veteran", "Veteran", "level", lambda n: f"Reach level {n:,}"),
    Title("legend", "Legend", "level", lambda n: f"Reach level {n:,}"),
)}

# Team banner patterns (Minecraft names), drawn by utils/profile_card.py.
PATTERNS: dict[str, str] = {
    "stripe_top": "Chief (top stripe)", "stripe_bottom": "Base (bottom stripe)",
    "stripe_left": "Pale dexter (left stripe)", "stripe_right": "Pale sinister (right stripe)",
    "stripe_center": "Pale (vertical stripe)", "stripe_middle": "Fess (horizontal stripe)",
    "straight_cross": "Cross", "cross": "Saltire (diagonal cross)", "chevron": "Chevron",
    "inverted_chevron": "Inverted chevron", "half_top": "Top half", "half_left": "Left half",
    "border": "Bordure", "circle": "Roundel", "rhombus": "Lozenge (diamond)",
    "gradient": "Gradient", "bricks": "Field masoned (bricks)", "small_stripes": "Paly (small stripes)",
    "triangle_top": "Chief indented (top triangle)", "creeper": "Creeper charge",
}
MAX_LAYERS = 3


def _cfg() -> dict:
    return settings.get()["profiles"]


# ---------------- conditions ----------------
def _met(ctx: Ctx, user_id: int, unlock: str) -> bool:
    kind, _, rest = unlock.partition(":")
    if kind == "stat":
        stat, _, n = rest.rpartition(":")
        return players.get_stat(ctx, user_id, stat) >= int(n)
    if kind == "level":
        return players.get_user(ctx, user_id)["level"] >= int(rest)
    if kind == "dummy":
        row = ctx.one("SELECT best_total FROM dummy_scores WHERE user_id=?;", (user_id,))
        return bool(row) and row["best_total"] >= float(rest)
    return False


def _owned(ctx: Ctx, user_id: int, kind: str) -> set[str]:
    return {r["key"] for r in ctx.all("SELECT key FROM profile_unlocks WHERE user_id=? AND kind=?;", (user_id, kind))}


def _grant(ctx: Ctx, user_id: int, kind: str, key: str) -> None:
    ctx.execute("INSERT OR IGNORE INTO profile_unlocks(user_id, kind, key, at) VALUES(?, ?, ?, ?);",
                (user_id, kind, key, int(ctx.now)))


def _set(ctx: Ctx, user_id: int, column: str, value) -> None:
    players.ensure_user(ctx, user_id)
    ctx.execute("INSERT OR IGNORE INTO profiles(user_id) VALUES(?);", (user_id,))
    ctx.execute(f"UPDATE profiles SET {column}=? WHERE user_id=?;", (value, user_id))


def get(ctx: Ctx, user_id: int) -> dict:
    """The player's choices: {"bio", "color", "title", "frame", "showcase"} (None when not set)."""
    row = ctx.one("SELECT * FROM profiles WHERE user_id=?;", (user_id,))
    out = {"bio": None, "color": None, "title": None, "frame": None, "showcase": []}
    if row:
        out.update({k: row[k] for k in ("bio", "color", "title", "frame")})
        out["showcase"] = json.loads(row["showcase"] or "[]")
    return out


def check_worn(ctx: Ctx, user_id: int) -> None:
    """Take off an earned title or frame whose condition isn't met anymore (after a /reset)."""
    worn = get(ctx, user_id)
    title = worn["title"]
    if title and not title.startswith("custom:") and (title not in TITLES or not _met(ctx, user_id, TITLES[title].unlock)):
        _set(ctx, user_id, "title", None)
    frame = worn["frame"]
    if frame and frames_of(ctx, user_id).get(frame) != "owned":
        _set(ctx, user_id, "frame", None)


def frames_of(ctx: Ctx, user_id: int) -> dict[str, str]:
    """frame -> "owned", "price" (can be bought) or "locked" (earned by playing)."""
    owned = _owned(ctx, user_id, "frame")
    prices = _cfg()["frame_prices"]
    out = {}
    for key, frame in FRAMES.items():
        if key in owned or (frame.unlock and _met(ctx, user_id, frame.unlock)):
            out[key] = "owned"
        elif key in prices:
            out[key] = "price"
        else:
            out[key] = "locked"
    return out


def titles_of(ctx: Ctx, user_id: int) -> list[tuple[str, str]]:
    """(value, label) of the titles the player can wear: earned ones, then the staff's."""
    out = [(t.key, t.name) for t in TITLES.values() if _met(ctx, user_id, t.unlock)]
    out += [(f"custom:{k}", k) for k in sorted(_owned(ctx, user_id, "custom_title"))]
    return out


def title_label(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("custom:"):
        return value[len("custom:"):]
    return TITLES[value].name if value in TITLES else None


def color_rgb(value: str | None) -> tuple[int, int, int]:
    if value in DYES:
        return DYES[value][1]
    m = HEX_RE.match(value or "")
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return DEFAULT_COLOR


# ---------------- choices ----------------
def set_bio(ctx: Ctx, user_id: int, text: str | None) -> str | None:
    text = " ".join((text or "").split()) or None
    if text and len(text) > int(_cfg()["bio_max"]):
        raise GameError(f"Your bio can be **{_cfg()['bio_max']}** characters at most.")
    _set(ctx, user_id, "bio", text)
    return text


def color_cost(ctx: Ctx, user_id: int, value: str) -> int:
    """What choosing this color costs now (0 if already owned or free)."""
    if value == "default":
        return 0
    if value in DYES:
        return 0 if value in _owned(ctx, user_id, "color") else int(_cfg()["color_price"])
    if HEX_RE.match(value):
        return 0 if _owned(ctx, user_id, "hex") else int(_cfg()["hex_price"])
    raise GameError("Pick a color from the list, or a code like `#ff8800`.")


def set_color(ctx: Ctx, user_id: int, value: str) -> dict:
    """Choose a color, buying it first if needed (a dye, or any #hex once unlocked)."""
    value = value.strip().lower()
    cost = color_cost(ctx, user_id, value)
    if cost:
        players.spend_emeralds(ctx, user_id, cost)
        if value in DYES:
            _grant(ctx, user_id, "color", value)
        else:
            _grant(ctx, user_id, "hex", "*")
    if HEX_RE.match(value):
        value = "#" + HEX_RE.match(value).group(1).lower()
    _set(ctx, user_id, "color", None if value == "default" else value)
    return {"color": value, "paid": cost}


def frame_cost(ctx: Ctx, user_id: int, key: str) -> int:
    if key == "none":
        return 0
    if key not in FRAMES:
        raise GameError("Unknown frame.")
    state = frames_of(ctx, user_id)[key]
    if state == "locked":
        raise GameError(f"The **{FRAMES[key].name}** frame is earned: {FRAMES[key].how}.")
    return int(_cfg()["frame_prices"][key]) if state == "price" else 0


def set_frame(ctx: Ctx, user_id: int, key: str) -> dict:
    cost = frame_cost(ctx, user_id, key)
    if cost:
        players.spend_emeralds(ctx, user_id, cost)
        _grant(ctx, user_id, "frame", key)
    _set(ctx, user_id, "frame", None if key == "none" else key)
    return {"frame": key, "paid": cost}


def set_title(ctx: Ctx, user_id: int, value: str) -> str | None:
    if value == "none":
        _set(ctx, user_id, "title", None)
        return None
    allowed = dict(titles_of(ctx, user_id))
    if value not in allowed:
        title = TITLES.get(value)
        raise GameError(f"You haven't earned **{title.name}** yet: {title.how}." if title else "Unknown title.")
    _set(ctx, user_id, "title", value)
    return allowed[value]


def set_showcase(ctx: Ctx, user_id: int, codes: list[str]) -> list[str]:
    """Up to 3 unlocked achievements shown first on the profile (empty = the latest ones)."""
    unlocked = progress.unlocked_codes(ctx, user_id)
    codes = list(dict.fromkeys(c for c in codes if c))[:3]
    missing = [c for c in codes if c not in unlocked]
    if missing:
        raise GameError("You can only show achievements you unlocked.")
    _set(ctx, user_id, "showcase", json.dumps(codes))
    return codes


# ---------------- staff ----------------
def give_title(ctx: Ctx, user_id: int, text: str) -> str:
    text = " ".join(text.split())
    if not 1 <= len(text) <= 40:
        raise GameError("A title is 1 to 40 characters.")
    _grant(ctx, user_id, "custom_title", text)
    _set(ctx, user_id, "title", f"custom:{text}")
    return text


def reset(ctx: Ctx, user_id: int, part: str) -> None:
    """Staff: clear a player's bio, title (and custom titles), or both."""
    players.ensure_user(ctx, user_id)
    if part in ("bio", "all"):
        _set(ctx, user_id, "bio", None)
    if part in ("title", "all"):
        _set(ctx, user_id, "title", None)
        ctx.execute("DELETE FROM profile_unlocks WHERE user_id=? AND kind='custom_title';", (user_id,))


# ---------------- team banners ----------------
def banner_of(ctx: Ctx, team_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM team_banners WHERE team_id=?;", (team_id,))
    if row is None:
        return None
    return {"base": row["base"], "layers": [tuple(layer) for layer in json.loads(row["layers"])]}


def check_banner(base: str, layers: list[tuple[str, str]]) -> dict:
    if base not in DYES:
        raise GameError("Unknown base color.")
    layers = [(p, c) for p, c in layers if p]
    if len(layers) > MAX_LAYERS:
        raise GameError(f"A banner has {MAX_LAYERS} patterns at most.")
    for pattern, color in layers:
        if pattern not in PATTERNS or color not in DYES:
            raise GameError("Each pattern needs a pattern and a color from the lists.")
    return {"base": base, "layers": layers}


def set_banner(ctx: Ctx, leader_id: int, base: str, layers: list[tuple[str, str]]) -> dict:
    """The leader sets their team's banner (it costs `banner_cost`)."""
    banner = check_banner(base, layers)
    team = teams.team_of(ctx, leader_id)
    if team is None or team["leader_id"] != leader_id:
        raise GameError("Only a team leader can change the team banner.")
    cost = int(_cfg()["banner_cost"])
    players.spend_emeralds(ctx, leader_id, cost)
    ctx.execute(
        """
        INSERT INTO team_banners(team_id, base, layers, updated_at) VALUES(?, ?, ?, ?)
        ON CONFLICT(team_id) DO UPDATE SET base=excluded.base, layers=excluded.layers, updated_at=excluded.updated_at;
        """,
        (team["team_id"], banner["base"], json.dumps(banner["layers"]), int(ctx.now)),
    )
    return {"team": team, "banner": banner, "paid": cost}
