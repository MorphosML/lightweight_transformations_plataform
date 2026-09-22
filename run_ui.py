#!/usr/bin/env python3
import sys
from pathlib import Path

# Ensure src/ is on python path
src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from openflow_ui.app import main

if __name__ == "__main__":
    main()

