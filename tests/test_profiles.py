"""Profile customization and team banners."""
from __future__ import annotations

from game import players, profiles, progress, teams
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class ProfileTests(GameTestCase):
    async def test_bio(self):
        self.assertEqual(await self.run_game(profiles.set_bio, ALICE, "  Je   mine donc je suis "), "Je mine donc je suis")
        with self.assertRaisesRegex(GameError, "150"):
            await self.run_game(profiles.set_bio, ALICE, "x" * 151)
        await self.run_game(profiles.set_bio, ALICE, None)
        self.assertIsNone((await self.run_game(profiles.get, ALICE))["bio"])

    async def test_colors_are_bought_once(self):
        await self.run_game(players.give_emeralds, ALICE, 2000)
        res = await self.run_game(profiles.set_color, ALICE, "lime")
        self.assertEqual(res["paid"], 300)
        await self.run_game(profiles.set_color, ALICE, "default")
        self.assertEqual((await self.run_game(profiles.set_color, ALICE, "lime"))["paid"], 0)  # kept for good
        res = await self.run_game(profiles.set_color, ALICE, "#FF8800")
        self.assertEqual((res["paid"], res["color"]), (1500, "#ff8800"))
        self.assertEqual((await self.run_game(profiles.set_color, ALICE, "123abc"))["paid"], 0)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 200)
        self.assertEqual(profiles.color_rgb("#123abc"), (0x12, 0x3A, 0xBC))
        with self.assertRaisesRegex(GameError, "Not enough"):
            await self.run_game(profiles.set_color, BOB, "red")
        with self.assertRaises(GameError):
            await self.run_game(profiles.set_color, ALICE, "rainbow")

    async def test_frames_sold_or_earned(self):
        await self.run_game(players.give_emeralds, ALICE, 500)
        frames = await self.run_game(profiles.frames_of, ALICE)
        self.assertEqual((frames["stone"], frames["netherite"]), ("price", "locked"))
        self.assertEqual((await self.run_game(profiles.set_frame, ALICE, "stone"))["paid"], 200)
        with self.assertRaisesRegex(GameError, "Win a weekend tournament"):
            await self.run_game(profiles.set_frame, ALICE, "netherite")
        await self.run_game(players.bump_stat, ALICE, "tournaments_won")
        self.assertEqual((await self.run_game(profiles.set_frame, ALICE, "netherite"))["paid"], 0)
        self.assertEqual((await self.run_game(profiles.get, ALICE))["frame"], "netherite")

    async def test_titles_earned_and_from_the_staff(self):
        with self.assertRaisesRegex(GameError, "Help defeat 10 bosses"):
            await self.run_game(profiles.set_title, ALICE, "boss_slayer")
        await self.run_game(players.bump_stat, ALICE, "bosses_defeated", 10)
        self.assertEqual(await self.run_game(profiles.set_title, ALICE, "boss_slayer"), "Boss Slayer")
        await self.run_game(profiles.give_title, ALICE, "The Architect")
        titles = await self.run_game(profiles.titles_of, ALICE)
        self.assertIn(("custom:The Architect", "The Architect"), titles)
        self.assertEqual(profiles.title_label((await self.run_game(profiles.get, ALICE))["title"]), "The Architect")
        await self.run_game(profiles.reset, ALICE, "title")
        self.assertNotIn(("custom:The Architect", "The Architect"), await self.run_game(profiles.titles_of, ALICE))

    async def test_showcase(self):
        await self.run_game(players.set_level, ALICE, 10)
        await self.run_game(progress.check_achievements, ALICE)
        with self.assertRaisesRegex(GameError, "only show achievements you unlocked"):
            await self.run_game(profiles.set_showcase, ALICE, ["champion"])
        self.assertEqual(await self.run_game(profiles.set_showcase, ALICE, ["level_10", "level_10"]), ["level_10"])


class BannerTests(GameTestCase):
    overrides = {"teams": {"create_cost": 0}}

    async def test_the_leader_sets_the_banner(self):
        team = await self.run_game(teams.create, ALICE, "Diamond Diggers", "DIG")
        await self.run_game(teams.invite, ALICE, BOB)
        await self.run_game(teams.accept, BOB, team["team_id"])
        await self.run_game(players.give_emeralds, ALICE, 300)
        with self.assertRaisesRegex(GameError, "Only a team leader"):
            await self.run_game(profiles.set_banner, BOB, "blue", [])
        with self.assertRaisesRegex(GameError, "3 patterns at most"):
            profiles.check_banner("blue", [("chevron", "yellow")] * 4)
        res = await self.run_game(profiles.set_banner, ALICE, "blue", [("chevron", "yellow"), ("border", "black")])
        self.assertEqual(res["paid"], 200)
        self.assertEqual(await self.run_game(profiles.banner_of, team["team_id"]),
                         {"base": "blue", "layers": [("chevron", "yellow"), ("border", "black")]})
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 100)
