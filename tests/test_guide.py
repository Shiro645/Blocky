"""The guide checklist: steps read from what players did, the reward paid once."""
from __future__ import annotations

from game import dummy, guide, players, reset, species
from game.notices import GuideProgress
from tests.helpers import DAY, GameTestCase

ALICE = 1


class GuideTests(GameTestCase):
    def progress(self) -> list[GuideProgress]:
        return [n for n in self.notices if isinstance(n, GuideProgress)]

    async def do_everything(self, uid: int) -> None:
        await self.run_game(players.bump_stat, uid, "blocks_mined", 3)
        await self.run_game(players.bump_stat, uid, "daily_claims")
        await self.run_game(players.bump_stat, uid, "emeralds_from_sales", 20)
        await self.run_game(species.choose, uid, "miner")
        await self.run_game(players.bump_stat, uid, "profiles_viewed")
        await self.run_game(dummy.hit_series, uid)

    async def test_steps_are_checked_as_they_are_done(self):
        await self.run_game(guide.opened, ALICE, 100, 200)
        state = await self.run_game(guide.overview, ALICE)
        self.assertEqual([ok for _, ok in state["steps"]], [False] * len(guide.STEPS))
        self.assertEqual(state["delete_at"], int(self.now + 30 * DAY))  # unfinished: deleted after expire_days

        await self.run_game(players.bump_stat, ALICE, "daily_claims")
        await self.run_game(players.bump_stat, ALICE, "daily_claims")  # nothing new the second time
        notes = self.progress()
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0].steps, notes[0].done, notes[0].completed, notes[0].channel_id, notes[0].message_id),
                         (("daily",), 1, False, 100, 200))

        self.notices.clear()
        await self.run_game(players.set_level, ALICE, 1)  # unrelated
        await self.run_game(species.choose, ALICE, "dwarf")  # not a stat: checked by species.choose itself
        self.assertEqual(self.progress()[0].steps, ("species",))

    async def test_the_reward_is_paid_once(self):
        await self.run_game(guide.opened, ALICE, 100, 200)
        await self.do_everything(ALICE)
        done = [n for n in self.progress() if n.completed]
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0].reward, done[0].done, done[0].total), (200, 6, 6))
        balance = await self.run_game(players.get_emeralds, ALICE)
        self.assertGreaterEqual(balance, 200)
        state = await self.run_game(guide.overview, ALICE)
        self.assertTrue(state["completed"] and state["rewarded"])
        self.assertEqual(state["delete_at"], int(self.now + 3 * DAY))  # finished: deleted after delete_after_days

        # The staff sends it again: everything is still done, nothing is paid twice.
        self.notices.clear()
        await self.run_game(guide.opened, ALICE, 101, 201)
        await self.run_game(players.bump_stat, ALICE, "blocks_mined")
        self.assertEqual(self.progress(), [])
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), balance)

    async def test_steps_done_before_count_and_can_finish_at_once(self):
        await self.do_everything(ALICE)  # before any guide: nothing is followed
        self.assertEqual(self.progress(), [])
        balance = await self.run_game(players.get_emeralds, ALICE)
        state = await self.run_game(guide.opened, ALICE, 100, 200)
        self.assertTrue(state["completed"])
        self.assertEqual([n.reward for n in self.progress()], [200])
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), balance + 200)

    async def test_channels_are_deleted_when_due(self):
        await self.run_game(guide.opened, ALICE, 100, 200)
        self.assertEqual(await self.run_game(guide.channels), {100: ALICE})
        self.assertEqual(await self.run_game(guide.due), [])
        self.advance(30 * DAY)
        self.assertEqual(await self.run_game(guide.due), [{"user_id": ALICE, "channel_id": 100}])
        self.assertEqual(await self.run_game(guide.closed, ALICE), 100)
        self.assertEqual(await self.run_game(guide.channels), {})
        self.assertIsNone(await self.run_game(guide.closed, ALICE))

        # Without a channel the checklist is still followed (/guide), and the reward reaches the player.
        await self.do_everything(ALICE)
        done = [n for n in self.progress() if n.completed]
        self.assertEqual((done[0].channel_id, done[0].reward), (None, 200))

    async def test_a_deleted_channel_is_forgotten(self):
        await self.run_game(guide.opened, ALICE, 100, 200)
        self.assertEqual(await self.run_game(guide.channel_deleted, 100), ALICE)
        self.assertIsNone(await self.run_game(guide.channel_deleted, 100))
        self.assertIsNone((await self.run_game(guide.overview, ALICE))["channel_id"])

    async def test_a_full_reset_starts_the_checklist_over(self):
        await self.run_game(guide.opened, ALICE, 100, 200)
        await self.do_everything(ALICE)
        await self.run_game(reset.apply, {"progress"}, ALICE)
        state = await self.run_game(guide.overview, ALICE)
        self.assertFalse(state["completed"] or state["rewarded"])
