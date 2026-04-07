"""Local document pipeline CLI entrypoint."""

import argparse
import json
import os
import traceback
from typing import Any, Dict, List

from app.setting.settings import Config
from app.modules.graph.local_pipeline import LocalGraphPipeline, LocalPipelineOptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MiroFish 本地多模态直读：文本/图片/视频 -> 证据块 -> 本体生成 -> 图谱构建"
    )
    parser.add_argument("--config", default="", help="从 JSON 配置文件读取本地管线参数")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="本地输入路径列表，支持 pdf/md/txt/markdown/jpg/png/webp/mp4/mov/mkv/avi",
    )
    parser.add_argument("--files-from", default=None, help="从文本文件读取路径（每行一个文件路径）")
    parser.add_argument("--simulation-requirement", default=None, help="模拟需求描述")
    parser.add_argument("--project-name", default=None, help="项目名称")
    parser.add_argument("--additional-context", default=None, help="额外上下文（传给本体生成）")
    parser.add_argument("--graph-name", default=None, help="图谱名称（默认使用项目名）")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help=f"图谱分块大小，默认 {Config.DEFAULT_CHUNK_SIZE}",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help=f"图谱分块重叠，默认 {Config.DEFAULT_CHUNK_OVERLAP}",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="发送到 Zep 的批次大小，默认 3")

    parser.add_argument(
        "--light-mode",
        action="store_true",
        default=None,
        help="启用轻量模式：压缩构图文本并限制分块数量",
    )
    parser.add_argument(
        "--light-text-max-chars",
        type=int,
        default=None,
        help="light 模式下参与构图的最大文本长度，默认 120000",
    )
    parser.add_argument(
        "--light-ontology-max-chars",
        type=int,
        default=None,
        help="light 模式下每个文档参与本体生成的最大字符数，默认 80000",
    )
    parser.add_argument("--light-max-chunks", type=int, default=None, help="light 模式下构图最多发送的文本块数，默认 120")
    parser.add_argument("--light-chunk-size", type=int, default=None, help="light 模式下分块大小，默认 1200")
    parser.add_argument("--light-chunk-overlap", type=int, default=None, help="light 模式下分块重叠，默认 40")

    parser.add_argument("--output", default=None, help="将结果写入 JSON 文件")
    return parser.parse_args()


def load_paths_from_file(list_file: str) -> List[str]:
    if not list_file:
        return []
    if not os.path.exists(list_file):
        raise FileNotFoundError(f"--files-from 文件不存在: {list_file}")

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
        raise FileNotFoundError(f"--config 文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("--config 内容必须是 JSON 对象")
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
        raise ValueError("config.files 必须是字符串列表")

    cli_files = args.files or []
    file_paths = [_resolve_path(str(p), config_dir) for p in config_files]
    file_paths.extend(os.path.abspath(p) for p in cli_files)

    files_from_value = _config_value(args.files_from, config, "files_from", "")
    if files_from_value:
        file_paths.extend(load_paths_from_file(_resolve_path(str(files_from_value), config_dir)))

    # 去重但保持顺序
    deduped_paths: List[str] = []
    seen = set()
    for path in file_paths:
        abs_path = os.path.abspath(path)
        if abs_path in seen:
            continue
        seen.add(abs_path)
        deduped_paths.append(abs_path)

    if not deduped_paths:
        raise ValueError("请通过 --files、--files-from 或 --config 提供至少一个文档路径")

    simulation_requirement = _config_value(
        args.simulation_requirement,
        config,
        "simulation_requirement",
        "",
    )
    if not simulation_requirement:
        raise ValueError("请通过 --simulation-requirement 或 config.simulation_requirement 提供模拟需求描述")

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
            print_step(f"结果已写入: {output_path}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print("[ERROR] 执行失败")
        print(str(e))
        print(traceback.format_exc())
        return 1
