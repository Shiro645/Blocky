"""Blocky updater: pulls the Blocky repository and rebuilds the bot's container, on request.

It runs in its own small container (updater/Dockerfile, see the README): it is the only
part with access to Docker. The bot never gets it; it only drops requests in the folder
both containers share:

    request-<id>.json   {"id": <32 hex>, "action": "check" | "update"}   written by the bot
    result-<id>.json    the answer                                       written here
    updater.json        {"alive": <unix time>}                           the heartbeat

There are only these two fixed actions, and nothing in a request is ever run:
- check: git fetch, then what's new on the branch (commit titles), and warnings;
- update: git pull --ff-only, then `docker compose up -d --build --no-deps <bot service>`
  for the bot's own compose project (found from the labels of its container).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

SHARED = Path(os.environ.get("SHARED_DIR", "/shared"))
REPO = Path(os.environ.get("REPO_DIR", "/repo"))
BRANCH = os.environ.get("BRANCH", "main")
SERVICE = os.environ.get("SERVICE", "blocky")
UPDATER_SERVICE = os.environ.get("UPDATER_SERVICE", "blocky-updater")
DEPLOY_CMD = os.environ.get("DEPLOY_CMD")  # tests: a command run instead of docker compose
ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_COMMITS = 20
HEARTBEAT_SECONDS = 10


def run(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"{args[0]} took more than {timeout} s"
    except OSError as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout + p.stderr).strip()


def git(*args: str, timeout: int = 120) -> str:
    code, out = run(["git", "-C", str(REPO), *args], timeout=timeout)
    if code:
        raise RuntimeError(f"git {args[0]} failed: {out[-600:]}")
    return out


def commits(since: str, until: str) -> list[str]:
    out = git("log", "--no-merges", f"--max-count={MAX_COMMITS}", "--format=%h %s", f"{since}..{until}")
    return out.splitlines()


def check() -> dict:
    git("fetch", "--quiet", "origin", BRANCH, timeout=180)
    remote = f"origin/{BRANCH}"
    dirty = git("diff", "--name-only", "HEAD").splitlines()  # tracked files changed by hand
    return {
        "head": git("rev-parse", "--short", "HEAD"),
        "remote": git("rev-parse", "--short", remote),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "behind": int(git("rev-list", "--count", f"HEAD..{remote}")),
        "ahead": int(git("rev-list", "--count", f"{remote}..HEAD")),
        "commits": commits("HEAD", remote),
        "dirty": dirty[:10],
    }


def compose_base() -> list[str]:
    """`docker compose` for the bot's project: read from the labels of the bot's container."""
    code, out = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.service={SERVICE}"])
    ids = out.split() if code == 0 else []
    if ids:
        code, out = run(["docker", "inspect", "--format", "{{json .Config.Labels}}", ids[0]])
        if code == 0:
            labels = json.loads(out or "{}")
            project = labels.get("com.docker.compose.project")
            workdir = labels.get("com.docker.compose.project.working_dir")
            files = [f for f in (labels.get("com.docker.compose.project.config_files") or "").split(",") if f]
            if project and workdir:
                cmd = ["docker", "compose", "-p", project, "--project-directory", workdir]
                for f in files:
                    cmd += ["-f", f]
                return cmd
    return ["docker", "compose"]  # the compose project in the working directory


def deploy(service: str) -> tuple[int, str]:
    if DEPLOY_CMD:
        return run([*DEPLOY_CMD.split(), service], timeout=900)
    return run([*compose_base(), "up", "-d", "--build", "--no-deps", service], timeout=900)


def fix_owner() -> None:
    """Files pulled as root are given back to the owner of the repository."""
    st = REPO.stat()
    if st.st_uid != 0 and os.geteuid() == 0:
        run(["chown", "-R", f"{st.st_uid}:{st.st_gid}", str(REPO)])


def update() -> dict:
    before = git("rev-parse", "--short", "HEAD")
    try:
        git("pull", "--ff-only", "--quiet", "origin", BRANCH, timeout=300)
    except RuntimeError as exc:
        return {"ok": False, "step": "pull", "error": str(exc), "before": before}
    after = git("rev-parse", "--short", "HEAD")
    fix_owner()
    result = {"before": before, "after": after, "commits": commits(before, after) if before != after else [],
              "self_update": bool(before != after and git("diff", "--name-only", before, after, "--", "updater/"))}
    code, out = deploy(SERVICE)
    if code:
        return {"ok": False, "step": "build", "error": out[-1500:], **result}
    return {"ok": True, **result}


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def handle(path: Path) -> dict | None:
    """Answer one request (and delete it). Returns the result written, if any."""
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        request = {}
    path.unlink(missing_ok=True)
    rid, action = str(request.get("id", "")), request.get("action")
    if not ID_RE.match(rid) or action not in ("check", "update"):
        return None
    try:
        result = check() if action == "check" else update()
    except Exception as exc:  # noqa: BLE001 - every failure is reported to the bot
        result = {"ok": False, "step": action, "error": str(exc)[-1500:]}
    result.setdefault("ok", True)
    result.update(id=rid, action=action, at=int(time.time()))
    write_json(SHARED / f"result-{rid}.json", result)
    if action == "update" and result.get("ok") and result.get("self_update"):
        deploy(UPDATER_SERVICE)  # last: it restarts this container with the new updater
    return result


def clean(now: float) -> None:
    for path in SHARED.glob("result-*.json"):
        if now - path.stat().st_mtime > 86_400:
            path.unlink(missing_ok=True)


def main() -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    print(f"Blocky updater: {REPO} ({BRANCH}), service {SERVICE}, shared folder {SHARED}", flush=True)
    beat = 0.0
    while True:
        now = time.time()
        if now - beat >= HEARTBEAT_SECONDS:
            write_json(SHARED / "updater.json", {"alive": int(now)})
            clean(now)
            beat = now
        for path in sorted(SHARED.glob("request-*.json")):
            result = handle(path)
            if result is not None:
                print(f"{result['action']}: {'ok' if result['ok'] else result.get('error', '')[:200]}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
