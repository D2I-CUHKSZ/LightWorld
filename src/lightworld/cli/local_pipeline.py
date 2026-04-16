"""Local document pipeline CLI entrypoint."""

import argparse
import json
import os
import traceback
from typing import Any, Dict, List

from lightworld.config.settings import Config
from lightworld.graph.local_graph_pipeline import LocalGraphPipeline, LocalPipelineOptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MicroWorld local multimodal ingest: text/image/video -> evidence chunks -> ontology -> graph"
    )
    parser.add_argument("--config", default="", help="Load local pipeline options from a JSON config file")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Local input paths; supports pdf/md/txt/markdown/jpg/png/webp/mp4/mov/mkv/avi",
    )
    parser.add_argument("--files-from", default=None, help="Read paths from a text file (one path per line)")
    parser.add_argument("--simulation-requirement", default=None, help="Simulation requirement description")
    parser.add_argument("--project-name", default=None, help="Project name")
    parser.add_argument("--additional-context", default=None, help="Extra context passed to ontology generation")
    parser.add_argument("--graph-name", default=None, help="Graph name (defaults to project name)")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help=f"Graph chunk size; default {Config.DEFAULT_CHUNK_SIZE}",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help=f"Graph chunk overlap; default {Config.DEFAULT_CHUNK_OVERLAP}",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="Batch size sent to Zep; default 3")

    parser.add_argument(
        "--light-mode",
        action="store_true",
        default=None,
        help="Enable light mode: compress graph text and cap chunk count",
    )
    parser.add_argument(
        "--light-text-max-chars",
        type=int,
        default=None,
        help="Max text length for graph building in light mode; default 120000",
    )
    parser.add_argument(
        "--light-ontology-max-chars",
        type=int,
        default=None,
        help="Max chars per document for ontology in light mode; default 80000",
    )
    parser.add_argument("--light-max-chunks", type=int, default=None, help="Max text chunks sent for graph in light mode; default 120")
    parser.add_argument("--light-chunk-size", type=int, default=None, help="Chunk size in light mode; default 1200")
    parser.add_argument("--light-chunk-overlap", type=int, default=None, help="Chunk overlap in light mode; default 40")

    parser.add_argument("--output", default=None, help="Write results to a JSON file")
    return parser.parse_args()


def load_paths_from_file(list_file: str) -> List[str]:
    if not list_file:
        return []
    if not os.path.exists(list_file):
        raise FileNotFoundError(f"--files-from file not found: {list_file}")

    paths: List[str] = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if not p or p.startswith("#"):
                continue
            paths.append(p)
    return paths


def load_json_config(config_path: str) -> Dict[str, Any]:
    if not config_path:
        return {}
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"--config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("--config must be a JSON object")
    return data


def _resolve_path(path: str, base_dir: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(base_dir, path))


def _config_value(cli_value: Any, config: Dict[str, Any], key: str, default: Any) -> Any:
    if cli_value is not None:
        return cli_value
    if key in config:
        return config[key]
    return default


def build_options(args: argparse.Namespace) -> tuple[LocalPipelineOptions, str]:
    config_path = os.path.abspath(args.config) if args.config else ""
    config = load_json_config(config_path)
    config_dir = os.path.dirname(config_path) if config_path else os.getcwd()

    config_files = config.get("files", []) or []
    if isinstance(config_files, str):
        config_files = [config_files]
    if not isinstance(config_files, list):
        raise ValueError("config.files must be a list of strings")

    cli_files = args.files or []
    file_paths = [_resolve_path(str(p), config_dir) for p in config_files]
    file_paths.extend(os.path.abspath(p) for p in cli_files)

    files_from_value = _config_value(args.files_from, config, "files_from", "")
    if files_from_value:
        file_paths.extend(load_paths_from_file(_resolve_path(str(files_from_value), config_dir)))

    # Deduplicate while preserving order
    deduped_paths: List[str] = []
    seen = set()
    for path in file_paths:
        abs_path = os.path.abspath(path)
        if abs_path in seen:
            continue
        seen.add(abs_path)
        deduped_paths.append(abs_path)

    if not deduped_paths:
        raise ValueError("Provide at least one document path via --files, --files-from, or --config")

    simulation_requirement = _config_value(
        args.simulation_requirement,
        config,
        "simulation_requirement",
        "",
    )
    if not simulation_requirement:
        raise ValueError("Provide simulation requirement via --simulation-requirement or config.simulation_requirement")

    if "multimodal_use_remote_analysis" in config:
        Config.MULTIMODAL_USE_REMOTE_ANALYSIS = bool(config["multimodal_use_remote_analysis"])

    opts = LocalPipelineOptions(
        files=deduped_paths,
        simulation_requirement=simulation_requirement,
        project_name=_config_value(args.project_name, config, "project_name", "Local Pipeline Project"),
        additional_context=_config_value(args.additional_context, config, "additional_context", ""),
        graph_name=_config_value(args.graph_name, config, "graph_name", ""),
        chunk_size=int(_config_value(args.chunk_size, config, "chunk_size", Config.DEFAULT_CHUNK_SIZE)),
        chunk_overlap=int(_config_value(args.chunk_overlap, config, "chunk_overlap", Config.DEFAULT_CHUNK_OVERLAP)),
        batch_size=int(_config_value(args.batch_size, config, "batch_size", 3)),
        light_mode=bool(_config_value(args.light_mode, config, "light_mode", False)),
        light_text_max_chars=int(_config_value(args.light_text_max_chars, config, "light_text_max_chars", 120000)),
        light_ontology_max_chars=int(_config_value(args.light_ontology_max_chars, config, "light_ontology_max_chars", 80000)),
        light_max_chunks=int(_config_value(args.light_max_chunks, config, "light_max_chunks", 120)),
        light_chunk_size=int(_config_value(args.light_chunk_size, config, "light_chunk_size", 1200)),
        light_chunk_overlap=int(_config_value(args.light_chunk_overlap, config, "light_chunk_overlap", 40)),
    )

    output_path = _config_value(args.output, config, "output", "")
    if output_path:
        output_path = _resolve_path(str(output_path), config_dir)

    return opts, output_path


def print_step(message: str):
    print(f"[STEP] {message}")


def main() -> int:
    args = parse_args()

    try:
        opts, output_path = build_options(args)
        pipeline = LocalGraphPipeline()
        result = pipeline.run(opts, progress_callback=print_step)

        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print_step(f"Results written to: {output_path}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print("[ERROR] Run failed")
        print(str(e))
        print(traceback.format_exc())
        return 1
