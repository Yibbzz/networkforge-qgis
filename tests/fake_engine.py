"""A stand-in for the `networkforge` program, for fast tests.

It notes down the arguments it was given, then plays back the lines a
test prepared. Both files are named by environment variables:

  NF_FAKE_ARGS  where to write the arguments, as a JSON list
  NF_FAKE_PLAY  a JSON file: {"lines": [...], "exit": 0, "sleep": 0}
                (each line is printed as is; dicts are printed as JSON)
"""

import json
import os
import sys
import time

if os.environ.get("NF_FAKE_ARGS"):
    with open(os.environ["NF_FAKE_ARGS"], "w", encoding="utf-8") as f:
        json.dump(sys.argv[1:], f)

play = {}
if os.environ.get("NF_FAKE_PLAY"):
    with open(os.environ["NF_FAKE_PLAY"], encoding="utf-8") as f:
        play = json.load(f)

for line in play.get("lines", []):
    print(line if isinstance(line, str) else json.dumps(line), flush=True)
print("fake engine log line", file=sys.stderr, flush=True)
time.sleep(play.get("sleep", 0))
sys.exit(play.get("exit", 0))
