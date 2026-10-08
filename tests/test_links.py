from __future__ import annotations

import unittest

from game import links
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB, STAFF = 1, 2, 99


class LinkTests(GameTestCase):
    async def test_request_then_approve(self):
        await self.run_game(links.request_link, ALICE, "Alice_MC")
        await self.run_game(links.check_pending, ALICE, "alice_mc")
        await self.run_game(links.approve, ALICE, STAFF)
        link = await self.run_game(links.get_link, ALICE)
        self.assertEqual((link["status"], link["decided_by"]), ("approved", STAFF))
        with self.assertRaises(GameError):
            await self.run_game(links.approve, ALICE, STAFF)  # already handled
        with self.assertRaises(GameError):
            await self.run_game(links.request_link, ALICE, "Other")  # already linked

    async def test_username_is_unique_case_insensitive(self):
        await self.run_game(links.request_link, ALICE, "Steve")
        with self.assertRaises(GameError):
            await self.run_game(links.request_link, BOB, "steve")

    async def test_new_request_replaces_pending_and_old_buttons_stop_working(self):
        await self.run_game(links.request_link, ALICE, "First")
        await self.run_game(links.request_link, ALICE, "Second")
        with self.assertRaises(GameError):
            await self.run_game(links.check_pending, ALICE, "First")
        # The old name is free again.
        await self.run_game(links.request_link, BOB, "First")

    async def test_reject_and_unlink(self):
        await self.run_game(links.request_link, ALICE, "Alex")
        await self.run_game(links.reject, ALICE, STAFF)
        self.assertIsNone(await self.run_game(links.get_link, ALICE))
        with self.assertRaises(GameError):
            await self.run_game(links.unlink, ALICE)

    async def test_invalid_username(self):
        for name in ("ab", "way_too_long_username", "bad name", "semi;colon"):
            with self.assertRaises(GameError):
                await self.run_game(links.request_link, ALICE, name)


if __name__ == "__main__":
    unittest.main()
