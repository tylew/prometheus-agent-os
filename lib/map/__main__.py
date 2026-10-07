# ---
# name: map.__main__
# description: Entry point so `python3 -m map` (from lib/) and `python3 lib/map` both run the map.
# usage: python3 lib/map [--unit <workspace_id>] [--dump | --split]
# ---
# Ported from Horchestra (https://github.com/SimoneDaniotti/horchestra),
# MIT License, Copyright (c) 2026 Simone Daniotti.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from map.app import main  # noqa: E402

sys.exit(main())
