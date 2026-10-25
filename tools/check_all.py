"""Every check before a push: the tests, then /help, /config and the wiki against Discord's limits.

python3 tools/check_all.py        (exit code 0 = all good)"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = [
    ("tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
    ("/help", [sys.executable, "tools/help_check.py"]),
    ("/config", [sys.executable, "tools/config_check.py"]),
    ("wiki", [sys.executable, "tools/wiki_check.py"]),
    ("wiki, custom emojis", [sys.executable, "tools/wiki_check.py", "--long-emojis"]),
]
failed = []
for name, cmd in STEPS:
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (res.stdout + res.stderr).strip().splitlines()
    print(f"{'✅' if res.returncode == 0 else '❌'} {name}: {out[-1] if out else ''}")
    if res.returncode != 0:
        failed.append(name)
        print("\n".join(out[-15:]))
sys.exit(1 if failed else 0)
