"""Loans between players (/loan).

- A lender offers a loan (/loan offer) or a borrower asks for one (/loan ask):
  the amount, the interest (the lender's choice, up to `max_interest`) and the
  duration in days. The other player accepts with a button before the offer
  expires; everything is checked again then and the emeralds move at once.
- A borrower has one unpaid loan at a time. A lender has up to `max_loans_out`.
- The borrower repays with /loan repay, all at once or bit by bit. The lender
  can forgive what's left (/loan forgive).
- Late (not repaid at the deadline): `late_penalty` of what's left is added,
  the bot takes what it can from the borrower's emeralds right away, then
  `garnish` of every emerald they receive goes to the lender until it's paid.
  Until then they can't /pay, /trade, list at the auction, lend or borrow.
- Loans, repayments and interest move emeralds between players: they don't
  count for the seasons (like /pay).
"""
from __future__ import annotations

import math

from game import players, settings
from game.db import Ctx
from game.errors import GameError
from game.notices import LoanRepaid

DAY = 86400
UNPAID = ("active", "late")


def _cfg() -> dict:
    return settings.get()["loans"]


def left(loan: dict) -> int:
    """What the borrower still owes."""
    return max(0, loan["due"] + loan["penalty"] - loan["repaid"])


def due_for(amount: int, interest: int) -> int:
    return amount + amount * interest // 100


def _loan(ctx: Ctx, loan_id: int) -> dict:
    return dict(ctx.one("SELECT * FROM loans WHERE loan_id=?;", (loan_id,)))


def debt_of(ctx: Ctx, user_id: int) -> dict | None:
    """The borrower's unpaid loan, if any."""
    row = ctx.one("SELECT * FROM loans WHERE borrower_id=? AND status IN ('active', 'late');", (user_id,))
    return dict(row) if row else None


def is_late(ctx: Ctx, user_id: int) -> bool:
    return ctx.one("SELECT 1 FROM loans WHERE borrower_id=? AND status='late';", (user_id,)) is not None


def check_not_late(ctx: Ctx, user_id: int, what: str) -> None:
    """Late borrowers can't move their wealth to someone else."""
    debt = ctx.one("SELECT lender_id FROM loans WHERE borrower_id=? AND status='late';", (user_id,))
    if debt is not None:
        raise GameError(
            f"<@{user_id}> has a late loan to repay to <@{debt['lender_id']}>: no {what} until it's paid "
            "(`/loan repay`)."
        )


# ---------------- offers ----------------
def _check_terms(amount: int, interest: int, days: int) -> None:
    c = _cfg()
    lo, hi = int(c["min_amount"]), int(c["max_amount"])
    if not lo <= amount <= hi:
        raise GameError(f"Loans go from **{lo:,}** to **{hi:,}** emeralds.")
    top = round(float(c["max_interest"]) * 100)
    if not 0 <= interest <= top:
        raise GameError(f"The interest goes from **0%** to **{top}%**.")
    dmin, dmax = int(c["min_days"]), int(c["max_days"])
    if not dmin <= days <= dmax:
        raise GameError(f"A loan lasts from **{dmin}** to **{dmax}** day(s).")


def _check_parties(ctx: Ctx, lender_id: int, borrower_id: int, amount: int) -> None:
    if lender_id == borrower_id:
        raise GameError("You can't lend to yourself.")
    check_not_late(ctx, lender_id, "lending")
    if debt_of(ctx, borrower_id):
        raise GameError(f"<@{borrower_id}> already has a loan to repay: one at a time.")
    out = ctx.one("SELECT COUNT(*) AS n FROM loans WHERE lender_id=? AND status IN ('active', 'late');", (lender_id,))["n"]
    if out >= int(_cfg()["max_loans_out"]):
        raise GameError(f"<@{lender_id}> already has **{out}** loans running (max {_cfg()['max_loans_out']}).")
    have = players.get_emeralds(ctx, lender_id)
    if have < amount:
        raise GameError(f"<@{lender_id}> doesn't have **{amount:,}** emeralds to lend (has {have:,}).")


def propose(ctx: Ctx, proposer_id: int, lender_id: int, borrower_id: int, amount: int, interest: int, days: int) -> dict:
    """An offer (the lender proposes) or a request (the borrower asks), waiting for the other player."""
    if proposer_id not in (lender_id, borrower_id):
        raise GameError("Only the lender or the borrower can propose a loan.")
    _check_terms(amount, interest, days)
    _check_parties(ctx, lender_id, borrower_id, amount)
    now = int(ctx.now)
    expires_at = now + int(float(_cfg()["offer_minutes"]) * 60)
    cur = ctx.execute(
        """
        INSERT INTO loan_offers(lender_id, borrower_id, proposer_id, amount, interest, days, created_at, expires_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (lender_id, borrower_id, proposer_id, amount, interest, days, now, expires_at),
    )
    return offer(ctx, cur.lastrowid)


def offer(ctx: Ctx, offer_id: int) -> dict:
    row = ctx.one("SELECT * FROM loan_offers WHERE offer_id=?;", (offer_id,))
    if row is None:
        raise GameError("This loan offer doesn't exist anymore.")
    out = dict(row)
    out["due"] = due_for(out["amount"], out["interest"])
    out["answerer_id"] = out["borrower_id"] if out["proposer_id"] == out["lender_id"] else out["lender_id"]
    return out


def _open_offer(ctx: Ctx, offer_id: int, user_id: int) -> dict:
    o = offer(ctx, offer_id)
    if user_id != o["answerer_id"]:
        raise GameError("This offer isn't for you.")
    if o["status"] != "open":
        raise GameError("This offer was already answered.")
    if ctx.now >= o["expires_at"]:
        raise GameError("This offer has expired. Make a new one with `/loan offer` or `/loan ask`.")
    return o


def accept(ctx: Ctx, offer_id: int, user_id: int) -> dict:
    """The other player accepts: the emeralds move now and the loan starts."""
    o = _open_offer(ctx, offer_id, user_id)
    _check_terms(o["amount"], o["interest"], o["days"])  # the settings may have changed
    _check_parties(ctx, o["lender_id"], o["borrower_id"], o["amount"])
    ctx.execute("UPDATE loan_offers SET status='accepted' WHERE offer_id=?;", (offer_id,))
    players.spend_emeralds(ctx, o["lender_id"], o["amount"])
    players.give_emeralds(ctx, o["borrower_id"], o["amount"])
    now = int(ctx.now)
    cur = ctx.execute(
        """
        INSERT INTO loans(lender_id, borrower_id, amount, interest, due, started_at, due_at)
        VALUES(?, ?, ?, ?, ?, ?, ?);
        """,
        (o["lender_id"], o["borrower_id"], o["amount"], o["interest"], o["due"], now, now + o["days"] * DAY),
    )
    players.bump_stat(ctx, o["lender_id"], "emeralds_lent", o["amount"])
    players.bump_stat(ctx, o["lender_id"], "loans_given")
    players.bump_stat(ctx, o["borrower_id"], "loans_taken")
    return {"offer": o, "loan": _loan(ctx, cur.lastrowid)}


def decline(ctx: Ctx, offer_id: int, user_id: int) -> dict:
    o = _open_offer(ctx, offer_id, user_id)
    ctx.execute("UPDATE loan_offers SET status='declined' WHERE offer_id=?;", (offer_id,))
    o["status"] = "declined"
    return o


# ---------------- paying back ----------------
def _credit(ctx: Ctx, loan: dict, amount: int, auto: bool = False) -> dict:
    """Count `amount` as repaid (the emeralds already moved). Closes the loan when nothing is left."""
    ctx.execute("UPDATE loans SET repaid = repaid + ? WHERE loan_id=?;", (amount, loan["loan_id"]))
    loan = _loan(ctx, loan["loan_id"])
    if left(loan) == 0:
        ctx.execute("UPDATE loans SET status='repaid', closed_at=? WHERE loan_id=?;", (int(ctx.now), loan["loan_id"]))
        loan = _loan(ctx, loan["loan_id"])
        ctx.notices.append(LoanRepaid(loan["loan_id"], loan["lender_id"], loan["borrower_id"], loan["repaid"], auto))
    return loan


def repay(ctx: Ctx, user_id: int, amount: int | None = None) -> dict:
    """The borrower pays back `amount` (everything left by default)."""
    loan = debt_of(ctx, user_id)
    if loan is None:
        raise GameError("You don't owe anything.")
    owed = left(loan)
    have = players.get_emeralds(ctx, user_id)
    if amount is None:
        if have < owed:
            raise GameError(
                f"You owe **{owed:,}** and have **{have:,}**. Pay part of it with `/loan repay amount:{have}`."
                if have else f"You owe **{owed:,}** and have no emeralds."
            )
        amount = owed
    if amount <= 0:
        raise GameError("The amount must be greater than 0.")
    amount = min(amount, owed)
    players.spend_emeralds(ctx, user_id, amount)
    players.give_emeralds(ctx, loan["lender_id"], amount)
    return {"paid": amount, "loan": _credit(ctx, loan, amount)}


def forgive(ctx: Ctx, lender_id: int, borrower_id: int) -> dict:
    """The lender cancels what's left."""
    loan = debt_of(ctx, borrower_id)
    if loan is None or loan["lender_id"] != lender_id:
        raise GameError(f"<@{borrower_id}> doesn't owe you anything.")
    ctx.execute("UPDATE loans SET status='forgiven', closed_at=? WHERE loan_id=?;", (int(ctx.now), loan["loan_id"]))
    out = _loan(ctx, loan["loan_id"])
    out["forgiven"] = left(loan)
    return out


def garnish(ctx: Ctx, user_id: int, amount: int) -> int:
    """Called by players.give_emeralds: the share of `amount` that goes to the lender of a late borrower.

    The lender is paid directly (not through give_emeralds), so this never chains.
    """
    row = ctx.one("SELECT * FROM loans WHERE borrower_id=? AND status='late';", (user_id,))
    if row is None:
        return 0
    loan = dict(row)
    share = min(left(loan), amount, int(amount * float(_cfg()["garnish"])))
    if share <= 0:
        return 0
    players.ensure_user(ctx, loan["lender_id"])
    ctx.execute("UPDATE users SET emeralds = emeralds + ? WHERE user_id=?;", (share, loan["lender_id"]))
    _credit(ctx, loan, share, auto=True)
    return share


def tick(ctx: Ctx) -> list[dict]:
    """Called every minute: loans past their deadline become late (penalty, then the bot collects)."""
    events = []
    rows = ctx.all("SELECT * FROM loans WHERE status='active' AND due_at <= ?;", (int(ctx.now),))
    for row in rows:
        loan = dict(row)
        penalty = math.ceil(left(loan) * float(_cfg()["late_penalty"]))
        ctx.execute("UPDATE loans SET status='late', penalty=? WHERE loan_id=?;", (penalty, loan["loan_id"]))
        loan = _loan(ctx, loan["loan_id"])
        taken = min(left(loan), players.get_emeralds(ctx, loan["borrower_id"]))
        if taken > 0:
            players.spend_emeralds(ctx, loan["borrower_id"], taken)
            players.give_emeralds(ctx, loan["lender_id"], taken)
            loan = _credit(ctx, loan, taken, auto=True)
        players.bump_stat(ctx, loan["borrower_id"], "loans_late")
        events.append({"loan": loan, "penalty": penalty, "taken": taken, "left": left(loan)})
    return events


# ---------------- overviews ----------------
def overview(ctx: Ctx, user_id: int) -> dict:
    """What /loan list shows: the player's debt and the loans they gave."""
    debt = debt_of(ctx, user_id)
    given = [
        dict(r) for r in ctx.all(
            "SELECT * FROM loans WHERE lender_id=? AND status IN ('active', 'late') ORDER BY due_at;", (user_id,)
        )
    ]
    for loan in [debt, *given]:
        if loan:
            loan["left"] = left(loan)
    return {"debt": debt, "given": given}
