"""Minecraft quiz: a question with 4 answers; the first player to pick the right one wins.

Questions are about vanilla Minecraft (Java 1.21). The rewards count like the
other rewards (seasons, challenges).
"""
from __future__ import annotations

import random

from game import players, settings
from game.db import Ctx

# question, right answer, 3 wrong answers
QUESTIONS: tuple[tuple[str, str, tuple[str, str, str]], ...] = (
    ("How many obsidian blocks does the smallest Nether portal frame need (without corners)?", "10", ("14", "8", "12")),
    ("Which mob drops ender pearls?", "Enderman", ("Blaze", "Ghast", "Shulker")),
    ("Which pickaxe can mine obsidian?", "Diamond or netherite", ("Iron", "Stone", "Gold")),
    ("What do you give a wolf to tame it?", "A bone", ("Raw beef", "Wheat", "A carrot")),
    ("What do you give a cat to tame it?", "Raw cod or salmon", ("Milk", "String", "Wheat")),
    ("What does a pig become when lightning strikes it?", "A zombified piglin", ("A zombie", "A hoglin", "A charged pig")),
    ("What happens to a creeper struck by lightning?", "It becomes a charged creeper", ("It explodes at once", "It turns into a witch", "Nothing")),
    ("How many eyes of ender does it take to fill every frame of an End portal?", "12", ("8", "10", "16")),
    ("What is the highest level an enchanting table offers?", "30", ("50", "15", "40")),
    ("How many bookshelves does an enchanting table need for level 30 enchantments?", "15", ("12", "20", "9")),
    ("Which of these blocks can be part of a beacon pyramid?", "Block of Emerald", ("Block of Coal", "Block of Redstone", "Block of Lapis Lazuli")),
    ("Besides glass and obsidian, what do you need to craft a beacon?", "A Nether Star", ("A Heart of the Sea", "An Eye of Ender", "A Dragon Egg")),
    ("Which boss drops the Nether Star?", "The Wither", ("The Ender Dragon", "The Warden", "The Elder Guardian")),
    ("How many wither skeleton skulls are needed to summon the Wither?", "3", ("1", "4", "2")),
    ("How many soul sand or soul soil blocks does the Wither's T shape need?", "4", ("3", "5", "6")),
    ("What does a sponge absorb?", "Water", ("Lava", "Light", "Explosions")),
    ("What do you get by smelting sand?", "Glass", ("Sandstone", "Terracotta", "Glass pane")),
    ("What do you get by smelting cobblestone?", "Stone", ("Smooth stone", "Gravel", "Stone bricks")),
    ("What do you get by smelting a clay ball?", "A brick", ("Terracotta", "A flower pot", "A clay block")),
    ("What do you get by smelting a clay block?", "Terracotta", ("Bricks", "Glazed terracotta", "Concrete")),
    ("Which tool mines wool the fastest?", "Shears", ("An axe", "A sword", "A hoe")),
    ("Which of these mobs can you milk with a bucket?", "A cow", ("A pig", "A sheep", "A chicken")),
    ("What do you get by using a bowl on a mooshroom?", "Mushroom stew", ("Milk", "Beetroot soup", "Suspicious stew only")),
    ("In which dimension do you find ancient debris?", "The Nether", ("The End", "The Overworld", "The Deep Dark")),
    ("Around which height is ancient debris most common?", "Y = 15", ("Y = -58", "Y = 64", "Y = 100")),
    ("Since 1.18, around which height are diamonds most common?", "Y = -58", ("Y = 12", "Y = 64", "Y = 32")),
    ("How many netherite scraps are in a netherite ingot?", "4", ("9", "1", "8")),
    ("Besides netherite scraps, what goes into a netherite ingot?", "4 gold ingots", ("4 diamonds", "4 iron ingots", "4 blaze powder")),
    ("Since 1.20, what else do you need to turn diamond gear into netherite gear?", "A netherite upgrade smithing template",
     ("An anvil", "A blaze rod", "An enchanted book")),
    ("Which block sets your respawn point in the Nether?", "A respawn anchor", ("A bed", "A lodestone", "A beacon")),
    ("What happens when you try to sleep in a bed in the Nether?", "It explodes", ("You sleep normally", "Nothing", "You teleport home")),
    ("What does a ghast shoot?", "Fireballs", ("Arrows", "Wind charges", "Shulker bullets")),
    ("Which mob drops blaze rods?", "The blaze", ("The ghast", "The magma cube", "The strider")),
    ("What is the first ingredient of most potions (to make an Awkward Potion)?", "Nether wart", ("Glowstone dust", "Sugar", "Redstone dust")),
    ("What turns a potion into a splash potion?", "Gunpowder", ("Dragon's breath", "Redstone dust", "Glowstone dust")),
    ("What turns a splash potion into a lingering potion?", "Dragon's breath", ("Gunpowder", "Phantom membrane", "A fermented spider eye")),
    ("What makes a potion last longer?", "Redstone dust", ("Glowstone dust", "Sugar", "Gunpowder")),
    ("What makes a potion stronger (level II)?", "Glowstone dust", ("Redstone dust", "Blaze powder", "Nether wart")),
    ("What does a fermented spider eye do to a potion?", "It changes or reverses its effect", ("It makes it last longer", "It makes it splash", "Nothing")),
    ("Which ingredient brews a Potion of Fire Resistance?", "Magma cream", ("Blaze powder", "Ghast tear", "Sugar")),
    ("Which ingredient brews a Potion of Night Vision?", "A golden carrot", ("A glistering melon slice", "A spider eye", "A pufferfish")),
    ("Which ingredient brews a Potion of Water Breathing?", "A pufferfish", ("A turtle shell", "Kelp", "A sea pickle")),
    ("Which ingredient brews a Potion of Swiftness?", "Sugar", ("A rabbit's foot", "Blaze powder", "Phantom membrane")),
    ("Which ingredient brews a Potion of Healing?", "A glistering melon slice", ("A golden apple", "A ghast tear", "Honey")),
    ("Which ingredient brews a Potion of Strength?", "Blaze powder", ("Magma cream", "Glowstone dust", "A golden carrot")),
    ("Which ingredient brews a Potion of Leaping?", "A rabbit's foot", ("Slime", "Sugar", "A feather")),
    ("Which ingredient brews a Potion of Slow Falling?", "Phantom membrane", ("A feather", "A chorus fruit", "A shulker shell")),
    ("Which villager works at a lectern?", "The librarian", ("The cleric", "The cartographer", "The mason")),
    ("Which villager works at a composter?", "The farmer", ("The shepherd", "The butcher", "The fisherman")),
    ("Which villager works at a brewing stand?", "The cleric", ("The librarian", "The leatherworker", "The farmer")),
    ("Which villager works at a grindstone?", "The weaponsmith", ("The toolsmith", "The armorer", "The mason")),
    ("Which villager works at a stonecutter?", "The mason", ("The toolsmith", "The cartographer", "The armorer")),
    ("What do villagers use as money?", "Emeralds", ("Gold ingots", "Diamonds", "Iron ingots")),
    ("What do piglins accept in trade (bartering)?", "Gold ingots", ("Emeralds", "Gold nuggets", "Netherite scraps")),
    ("What does a villager become when lightning strikes it?", "A witch", ("A zombie villager", "An illager", "An iron golem")),
    ("How do you cure a zombie villager?", "Splash Potion of Weakness, then a golden apple",
     ("Feed it bread", "Splash Potion of Healing", "Let it burn in the sun")),
    ("How many gold ingots does a golden apple need?", "8", ("4", "9", "1")),
    ("How many ender pearls fit in one stack?", "16", ("64", "1", "32")),
    ("How long is a full Minecraft day in real time?", "20 minutes", ("10 minutes", "24 minutes", "1 hour")),
    ("Which block makes a bubble column that pushes you up?", "Soul sand", ("Magma block", "Prismarine", "Sea lantern")),
    ("Which helmet lets you breathe underwater longer?", "The turtle shell", ("The netherite helmet", "The golden helmet", "A carved pumpkin")),
    ("Which mob can drop a trident?", "The drowned", ("The guardian", "The elder guardian", "The pillager")),
    ("Which trident enchantment launches you with it in the rain?", "Riptide", ("Loyalty", "Channeling", "Impaling")),
    ("Which enchantment freezes water under your feet?", "Frost Walker", ("Depth Strider", "Aqua Affinity", "Feather Falling")),
    ("What does Mending use to repair items?", "Experience orbs", ("Lapis lazuli", "Iron ingots", "Emeralds")),
    ("Which bow enchantment can't be combined with Mending?", "Infinity", ("Power", "Punch", "Flame")),
    ("What does Silk Touch do?", "Mined blocks drop themselves", ("More drops from ores", "Faster mining", "No durability loss")),
    ("What is the highest level of Efficiency?", "V", ("III", "IV", "X")),
    ("What is the highest level of Protection?", "IV", ("III", "V", "II")),
    ("What is the highest level of Unbreaking?", "III", ("V", "IV", "II")),
    ("Which boss lives in the End?", "The Ender Dragon", ("The Wither", "The Warden", "The Elder Guardian")),
    ("Which block appears on the exit portal after the first Ender Dragon is killed?", "The dragon egg", ("A beacon", "A dragon head", "An end crystal")),
    ("Which item lets you glide?", "Elytra", ("A phantom membrane", "A feather", "A saddle")),
    ("Where do you find elytra?", "On End ships, in End cities", ("In ancient cities", "In bastions", "In woodland mansions")),
    ("What boosts your speed while gliding with elytra?", "Firework rockets", ("Wind charges", "Ender pearls", "Potions of Swiftness")),
    ("Which mob's projectiles make you levitate?", "The shulker", ("The ghast", "The breeze", "The phantom")),
    ("How does the Warden find players?", "It senses vibrations and smells: it's blind", ("It sees very far", "It hears only explosions", "It follows light")),
    ("Where can a Warden appear?", "In the Deep Dark", ("In the Nether", "In ocean monuments", "In trial chambers")),
    ("What does an allay do?", "It collects items that match the one you gave it", ("It attacks hostile mobs", "It heals you", "It mines ores")),
    ("What do you feed cows to breed them?", "Wheat", ("Carrots", "Seeds", "Hay bales")),
    ("What do you feed chickens to breed them?", "Seeds", ("Wheat", "Bread", "Beetroots")),
    ("What do you feed pandas to breed them?", "Bamboo", ("Sugar cane", "Sweet berries", "Apples")),
    ("What do you feed foxes to breed them?", "Sweet berries", ("Chicken", "Carrots", "Apples")),
    ("What do you feed llamas to breed them?", "Hay bales", ("Wheat", "Golden carrots", "Apples")),
    ("How do you take honeycomb from a bee nest without angering the bees?", "Use shears with a campfire under the nest",
     ("Hit the nest", "Use an axe at night", "Use a bucket")),
    ("What does a sniffer dig up?", "Ancient seeds", ("Diamonds", "Bones", "Suspicious sand")),
    ("What do you need to craft a bow?", "3 sticks and 3 string", ("2 sticks and 2 string", "3 sticks and 1 string", "1 stick and 3 string")),
    ("How many blocks can a redstone signal travel before it fades?", "15", ("16", "10", "64")),
    ("Which block can extend a redstone signal?", "A redstone repeater", ("A redstone comparator", "A lever", "A target block")),
    ("Which block sends a pulse when the block in front of it changes?", "An observer", ("A daylight detector", "A sculk sensor", "A hopper")),
    ("Which block can pull blocks back?", "A sticky piston", ("A piston", "A dispenser", "A dropper")),
    ("What does an enchanting table take besides XP levels?", "Lapis lazuli", ("Emeralds", "Redstone dust", "Diamonds")),
    ("What happens to a piglin brought into the Overworld?", "It turns into a zombified piglin", ("Nothing", "It burns", "It becomes a hoglin")),
    ("What can you wear so piglins don't attack you?", "A piece of golden armor", ("A carved pumpkin", "Leather armor", "Netherite armor")),
    ("Which update added axolotls?", "Caves & Cliffs", ("The Nether Update", "Buzzy Bees", "The Wild Update")),
    ("Which update added trial chambers?", "Tricky Trials (1.21)", ("Trails & Tales (1.20)", "The Wild Update (1.19)", "Caves & Cliffs (1.17)")),
    ("Which mob lives in trial chambers and shoots wind charges?", "The breeze", ("The blaze", "The vex", "The phantom")),
    ("What makes a mace hit harder?", "Falling before the hit", ("Sprinting", "Hitting from behind", "Being at full health")),
    ("Besides a breeze rod, what do you need to craft a mace?", "A heavy core", ("A netherite ingot", "An anvil", "A trial key")),
    ("What does a trial key open?", "A vault", ("A trial spawner", "A chest", "An iron door")),
    ("How do you get a froglight?", "A frog eats a small magma cube", ("Smelting glowstone", "Mining it in the Nether", "Crafting it from slime")),
    ("When do phantoms start appearing?", "After 3 nights without sleeping", ("Every full moon", "In the End", "When it rains")),
    ("Which mob drops the totem of undying?", "The evoker", ("The vindicator", "The witch", "The pillager")),
    ("What does a totem of undying do?", "It saves you from dying", ("It summons a golem", "It gives night vision", "It repels mobs")),
    ("Which ore drops lapis lazuli?", "Lapis lazuli ore", ("Redstone ore", "Diamond ore", "Emerald ore")),
    ("Which ore only generates in mountain biomes?", "Emerald ore", ("Gold ore", "Lapis lazuli ore", "Copper ore")),
    ("What do you use to wax copper so it stops oxidizing?", "Honeycomb", ("Slime", "Water", "An axe")),
    ("What removes the oxidation from copper?", "An axe", ("A pickaxe", "Water", "Honeycomb")),
)


def _cfg() -> dict:
    return settings.get()["games"]


def pick(rng: random.Random, recent: list[int]) -> int:
    """A question index, avoiding the recently asked ones."""
    fresh = [i for i in range(len(QUESTIONS)) if i not in recent]
    return rng.choice(fresh or list(range(len(QUESTIONS))))


def answers(rng: random.Random, index: int) -> tuple[list[str], int]:
    """The 4 answers in a random order, and the position of the right one."""
    _, right, wrong = QUESTIONS[index]
    options = [right, *wrong]
    rng.shuffle(options)
    return options, options.index(right)


def reward(ctx: Ctx, user_id: int) -> dict:
    """The winner of a question: emeralds (they count like the other rewards) and XP."""
    emeralds, xp = int(_cfg()["quiz_reward"]), int(_cfg()["quiz_xp"])
    players.earn_emeralds(ctx, user_id, emeralds)
    players.add_xp(ctx, user_id, xp)
    players.bump_stat(ctx, user_id, "quiz_wins")
    return {"emeralds": emeralds, "xp": xp}
