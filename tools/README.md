# Checks

`python3 tools/check_all.py` runs everything before a push. Exit code 0 means all good.

It runs these checks:
- the tests;
- `tools/help_check.py`: loads every cog in a bot that never logs in, then renders every `/help` screen against Discord's limits. `home` or page names as arguments also print those screens.
- `tools/config_check.py`: builds every `/config` screen and saves a few values for real.
- `tools/wiki_check.py`: renders every wiki message. `--long-emojis` counts every emoji as a ~40-character custom emoji.

The checks need `discord.py` (`pip install -r requirements.txt`). Where it can't be installed, set `BLOCKY_DEPS` to a folder of unpacked pure-Python copies of the dependencies.

Each check runs in a fresh temporary folder, with a `config.json` made from `config.example.json`. It never touches the repo or a real database.
