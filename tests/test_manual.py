"""The /help manual: a page for every command, and pages that stay correct when the settings change.

discord.py isn't needed: the commands are read from the cogs' source code.
"""
from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from game import settings
from utils import manual

COGS = Path(__file__).resolve().parent.parent / "cogs"


@dataclass
class SlashCommand:
    name: str
    staff: bool
    params: list[str]
    described: dict[str, str] = field(default_factory=dict)


def _literal(node: ast.AST) -> str:
    try:
        return str(ast.literal_eval(node))
    except ValueError:
        return ast.unparse(node)  # f-strings and constants: not checked for length


def slash_commands() -> dict[str, SlashCommand]:
    """Every slash command defined in cogs/, found in the source code."""
    found: dict[str, SlashCommand] = {}
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        groups = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, "attr", "") == "Group":
                    kw = {k.arg: k.value for k in node.value.keywords}
                    groups[node.targets[0].id] = ast.literal_eval(kw["name"])
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name, staff, described = None, False, {}
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                func = deco.func
                if isinstance(func, ast.Attribute) and func.attr == "command":
                    kw = {k.arg: k.value for k in deco.keywords}
                    name = ast.literal_eval(kw["name"]) if "name" in kw else node.name
                    if isinstance(func.value, ast.Name) and func.value.id in groups:
                        name = f"{groups[func.value.id]} {name}"
                elif isinstance(func, ast.Attribute) and func.attr == "describe":
                    described.update({k.arg: _literal(k.value) for k in deco.keywords})
                elif isinstance(func, ast.Name) and func.id == "staff_only":
                    staff = True
            if name is not None:
                params = [a.arg for a in node.args.args[2:]]  # after self and interaction
                found[name] = SlashCommand(name, staff, params, described)
    return found


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commands = slash_commands()

    def setUp(self):
        settings.load()

    def tearDown(self):
        settings.load()

    def test_every_command_has_a_page(self):
        pages = {p.name for p in manual.PAGES if not p.is_topic}
        self.assertGreater(len(self.commands), 80)
        self.assertEqual(sorted(set(self.commands) - pages), [], "commands without a page in utils/manual.py")
        self.assertEqual(sorted(pages - set(self.commands)), [], "pages for commands that don't exist")
        self.assertEqual(len(manual.BY_NAME), len(manual.PAGES), "two pages with the same name")

    def test_staff_commands_are_in_staff_categories(self):
        for name, cmd in self.commands.items():
            with self.subTest(command=name):
                self.assertEqual(manual.BY_NAME[name].staff, cmd.staff)

    def test_every_option_is_described(self):
        for name, cmd in self.commands.items():
            for param in cmd.params:
                with self.subTest(command=name, option=param):
                    self.assertIn(param, cmd.described, "add it to @app_commands.describe")
                    self.assertLessEqual(len(cmd.described[param]), 100)  # Discord's limit

    def test_pages_are_well_formed(self):
        for page in manual.PAGES:
            with self.subTest(page=page.name):
                self.assertIn(page.category, manual.CATEGORIES)
                self.assertTrue(page.text)
                self.assertLessEqual(len(page.text), 2000)
                self.assertLessEqual(len(page.heading), 100)
                self.assertNotIn(page.name, page.related)
                for name in page.related:
                    self.assertIn(name, manual.BY_NAME)
                    if not page.staff:
                        self.assertFalse(manual.BY_NAME[name].staff, "a player page points to a staff page")
                for example in page.examples:
                    if not page.is_topic:
                        self.assertTrue(f"{example} ".startswith(f"/{page.name} "), example)
        for key in manual.CATEGORIES:
            self.assertTrue(1 <= len(manual.in_category(key)) <= 25, key)  # a select menu holds 25 options

    def test_values_follow_the_settings(self):
        for page in manual.PAGES:
            with self.subTest(page=page.name):
                for line in page.current_values(settings.get()):
                    self.assertIsInstance(line, str)
                    self.assertLessEqual(len(line), 400)
        mining = manual.BY_NAME["mining"]
        self.assertIn("**30 s**", mining.current_values(settings.get())[0])
        settings.load({"mining": {"cooldown_seconds": 15}, "boss": {"auto_spawn_hours": 72}})
        self.assertIn("**15 s**", mining.current_values(settings.get())[0])
        self.assertIn("every **72 h**", manual.BY_NAME["boss"].current_values(settings.get())[0])
        settings.load({"tournament": {"opens_day": 5, "opens_hour": 9}})
        self.assertIn("**Saturday 09:00**", manual.BY_NAME["tournament join"].current_values(settings.get())[0])

    def test_boss_challenge_hidden_without_automatic_bosses(self):
        lines = manual.BY_NAME["challenges"].current_values(settings.get())
        self.assertFalse(any("bosses" in line for line in lines))
        settings.load({"boss": {"auto_spawn_hours": 24}})
        lines = manual.BY_NAME["challenges"].current_values(settings.get())
        self.assertTrue(any("bosses" in line for line in lines))

    def test_find_and_search(self):
        self.assertEqual(manual.find("/Team  Create", staff=False).name, "team create")
        self.assertIsNone(manual.find("warn", staff=False))
        self.assertEqual(manual.find("warn", staff=True).name, "warn")
        self.assertIsNone(manual.find("nope", staff=True))
        names = [p.name for p in manual.search("team", staff=False)]
        self.assertEqual(names[0], "team create")
        self.assertNotIn("team_remove", names)
        self.assertIn("team_remove", [p.name for p in manual.search("team", staff=True)])
        self.assertIn("tournament join", [p.name for p in manual.search("join", staff=False)])
        self.assertFalse(any(p.staff for p in manual.search("", staff=False, limit=200)))
        self.assertNotIn("staff_server", manual.categories(staff=False))

    def test_formatting(self):
        self.assertEqual(manual.duration(90), "1 min 30 s")
        self.assertEqual(manual.duration(7200), "2 h")
        self.assertEqual(manual.duration(172800), "2 days")
        self.assertEqual(manual.pct(0.025), "2.5%")
        self.assertEqual(manual.num(1500), "1,500")
        self.assertEqual(manual.num(0.01), "0.01")
        self.assertEqual(manual.per_level([2, 4, 8]), "I 2 · II 4 · III 8")


if __name__ == "__main__":
    unittest.main()
