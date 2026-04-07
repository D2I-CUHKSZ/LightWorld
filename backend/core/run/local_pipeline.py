"""Local document pipeline CLI entrypoint."""

import argparse
import json
import os
import traceback
from typing import List

from core.setting.settings import Config
from core.modules.graph.local_pipeline import LocalGraphPipeline, LocalPipelineOptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiroFish 本地多模态直读：文本/图片/视频 -> 证据块 -> 本体生成 -> 图谱构建" )
    parser.add_argument("--files", nargs="*", default=[], help="本地输入路径列表，支持 pdf/md/txt/markdown/jpg/png/webp/mp4/mov/mkv/avi")
    parser.add_argument("--files-from", default="", help="从文本文件读取路径（每行一个文件路径）")
    parser.add_argument("--simulation-requirement", required=True, help="模拟需求描述")
    parser.add_argument("--project-name", default="Local Pipeline Project", help="项目名称")
    parser.add_argument("--additional-context", default="", help="额外上下文（传给本体生成）")
    parser.add_argument("--graph-name", default="", help="图谱名称（默认使用项目名）")
    parser.add_argument("--chunk-size", type=int, default=Config.DEFAULT_CHUNK_SIZE, help=f"图谱分块大小，默认 {Config.DEFAULT_CHUNK_SIZE}")
    parser.add_argument("--chunk-overlap", type=int, default=Config.DEFAULT_CHUNK_OVERLAP, help=f"图谱分块重叠，默认 {Config.DEFAULT_CHUNK_OVERLAP}",)
    parser.add_argument("--batch-size", type=int, default=3, help="发送到 Zep 的批次大小，默认 3")

    parser.add_argument("--light-mode", action="store_true", help="启用轻量模式：压缩构图文本并限制分块数量")
    parser.add_argument("--light-text-max-chars", type=int, default=120000, help="light 模式下参与构图的最大文本长度，默认 120000",)
    parser.add_argument("--light-ontology-max-chars", type=int, default=80000,help="light 模式下每个文档参与本体生成的最大字符数，默认 80000")
    parser.add_argument("--light-max-chunks", type=int, default=120, help="light 模式下构图最多发送的文本块数，默认 120")
    parser.add_argument("--light-chunk-size", type=int, default=1200, help="light 模式下分块大小，默认 1200")
    parser.add_argument("--light-chunk-overlap", type=int, default=40, help="light 模式下分块重叠，默认 40")

    parser.add_argument("--output", default="", help="将结果写入 JSON 文件")
    return parser.parse_args()


def load_paths_from_file(list_file: str) -> List[str]:
    if not list_file: return []
    if not os.path.exists(list_file): raise FileNotFoundError(f"--files-from 文件不存在: {list_file}")

    paths: List[str] = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if not p or p.startswith("#"):
                continue
            paths.append(p)
    return paths


def print_step(message: str):
    print(f"[STEP] {message}")


def main() -> int:
    args = parse_args()

    file_paths = [os.path.abspath(p) for p in (list(args.files) + load_paths_from_file(args.files_from))]
    if not file_paths:
        raise ValueError("请通过 --files 或 --files-from 提供至少一个文档路径")

    opts = LocalPipelineOptions( 
        files=file_paths,
        simulation_requirement=args.simulation_requirement,
        project_name=args.project_name,
        additional_context=args.additional_context,
        graph_name=args.graph_name,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        batch_size=args.batch_size,
        light_mode=args.light_mode,
        light_text_max_chars=args.light_text_max_chars,
        light_ontology_max_chars=args.light_ontology_max_chars,
        light_max_chunks=args.light_max_chunks,
        light_chunk_size=args.light_chunk_size,
        light_chunk_overlap=args.light_chunk_overlap,
    )

    try:
        pipeline = LocalGraphPipeline()
        result = pipeline.run(opts, progress_callback=print_step)

        if args.output:
            out_path = os.path.abspath(args.output)
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print_step(f"结果已写入: {out_path}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print("[ERROR] 执行失败")
        print(str(e))
        print(traceback.format_exc())
        return 1
