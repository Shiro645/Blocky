"""Async access to the SQLite database.

All queries run on one dedicated thread, so the bot's event loop never
blocks. Each `Database.run(fn, ...)` call executes `fn(ctx, ...)` inside a
single transaction: either everything it does is saved, or nothing is.
Because there is only one database thread, two actions can never interleave
(no double spending between "check balance" and "debit").
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from zoneinfo import ZoneInfo

from game import settings

log = logging.getLogger("db")

T = TypeVar("T")

# Each entry upgrades the schema by one version. Never edit an entry that
# has shipped: append a new one instead.
MIGRATIONS: list[str] = [
    # 1 - core economy
    """
    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        emeralds INTEGER NOT NULL DEFAULT 0 CHECK (emeralds >= 0),
        xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
        level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1),
        talent_points INTEGER NOT NULL DEFAULT 0 CHECK (talent_points >= 0),
        miner_points INTEGER NOT NULL DEFAULT 0 CHECK (miner_points >= 0),
        trader_points INTEGER NOT NULL DEFAULT 0 CHECK (trader_points >= 0),
        lucky_points INTEGER NOT NULL DEFAULT 0 CHECK (lucky_points >= 0),
        efficiency_points INTEGER NOT NULL DEFAULT 0 CHECK (efficiency_points >= 0),
        created_at INTEGER NOT NULL
    );
    CREATE TABLE blocks (
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        block_type TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
        PRIMARY KEY (user_id, block_type)
    );
    -- stackable resources: sticks (material 'none') and ingots
    CREATE TABLE items (
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        item TEXT NOT NULL,
        material TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
        PRIMARY KEY (user_id, item, material)
    );
    CREATE TABLE gear (
        gear_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        item TEXT NOT NULL,
        material TEXT NOT NULL,
        durability INTEGER NOT NULL CHECK (durability >= 0),
        max_durability INTEGER NOT NULL,
        equipped INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX idx_gear_user ON gear(user_id);
    -- one equipped piece per slot (the slot is the item type)
    CREATE UNIQUE INDEX idx_gear_equipped ON gear(user_id, item) WHERE equipped = 1;
    CREATE TABLE stats (
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        stat TEXT NOT NULL,
        value INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, stat)
    );
    CREATE INDEX idx_stats_stat ON stats(stat, value);
    """,
    # 2 - daily rewards and auction house
    """
    ALTER TABLE users ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN last_daily TEXT;
    CREATE TABLE auctions (
        auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        asset TEXT NOT NULL,          -- see game/assets.py
        amount INTEGER NOT NULL CHECK (amount > 0),
        durability INTEGER,           -- gear only
        max_durability INTEGER,       -- gear only
        price INTEGER NOT NULL CHECK (price > 0),
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE INDEX idx_auctions_seller ON auctions(seller_id);
    CREATE INDEX idx_auctions_expires ON auctions(expires_at);
    """,
    # 3 - weekly seasons
    """
    CREATE TABLE season_scores (
        season_id TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        score INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (season_id, user_id)
    );
    CREATE INDEX idx_season_scores ON season_scores(season_id, score);
    CREATE TABLE seasons_closed (
        season_id TEXT PRIMARY KEY,
        closed_at INTEGER NOT NULL
    );
    CREATE TABLE season_results (
        season_id TEXT NOT NULL,
        rank INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        reward INTEGER NOT NULL,
        PRIMARY KEY (season_id, rank)
    );
    """,
    # 4 - achievements and weekly challenges
    """
    CREATE TABLE achievements (
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        unlocked_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, code)
    );
    CREATE TABLE challenge_progress (
        week_id TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        completed_at INTEGER,
        PRIMARY KEY (week_id, user_id, code)
    );
    """,
    # 5 - server bosses
    """
    CREATE TABLE bosses (
        boss_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        max_hp INTEGER NOT NULL,
        hp INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',  -- active | defeated | escaped
        started_at INTEGER NOT NULL,
        ends_at INTEGER NOT NULL,
        channel_id INTEGER,
        message_id INTEGER
    );
    CREATE TABLE boss_damage (
        boss_id INTEGER NOT NULL REFERENCES bosses(boss_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        damage INTEGER NOT NULL DEFAULT 0,
        hits INTEGER NOT NULL DEFAULT 0,
        last_attack_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (boss_id, user_id)
    );
    """,
    # 6 - Discord <-> Minecraft account links
    """
    CREATE TABLE links (
        user_id INTEGER PRIMARY KEY,
        mc_username TEXT NOT NULL,
        status TEXT NOT NULL,  -- pending | approved
        requested_at INTEGER NOT NULL,
        decided_by INTEGER,
        decided_at INTEGER
    );
    CREATE UNIQUE INDEX idx_links_username ON links(mc_username COLLATE NOCASE);
    """,
    # 7 - teams and the weekly team season
    """
    CREATE TABLE teams (
        team_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        tag TEXT NOT NULL,
        leader_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE UNIQUE INDEX idx_teams_name ON teams(name COLLATE NOCASE);
    CREATE UNIQUE INDEX idx_teams_tag ON teams(tag COLLATE NOCASE);
    CREATE TABLE team_members (
        user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
        joined_at INTEGER NOT NULL,
        last_active TEXT  -- local date of the last mining, for the team bonus
    );
    CREATE INDEX idx_team_members_team ON team_members(team_id);
    CREATE TABLE team_invites (
        team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL,
        invited_by INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        PRIMARY KEY (team_id, user_id)
    );
    -- emeralds earned by each member for their team, per week
    CREATE TABLE team_season_scores (
        season_id TEXT NOT NULL,
        team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (season_id, team_id, user_id)
    );
    CREATE TABLE team_seasons_closed (
        season_id TEXT PRIMARY KEY,
        closed_at INTEGER NOT NULL
    );
    -- name and tag are copied: the team may be renamed or disbanded later
    CREATE TABLE team_season_results (
        season_id TEXT NOT NULL,
        rank INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        tag TEXT NOT NULL,
        score INTEGER NOT NULL,
        reward INTEGER NOT NULL,
        PRIMARY KEY (season_id, rank)
    );
    """,
    # 8 - weekend tournaments
    """
    CREATE TABLE tournaments (
        tournament_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_id TEXT NOT NULL,
        status TEXT NOT NULL,       -- open | running | finished | cancelled
        closes_at INTEGER,          -- end of registrations (NULL = staff closes them)
        starts_at INTEGER,          -- first round (NULL = right after the draw)
        next_round_at INTEGER,
        round INTEGER NOT NULL DEFAULT 0,   -- last round played
        rounds INTEGER NOT NULL DEFAULT 0,
        pot INTEGER NOT NULL DEFAULT 0,
        house_bonus INTEGER NOT NULL DEFAULT 0,
        winner_id INTEGER,
        created_at INTEGER NOT NULL,
        finished_at INTEGER
    );
    CREATE INDEX idx_tournaments_week ON tournaments(week_id);
    CREATE TABLE tournament_players (
        tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        paid INTEGER NOT NULL,
        joined_at INTEGER NOT NULL,
        eliminated_round INTEGER,   -- NULL while still in the tournament
        prize INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tournament_id, user_id)
    );
    CREATE TABLE tournament_matches (
        tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
        round INTEGER NOT NULL,
        slot INTEGER NOT NULL,      -- position in the round: slots 2k and 2k+1 feed slot k of the next round
        player1 INTEGER NOT NULL,
        player2 INTEGER,            -- NULL = bye, player1 goes through
        winner INTEGER,
        winner_hp REAL,
        played_at INTEGER,
        PRIMARY KEY (tournament_id, round, slot)
    );
    """,
    # 9 - enchantments (books and lapis are rows of the items table)
    """
    CREATE TABLE gear_enchants (
        gear_id INTEGER NOT NULL REFERENCES gear(gear_id) ON DELETE CASCADE,
        enchant TEXT NOT NULL,
        level INTEGER NOT NULL CHECK (level >= 1),
        PRIMARY KEY (gear_id, enchant)
    );
    """,
    # 10 - duels being fought (the stakes are held until the end; refunded after a restart)
    """
    CREATE TABLE duels (
        duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id INTEGER NOT NULL,
        opponent_id INTEGER NOT NULL,
        stake INTEGER NOT NULL,
        started_at INTEGER NOT NULL
    );
    """,
    # 11 - the wandering villager
    """
    CREATE TABLE villager_visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,              -- local date of the visit
        arrives_at INTEGER NOT NULL,
        leaves_at INTEGER NOT NULL,
        status TEXT NOT NULL,           -- here | gone
        channel_id INTEGER,
        message_id INTEGER
    );
    CREATE INDEX idx_villager_day ON villager_visits(day);
    CREATE TABLE villager_offers (
        visit_id INTEGER NOT NULL REFERENCES villager_visits(visit_id) ON DELETE CASCADE,
        slot INTEGER NOT NULL,
        kind TEXT NOT NULL,             -- sell | buy | exclusive
        asset TEXT NOT NULL,            -- asset key (game/assets.py)
        amount INTEGER NOT NULL,
        price INTEGER NOT NULL,
        value INTEGER NOT NULL,         -- reference value, to show the deal
        taken_by INTEGER,
        taken_at INTEGER,
        PRIMARY KEY (visit_id, slot)
    );
    """,
    # 12 - the tournament registration message (Join / Leave buttons)
    """
    ALTER TABLE tournaments ADD COLUMN channel_id INTEGER;
    ALTER TABLE tournaments ADD COLUMN message_id INTEGER;
    """,
    # 13 - moderation: warnings, mutes, kicks and bans
    """
    CREATE TABLE sanctions (
        sanction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,             -- warn | mute | kick | ban
        reason TEXT,
        moderator_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER,             -- end of a temporary mute or ban (NULL = permanent)
        active INTEGER NOT NULL DEFAULT 1,  -- warning still counted, mute or ban in force
        applied_until INTEGER,          -- end of the Discord timeout currently set (mutes)
        ended_at INTEGER,
        ended_by INTEGER
    );
    CREATE INDEX idx_sanctions_user ON sanctions(user_id, kind, active);
    """,
    # 14 - /lock saves the permissions it changes; team season scores outlive the team
    """
    CREATE TABLE channel_locks (
        channel_id INTEGER PRIMARY KEY,
        saved TEXT NOT NULL,            -- JSON: the overwrite values /unlock puts back
        locked_by INTEGER NOT NULL,
        locked_at INTEGER NOT NULL
    );
    CREATE INDEX idx_sanctions_due ON sanctions(kind, active, expires_at);
    CREATE INDEX idx_team_invites_user ON team_invites(user_id);
    -- name and tag of deleted teams, for the results of a week not closed yet
    CREATE TABLE team_archive (
        team_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        tag TEXT NOT NULL
    );
    -- same table without the cascade: deleting a team must not delete what its members earned
    CREATE TABLE team_season_scores_new (
        season_id TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (season_id, team_id, user_id)
    );
    INSERT INTO team_season_scores_new(season_id, team_id, user_id, score)
        SELECT season_id, team_id, user_id, score FROM team_season_scores;
    DROP TABLE team_season_scores;
    ALTER TABLE team_season_scores_new RENAME TO team_season_scores;
    """,
    # 15 - Blockdle: the block of each day, and each player's guesses
    """
    CREATE TABLE blockdle_days (
        day TEXT PRIMARY KEY,           -- local date, YYYY-MM-DD
        block TEXT NOT NULL
    );
    CREATE TABLE blockdle_guesses (
        day TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        n INTEGER NOT NULL,             -- 1 for the first guess of the day
        block TEXT NOT NULL,
        guessed_at INTEGER NOT NULL,
        PRIMARY KEY (day, user_id, n)
    );
    CREATE TABLE blockdle_wins (
        day TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        tries INTEGER NOT NULL,
        reward INTEGER NOT NULL,
        won_at INTEGER NOT NULL,
        PRIMARY KEY (day, user_id)
    );
    """,
    # 16 - robberies (the victim has some time to stop them) and small bot state (the market board message)
    """
    CREATE TABLE robberies (
        rob_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thief_id INTEGER NOT NULL,
        victim_id INTEGER NOT NULL,
        mode TEXT NOT NULL,             -- risky | discreet
        amount INTEGER NOT NULL,        -- the loot aimed at, rolled at the start
        started_at INTEGER NOT NULL,
        ends_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',  -- active | stopped | done
        stolen INTEGER NOT NULL DEFAULT 0,
        fine INTEGER NOT NULL DEFAULT 0,
        channel_id INTEGER,
        message_id INTEGER
    );
    CREATE INDEX idx_robberies_status ON robberies(status, ends_at);
    CREATE INDEX idx_robberies_thief ON robberies(thief_id, started_at);
    CREATE INDEX idx_robberies_victim ON robberies(victim_id, status);
    CREATE TABLE bot_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 17: loans between players
    """
    CREATE TABLE loan_offers (
        offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        lender_id INTEGER NOT NULL,
        borrower_id INTEGER NOT NULL,
        proposer_id INTEGER NOT NULL,   -- the lender (offer) or the borrower (ask)
        amount INTEGER NOT NULL,
        interest INTEGER NOT NULL,      -- percent
        days INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'open'  -- open | accepted | declined
    );
    CREATE TABLE loans (
        loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        lender_id INTEGER NOT NULL,
        borrower_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,        -- lent
        interest INTEGER NOT NULL,      -- percent
        due INTEGER NOT NULL,           -- to repay: amount + interest
        penalty INTEGER NOT NULL DEFAULT 0,  -- added when late
        repaid INTEGER NOT NULL DEFAULT 0,
        started_at INTEGER NOT NULL,
        due_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',  -- active | late | repaid | forgiven
        closed_at INTEGER
    );
    CREATE INDEX idx_loans_borrower ON loans(borrower_id, status);
    CREATE INDEX idx_loans_lender ON loans(lender_id, status);
    CREATE INDEX idx_loans_due ON loans(status, due_at);
    """,
    # 18: species
    """
    ALTER TABLE users ADD COLUMN species TEXT;
    ALTER TABLE users ADD COLUMN species_changed_at INTEGER;
    """,
    # 19: PVE dungeon
    """
    CREATE TABLE pve_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        leader_id INTEGER NOT NULL,
        difficulty TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'lobby',  -- lobby | between | done | cancelled
        wave INTEGER NOT NULL DEFAULT 0,       -- waves cleared
        created_at INTEGER NOT NULL,
        started_at INTEGER,
        deadline INTEGER NOT NULL,             -- lobby: start before; between waves: decide before
        ended_at INTEGER,
        channel_id INTEGER,
        message_id INTEGER
    );
    CREATE TABLE pve_members (
        run_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        joined_at INTEGER NOT NULL,
        entry INTEGER NOT NULL,                -- what they paid to enter
        status TEXT NOT NULL DEFAULT 'in',     -- in | dead | left | cleared
        loot INTEGER NOT NULL DEFAULT 0,       -- earned so far (lost if they die)
        paid INTEGER NOT NULL DEFAULT 0,       -- loot paid when they left or cleared
        hero TEXT,                             -- JSON: health, gear and potions of the run
        potions INTEGER NOT NULL DEFAULT 0,
        strong_potion INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, user_id)
    );
    CREATE INDEX idx_pve_runs_status ON pve_runs(status, deadline);
    CREATE INDEX idx_pve_members_user ON pve_members(user_id);
    """,
    # 20: players blocked from Blocky by the staff
    """
    CREATE TABLE blocky_bans (
        user_id INTEGER PRIMARY KEY,
        until INTEGER,                 -- NULL = until the staff lifts it
        reason TEXT,
        by_id INTEGER NOT NULL,
        at INTEGER NOT NULL
    );
    """,
    # 21: training dummy (damage tester records)
    """
    CREATE TABLE dummy_scores (
        user_id INTEGER PRIMARY KEY,
        best_total REAL NOT NULL DEFAULT 0,   -- best series of hits (total damage)
        best_hit REAL NOT NULL DEFAULT 0,
        series INTEGER NOT NULL DEFAULT 0,
        last_at INTEGER NOT NULL DEFAULT 0
    );
    """,
    # 22: profile customization and team banners
    """
    CREATE TABLE profiles (
        user_id INTEGER PRIMARY KEY,
        bio TEXT,
        color TEXT,                    -- a dye key or "#rrggbb"
        title TEXT,                    -- a title key, or "custom:<text>"
        frame TEXT,                    -- a frame key
        showcase TEXT                  -- JSON list of up to 3 achievement codes
    );
    CREATE TABLE profile_unlocks (
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,            -- color | hex | frame | custom_title
        key TEXT NOT NULL,
        at INTEGER NOT NULL,
        PRIMARY KEY (user_id, kind, key)
    );
    CREATE TABLE team_banners (
        team_id INTEGER PRIMARY KEY,
        base TEXT NOT NULL,            -- a dye key
        layers TEXT NOT NULL,          -- JSON [[pattern, dye], ...] (3 at most)
        updated_at INTEGER NOT NULL
    );
    """,
    # 23: the guide (a private channel per player with a checklist of first steps)
    """
    CREATE TABLE guides (
        user_id INTEGER PRIMARY KEY,
        channel_id INTEGER,            -- the player's guide channel (NULL once deleted)
        message_id INTEGER,            -- its checklist message
        created_at INTEGER NOT NULL,
        done TEXT NOT NULL DEFAULT '', -- steps already done, comma separated
        completed_at INTEGER,
        rewarded_at INTEGER,           -- the reward is paid once ever
        delete_at INTEGER              -- when the bot deletes the channel
    );
    CREATE INDEX guides_channel ON guides(channel_id);
    """,
    # 24: team spaces (a private Discord category per team)
    """
    CREATE TABLE team_spaces (
        team_id INTEGER PRIMARY KEY,   -- no foreign key: kept after the team is gone, to clean up Discord
        payer_id INTEGER NOT NULL,
        paid INTEGER NOT NULL,
        unlocked_at INTEGER NOT NULL,
        role_id INTEGER,               -- the team role (its members see the category)
        category_id INTEGER
    );
    """,
    # 25: what each player won (or lost) at games of chance each day, for the daily cap
    """
    CREATE TABLE gamble_days (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,             -- local date, YYYY-MM-DD
        net INTEGER NOT NULL,          -- winnings minus bets
        PRIMARY KEY (user_id, day)
    );
    """,
    # 26: rewards already paid (achievements…), kept by a /reset of the progress so they're never paid twice
    """
    CREATE TABLE rewards_paid (
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,            -- achievement
        key TEXT NOT NULL,
        PRIMARY KEY (user_id, kind, key)
    );
    INSERT OR IGNORE INTO rewards_paid(user_id, kind, key) SELECT user_id, 'achievement', code FROM achievements;
    """,
    # 27: what a running duel needs to be undone after a restart: the potions drunk and its message
    """
    ALTER TABLE duels ADD COLUMN potions TEXT NOT NULL DEFAULT '[]';  -- JSON [[user_id, potion key], ...]
    ALTER TABLE duels ADD COLUMN channel_id INTEGER;
    ALTER TABLE duels ADD COLUMN message_id INTEGER;
    """,
    # 28: repairs with ingots on an anvil: how many times a piece was repaired (each repair costs more), the
    # player's anvil (0 = none, 3 = new, 2 = chipped, 1 = damaged), and the repairs of gear listed at the auction
    """
    ALTER TABLE gear ADD COLUMN repairs INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE auctions ADD COLUMN repairs INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN anvil INTEGER NOT NULL DEFAULT 0;
    """,
    # 29: waiting times reset by the staff (/player cooldowns) when they're counted from an event kept in the
    # history (a robbery, a dungeon run): the check ignores the events before the reset
    """
    CREATE TABLE cooldown_resets (
        user_id INTEGER NOT NULL,
        timer TEXT NOT NULL,           -- rob, rob_protection, dungeon
        at INTEGER NOT NULL,
        PRIMARY KEY (user_id, timer)
    );
    """,
    # 30: timed events (Gambling Frenzy, Mining Rush…) and the challenges picked for each day and week (kept so
    # the next period can pick different ones)
    """
    CREATE TABLE live_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        starts_at INTEGER NOT NULL,
        ends_at INTEGER NOT NULL,
        day TEXT,                      -- local date of the day's random event, NULL when the staff started it
        started_by INTEGER,
        announced INTEGER NOT NULL DEFAULT 0,  -- 0 = to post, 1 = posted, 2 = its end posted
        channel_id INTEGER,
        message_id INTEGER
    );
    CREATE INDEX live_events_ends ON live_events(ends_at);
    CREATE TABLE challenge_sets (
        period TEXT PRIMARY KEY,       -- "day:YYYY-MM-DD" or "week:YYYY-Www"
        codes TEXT NOT NULL            -- the challenges picked, comma separated
    );
    """,
]


@dataclass
class Ctx:
    """What a game function receives: the connection plus the current moment."""

    conn: sqlite3.Connection
    now: float
    rng: random.Random
    notices: list[Any] = field(default_factory=list)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    @property
    def local_now(self) -> datetime:
        return datetime.fromtimestamp(self.now, ZoneInfo(settings.get()["timezone"]))

    @property
    def today(self) -> date:
        return self.local_now.date()

    @property
    def week_id(self) -> str:
        return week_id_of(self.local_now)


def week_id_of(moment: datetime | date) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def apply_migrations(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version;").fetchone()[0]
    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        log.info("Applying database migration %d", version)
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")


class Database:
    def __init__(self, path: str | Path = "economy.db"):
        self.path = str(path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db")
        self._conn: sqlite3.Connection | None = None
        # Overridable for tests.
        self.clock: Callable[[], float] = time.time
        self.rng = random.Random()
        # Called with the notices of each committed transaction.
        self.notice_handler: Callable[[list[Any]], Awaitable[None]] | None = None
        self._pending: set[asyncio.Task] = set()

    async def _call(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args))

    def _set_aside_legacy_database(self) -> None:
        """The pre-migrations database can't be upgraded: keep it as a backup and start fresh."""
        path = Path(self.path)
        if not path.exists() or path.stat().st_size == 0:
            return
        conn = sqlite3.connect(self.path)
        try:
            version = conn.execute("PRAGMA user_version;").fetchone()[0]
            has_users = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users';"
            ).fetchone()
        finally:
            conn.close()
        if version != 0 or not has_users:
            return
        backup = path.with_name(f"{path.name}.legacy-{int(time.time())}")
        try:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix)
                if src.exists():
                    src.rename(Path(str(backup) + suffix))
        except OSError as e:
            raise RuntimeError(
                f"{path} uses the old database format and could not be renamed ({e}). "
                "Move or delete it by hand (with Docker, mount a folder instead of the file: see README)."
            ) from e
        log.warning("Old database format found: moved to %s, starting a new database.", backup)

    def _open(self) -> None:
        self._set_aside_legacy_database()
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        apply_migrations(conn)
        self._conn = conn

    async def open(self) -> None:
        await self._call(self._open)

    def _backup(self, dest: str) -> None:
        assert self._conn is not None, "Database.open() was not called"
        target = sqlite3.connect(dest)
        try:
            self._conn.backup(target)  # consistent copy, even while the bot is writing
        finally:
            target.close()

    async def backup_to(self, dest: str | Path) -> None:
        await self._call(self._backup, str(dest))

    async def close(self) -> None:
        if self._conn is not None:
            await self._call(self._conn.close)
            self._conn = None
        self._executor.shutdown(wait=True)

    def _transaction(self, fn: Callable[..., T], args: tuple, kwargs: dict) -> tuple[T, list[Any]]:
        assert self._conn is not None, "Database.open() was not called"
        ctx = Ctx(conn=self._conn, now=self.clock(), rng=self.rng)
        self._conn.execute("BEGIN IMMEDIATE;")
        try:
            result = fn(ctx, *args, **kwargs)
        except BaseException:
            self._conn.execute("ROLLBACK;")
            raise
        self._conn.execute("COMMIT;")
        return result, ctx.notices

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run `fn(ctx, *args, **kwargs)` in one transaction and return its result."""
        result, notices = await self._call(self._transaction, fn, args, kwargs)
        if notices and self.notice_handler is not None:
            # Announce in the background: a slow Discord call must not delay
            # the reply to the interaction that caused the notice.
            task = asyncio.create_task(self._handle_notices(notices))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        return result

    async def _handle_notices(self, notices: list[Any]) -> None:
        try:
            await self.notice_handler(notices)  # type: ignore[misc]
        except Exception:
            log.exception("Notice handler failed")

    async def drain(self) -> None:
        """Wait for the background notice handlers (used by tests)."""
        while self._pending:
            await asyncio.gather(*list(self._pending))
