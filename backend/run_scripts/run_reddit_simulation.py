"""Compatibility wrapper for the unified platform runner.

This keeps the historical script path working while delegating execution to the
new topology-aware runtime implemented in ``run_parallel_simulation.py``.
"""

import asyncio
import sys

from run_parallel_simulation import main as parallel_main


def main():
    if "--reddit-only" not in sys.argv and "--twitter-only" not in sys.argv:
        sys.argv.insert(1, "--reddit-only")
    return asyncio.run(parallel_main())


if __name__ == "__main__":
    sys.exit(main())
