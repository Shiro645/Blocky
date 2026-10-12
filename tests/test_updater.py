"""The updater (updater/updater.py) on real git repositories, with a fake deploy command."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils import selfupdate

ROOT = Path(__file__).resolve().parent.parent
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "init.defaultBranch=main"]


def load_updater():
    spec = importlib.util.spec_from_file_location("blocky_updater", ROOT / "updater" / "updater.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@unittest.skipUnless(shutil.which("git"), "git is needed")
class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.git("init", "--bare", "-b", "main", str(self.tmp / "origin.git"))
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.tmp / "work"))  # "GitHub" side
        self.commit("bot.py", "print('v1')", "First version")
        self.git("-C", str(self.tmp / "work"), "push", "-q", "origin", "main")
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.tmp / "repo"))  # the NAS side
        self.shared = self.tmp / "shared"
        self.shared.mkdir()
        self.deployed = self.tmp / "deployed.txt"
        self.u = load_updater()
        self.u.REPO, self.u.SHARED = self.tmp / "repo", self.shared
        self.u.DEPLOY_CMD = f"sh {self.tmp / 'deploy.sh'}"
        self.deploy_script(0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args: str) -> str:
        return subprocess.run([*GIT, *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, name: str, content: str, title: str, where: str = "work") -> None:
        path = self.tmp / where / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.git("-C", str(self.tmp / where), "add", name)
        self.git("-C", str(self.tmp / where), "commit", "-q", "-m", title)

    def publish(self, name: str, content: str, title: str) -> None:
        self.commit(name, content, title)
        self.git("-C", str(self.tmp / "work"), "push", "-q", "origin", "main")

    def deploy_script(self, code: int) -> None:
        (self.tmp / "deploy.sh").write_text(f'echo "$1" >> {self.deployed}\necho "building $1"\nexit {code}\n')

    def ask(self, action: str) -> dict | None:
        rid = os.urandom(16).hex()
        path = self.shared / f"request-{rid}.json"
        path.write_text(json.dumps({"id": rid, "action": action}))
        res = self.u.handle(path)
        self.assertFalse(path.exists())
        if res is not None:
            self.assertEqual(json.loads((self.shared / f"result-{rid}.json").read_text()), res)
        return res

    def test_check_shows_what_is_new(self):
        res = self.ask("check")
        self.assertTrue(res["ok"])
        self.assertEqual((res["behind"], res["ahead"], res["branch"], res["commits"]), (0, 0, "main", []))
        self.publish("bot.py", "print('v2')", "Add the wiki")
        self.publish("README.md", "hi", "Announce updates")
        res = self.ask("check")
        self.assertEqual(res["behind"], 2)
        self.assertEqual([c.split(" ", 1)[1] for c in res["commits"]], ["Announce updates", "Add the wiki"])
        self.assertFalse(self.deployed.exists())  # a check never deploys
        (self.tmp / "repo" / "bot.py").write_text("edited by hand")
        self.assertEqual(self.ask("check")["dirty"], ["bot.py"])

    def test_update_pulls_then_rebuilds(self):
        self.publish("bot.py", "print('v2')", "Add the wiki")
        res = self.ask("update")
        self.assertTrue(res["ok"], res)
        self.assertNotEqual(res["before"], res["after"])
        self.assertEqual([c.split(" ", 1)[1] for c in res["commits"]], ["Add the wiki"])
        self.assertEqual((self.tmp / "repo" / "bot.py").read_text(), "print('v2')")
        self.assertEqual(self.deployed.read_text().split(), ["blocky"])
        self.assertFalse(res["self_update"])

    def test_a_changed_updater_rebuilds_itself_last(self):
        self.publish("updater/updater.py", "# v2", "Improve the updater")
        res = self.ask("update")
        self.assertTrue(res["ok"] and res["self_update"])
        self.assertEqual(self.deployed.read_text().split(), ["blocky", "blocky-updater"])

    def test_failures_are_reported(self):
        self.publish("bot.py", "print('v2')", "Add the wiki")
        self.deploy_script(1)
        res = self.ask("update")
        self.assertEqual((res["ok"], res["step"]), (False, "build"))
        self.assertIn("building blocky", res["error"])
        # Diverged: a local commit GitHub doesn't have. The pull refuses and nothing is rebuilt.
        self.deployed.unlink()
        self.commit("local.txt", "x", "Local change", where="repo")
        self.publish("bot.py", "print('v3')", "Another change")
        self.assertEqual(self.ask("check")["ahead"], 1)
        res = self.ask("update")
        self.assertEqual((res["ok"], res["step"]), (False, "pull"))
        self.assertFalse(self.deployed.exists())

    def test_bad_requests_are_dropped(self):
        for request in ({"id": "../../etc", "action": "check"}, {"id": "a" * 32, "action": "rm -rf /"}, "not json"):
            path = self.shared / "request-x.json"
            path.write_text(request if isinstance(request, str) else json.dumps(request))
            self.assertIsNone(self.u.handle(path))
            self.assertFalse(path.exists())
        self.assertEqual(list(self.shared.glob("result-*")), [])

    def test_the_bot_side(self):
        before = selfupdate.UPDATE_DIR
        self.addCleanup(setattr, selfupdate, "UPDATE_DIR", before)
        selfupdate.UPDATE_DIR = self.shared
        self.assertFalse(selfupdate.updater_alive())
        self.u.write_json(self.shared / "updater.json", {"alive": int(time.time())})
        self.assertTrue(selfupdate.updater_alive())
        self.assertFalse(selfupdate.updater_alive(time.time() + 120))
        rid = selfupdate.request("check")
        res = self.u.handle(self.shared / f"request-{rid}.json")
        self.assertEqual(selfupdate.result(rid), res)
        selfupdate.forget(rid)
        self.assertIsNone(selfupdate.result(rid))
