"""2.2.6: the XP of a fight comes before its wear, so Mending only repairs what was worn before."""
from __future__ import annotations

from game import enchants, gear, night, players, settings, shop
from tests.test_night import ALICE, WEAK, NightTestCase


class MendingOrderTests(NightTestCase):
    async def mending_sword(self) -> int:
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        await self.run_game(enchants.set_enchants, sword, {"mending": 1})
        await self.run_game(gear.equip, ALICE, sword)
        return sword

    async def durability(self, gear_id: int) -> int:
        return await self.run_game(lambda ctx: ctx.one("SELECT durability FROM gear WHERE gear_id=?;", (gear_id,))[0])

    async def test_a_new_sword_keeps_the_fights_xp(self):
        settings.load(WEAK)
        sword = await self.mending_sword()
        full = await self.durability(sword)
        await self.to_slot(0)
        [a] = (await self.run_game(night.tick, [ALICE]))["spawned"]
        before = await self.run_game(players.get_user, ALICE)
        a = await self.run_game(night.fight, a["attack_id"], ALICE)
        after = await self.run_game(players.get_user, ALICE)
        xp = int(settings.get()["night"]["xp"])
        self.assertEqual(after["xp"] - before["xp"], xp)  # nothing went to Mending
        self.assertLess(await self.durability(sword), full)  # the fight wore it afterwards
        self.assertEqual(a["log"][-1], f"+{xp} XP")

    async def test_a_worn_sword_takes_some_and_says_so(self):
        sword = await self.mending_sword()
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability = durability - 6 WHERE gear_id=?;",
                                                    (sword,)))
        res = await self.run_game(players.add_xp, ALICE, 10)
        self.assertEqual(res["mended"], 3)  # 2 durability per XP
        self.assertEqual(players.xp_text(10, 3), "+7 XP (🔧 3 XP repaired your gear: Mending)")
