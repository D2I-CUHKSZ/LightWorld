"""Legacy API entrypoint wrapper.

Kept for backward compatibility. Preferred command:
`uv run mirofish-api`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cli.api import main


if __name__ == "__main__":
    sys.exit(main())
