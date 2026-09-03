#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tools_diff import executer  # noqa: E402

raise SystemExit(executer("--strict" in sys.argv))
