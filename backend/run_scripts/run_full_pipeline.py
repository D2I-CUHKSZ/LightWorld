"""Legacy full pipeline script wrapper.

Preferred command:
`uv run mirofish-full-run --config path/to/full_run.config.json`
"""

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.run.full_run import main


if __name__ == "__main__":
    sys.exit(main())
