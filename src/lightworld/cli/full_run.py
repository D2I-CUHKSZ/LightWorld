import argparse
from pathlib import Path
from lightworld.application.full_run_service import FullRunService
from lightworld.simulation.cluster_cli import (
    CLUSTER_METHOD_LLM_KEYWORD,
    CLUSTER_METHOD_THRESHOLD,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MicroWorld full pipeline runner")
    parser.add_argument("--config", required=True, help="Path to full-run config (JSON)")
    parser.add_argument(
        "--cluster-method",
        choices=[CLUSTER_METHOD_THRESHOLD, CLUSTER_METHOD_LLM_KEYWORD],
        default=None,
        help="Override cluster method for this run; if omitted, the interactive terminal prompts for choice.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = FullRunService()
    service.run(Path(args.config), cluster_method_override=args.cluster_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
