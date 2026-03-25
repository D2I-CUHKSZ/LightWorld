"""Parallel simulation CLI entrypoint.

This keeps compatibility with the existing script while providing a
standardized package-level command entry.
"""

import asyncio
import sys

from scripts.run_parallel_simulation import main as _async_main
from scripts.run_parallel_simulation import setup_signal_handlers


def main() -> int:
    setup_signal_handlers()
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        print("\n程序被中断")
    except SystemExit:
        pass
    finally:
        try:
            from multiprocessing import resource_tracker

            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("模拟进程已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
