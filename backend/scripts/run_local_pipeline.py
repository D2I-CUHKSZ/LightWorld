"""Legacy local pipeline script wrapper.

Kept for backward compatibility. Preferred command:
`uv run mirofish-local-pipeline ...`
"""

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.cli.local_pipeline import main


if __name__ == "__main__":
    sys.exit(main())
