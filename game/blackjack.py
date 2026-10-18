"""Blackjack (/blackjack): beat the dealer without going over 21.

- Each hand is dealt from a real deck of 52 cards, shuffled: a card comes out once (at most 4 of a rank).
  Aces count 1 or 11, faces 10.
- You get two cards, the dealer one face up and one face down. 21 with your first two cards is a
  **blackjack**: it pays games.blackjack_natural_payout (3:2), unless the dealer has one too (a push).
- Hit (one more card), stand (the dealer plays), or double (twice the bet, one card, then you stand).
  The dealer draws until games.blackjack_dealer_stands (17).
- A win pays twice the bet, a push gives it back. Bets and the daily cap are shared with the other games of
  chance (game/gambling.py). No move for games.move_minutes: you stand.
"""
from __future__ import annotations

import math
import random

from game import gambling, players, settings
from game.db import Ctx
from game.errors import GameError

KIND = "blackjack"
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("♠", "♥", "♦", "♣")


def _cfg() -> dict:
    return settings.get()["games"]


def new_deck(rng: random.Random) -> list[str]:
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    rng.shuffle(deck)
    return deck


def draw(state: dict, rng: random.Random) -> str:
    """The next card of the hand's deck (a hand started before the deck existed gets one without the cards
    already on the table)."""
    if "deck" not in state:
        dealt = state["player"] + state["dealer"]
        state["deck"] = [c for c in new_deck(rng) if c not in dealt]
    return state["deck"].pop()


def value(cards: list[str]) -> int:
    """The best total of a hand: aces count 11 while it doesn't go over 21."""
    total, aces = 0, 0
    for card in cards:
        rank = card[:-1]
        if rank == "A":
            total, aces = total + 11, aces + 1
        else:
            total += 10 if rank in ("J", "Q", "K") else int(rank)
    while total > 21 and aces:
        total, aces = total - 10, aces - 1
    return total


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and value(cards) == 21


def start(ctx: Ctx, user_id: int, amount: int) -> dict:
    if not _cfg()["blackjack_enabled"]:
        raise GameError("🃏 The blackjack table is closed for now.")
    state = {"player": [], "dealer": [], "doubled": False, "deck": new_deck(ctx.rng)}
    for hand in ("player", "dealer", "player", "dealer"):  # dealt in turn, like at a table
        state[hand].append(draw(state, ctx.rng))
    game = gambling.open_game(ctx, user_id, KIND, amount, state)
    players.bump_stat(ctx, user_id, "blackjack_hands")
    players.bump_stat(ctx, user_id, "blackjack_bet", amount)
    if is_blackjack(state["player"]) or is_blackjack(state["dealer"]):
        return _finish(ctx, game)  # a blackjack ends the hand at once
    return game


def hit(ctx: Ctx, game_id: int, user_id: int) -> dict:
    game = gambling.my_game(ctx, game_id, user_id, KIND)
    game["state"]["player"].append(draw(game["state"], ctx.rng))
    if value(game["state"]["player"]) >= 21:
        return _finish(ctx, game)  # bust, or 21: nothing more to ask
    return gambling.save_game(ctx, game)


def stand(ctx: Ctx, game_id: int, user_id: int) -> dict:
    return _finish(ctx, gambling.my_game(ctx, game_id, user_id, KIND))


def can_double(game: dict) -> bool:
    return game["status"] == "active" and len(game["state"]["player"]) == 2 and not game["state"]["doubled"]


def double(ctx: Ctx, game_id: int, user_id: int) -> dict:
    game = gambling.my_game(ctx, game_id, user_id, KIND)
    if not can_double(game):
        raise GameError("You can only double with your first two cards.")
    extra = game["bet"]
    players.spend_emeralds(ctx, user_id, extra)
    players.bump_stat(ctx, user_id, "blackjack_bet", extra)
    game["state"]["doubled"] = True
    game["state"]["player"].append(draw(game["state"], ctx.rng))
    game = gambling.save_game(ctx, game, extra_bet=extra)
    return _finish(ctx, game)


def _finish(ctx: Ctx, game: dict) -> dict:
    """The dealer plays (unless the player went over 21 or someone has a blackjack), then the hand is paid."""
    state, bet = game["state"], game["bet"]
    player, dealer = state["player"], state["dealer"]
    if is_blackjack(player) or is_blackjack(dealer):
        if is_blackjack(player) and is_blackjack(dealer):
            result, paid = "push", bet
        elif is_blackjack(player):
            result, paid = "blackjack", bet + math.floor(bet * float(_cfg()["blackjack_natural_payout"]) + 0.5)
        else:
            result, paid = "lose", 0
    elif value(player) > 21:
        result, paid = "bust", 0
    else:
        while value(dealer) < int(_cfg()["blackjack_dealer_stands"]):
            dealer.append(draw(state, ctx.rng))
        mine, theirs = value(player), value(dealer)
        if theirs > 21 or mine > theirs:
            result, paid = "win", bet * 2
        elif mine == theirs:
            result, paid = "push", bet
        else:
            result, paid = "lose", 0
    if paid > bet:
        players.bump_stat(ctx, game["user_id"], "blackjack_wins")
    players.bump_stat(ctx, game["user_id"], "blackjack_paid", paid)
    return gambling.close_game(ctx, game, result, paid)


def expire(ctx: Ctx) -> list[dict]:
    """Hands left without a move: the player stands."""
    return [_finish(ctx, game) for game in gambling.due_games(ctx, KIND)]
