"""Shared setup of the checks: the repo on the path, a scratch folder to run in, and stubs for what the checks
never use (Minecraft status, .env). discord.py must be installed (pip install -r requirements.txt); BLOCKY_DEPS
can point to a folder of unpacked dependencies instead (see tools/README.md)."""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

deps = os.environ.get("BLOCKY_DEPS")
if deps:  # pure-Python copies of the dependencies (no compiled extensions)
    for flag in ("AIOHTTP", "MULTIDICT", "YARL", "FROZENLIST", "PROPCACHE"):
        os.environ[f"{flag}_NO_EXTENSIONS"] = "1"
    sys.path[:0] = [f"{deps}/{p}" for p in ("aiohappyeyeballs/src", "attrs/src", "aiosignal", "frozenlist",
                                             "multidict", "propcache/src", "yarl", "idna", "aiohttp", "discord.py")]

sys.modules.setdefault("audioop", types.ModuleType("audioop"))
mcstatus = types.ModuleType("mcstatus")
mcstatus.JavaServer = object
sys.modules.setdefault("mcstatus", mcstatus)
try:
    import dotenv  # noqa: F401
except ImportError:
    stub = types.ModuleType("dotenv")
    stub.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = stub


def workdir() -> str:
    """A fresh folder to run in (a config.json and a database are made there, never in the repo)."""
    path = tempfile.mkdtemp(prefix="blocky-check-")
    os.chdir(path)
    cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    cfg["guild_id"] = 123
    Path(path, "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path
