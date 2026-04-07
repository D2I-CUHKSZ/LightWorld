
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.run.api import main


if __name__ == "__main__":
    sys.exit(main())
