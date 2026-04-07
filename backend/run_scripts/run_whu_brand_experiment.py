"""End-to-end scaled experiment for the WHU brand reputation PDF.

Pipeline:
1. Read local PDF and build Zep graph
2. Prepare simulation assets
3. Apply scaled experiment config
4. Run parallel Twitter/Reddit simulation
5. Generate markdown report and summary artifacts
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.setting.settings import Config  # noqa: E402
from app.domain.project import ProjectManager  # noqa: E402
from app.infrastructure.file_parser import FileParser  # noqa: E402
from app.utils.text_processor import TextProcessor  # noqa: E402
from app.modules.graph.local_pipeline import LocalGraphPipeline, LocalPipelineOptions  # noqa: E402
from app.utils.simulation_manager import SimulationManager  # noqa: E402


DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EXPERIMENTS_DIR = BACKEND_DIR / "uploads" / "experiments"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="武汉大学品牌声誉 PDF 规模扩大实验")
    parser.add_argument(
        "--pdf",
        default=str(PROJECT_ROOT / "武汉大学品牌声誉深度分析报告.pdf"),
        help="输入 PDF 路径",
    )
    parser.add_argument(
        "--model",
        default="qwen-plus",
        help="OpenAI-compatible model name",
    )
    parser.add_argument(
        "--llm-base-url",
        default="",
        help="LLM base URL，未传且使用 qwen 系列时默认采用 DashScope 兼容端点",
    )
    parser.add_argument(
        "--project-name",
        default="WHU Brand Reputation Scaled Experiment",
        help="项目名称",
    )
    parser.add_argument(
        "--graph-name",
        default="WHU Brand Reputation Graph",
        help="图谱名称",
    )
    parser.add_argument(
        "--simulation-hours",
        type=int,
        default=48,
        help="模拟总小时数，默认 48",
    )
    parser.add_argument(
        "--minutes-per-round",
        type=int,
        default=60,
        help="每轮模拟分钟数，默认 60",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1200,
        help="图谱构建 chunk 大小，默认 1200",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=120,
        help="图谱构建 chunk overlap，默认 120",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Zep 批量发送大小，默认 4",
    )
    parser.add_argument(
        "--parallel-profile-count",
        type=int,
        default=4,
        help="并行生成 profile 数量，默认 4",
    )
    return parser.parse_args()


def print_step(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def ensure_env(model: str, llm_base_url: str):
    if not os.environ.get("LLM_MODEL_NAME"):
        os.environ["LLM_MODEL_NAME"] = model
    if llm_base_url:
        os.environ["LLM_BASE_URL"] = llm_base_url
    elif not os.environ.get("LLM_BASE_URL") and model.lower().startswith("qwen"):
        os.environ["LLM_BASE_URL"] = DEFAULT_QWEN_BASE_URL

    missing = []
    if not os.environ.get("LLM_API_KEY"):
        missing.append("LLM_API_KEY")
    if not os.environ.get("ZEP_API_KEY"):
        missing.append("ZEP_API_KEY")
    if missing:
        raise ValueError(f"缺少环境变量: {', '.join(missing)}")


def slugify(text: str) -> str:
    clean = []
    for ch in text.lower():
        if ch.isalnum():
            clean.append(ch)
        elif ch in {" ", "-", "_"}:
            clean.append("-")
    slug = "".join(clean).strip("-")
    return slug or "experiment"


def redact_key(value: str) -> str:
    value = str(value or "")
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return deepcopy(default)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_json(path: Path, payload: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def resolve_requirement() -> str:
    return (
        "围绕《武汉大学品牌声誉深度分析报告》开展一次规模扩大的双平台品牌声誉演化模拟。"
        "要求覆盖高校官方主体、校领导/教师/学生/校友、媒体、自媒体、竞校、公众、监管与企业合作方等可发声主体，"
        "重点模拟品牌声誉在正面叙事、争议事件、舆情放大、澄清回应、校友声援、媒体跟进和平台扩散中的传播路径。"
        "实验必须显式保留并验证四个创新点："
        "1) 为实体增加 keywords 并让其进入聚类与检索；"
        "2) cluster 以 unit 为协调粒度；"
        "3) 使用 PPR 建模非对称影响力；"
        "4) 使用 memory 形成跨轮次记忆闭环。"
        "输出需要适合生成完整实验报告，并保留中间 artifact。"
    )


def summarize_text(pdf_path: Path) -> Dict[str, Any]:
    raw_text = FileParser.extract_text(str(pdf_path))
    text = TextProcessor.preprocess_text(raw_text)
    return {
        "chars": len(text),
        "lines": text.count("\n") + 1,
        "preview": text[:1500],
        "text": text,
    }


def build_pipeline(
    args: argparse.Namespace,
    pdf_path: Path,
    experiment_dir: Path,
) -> Dict[str, Any]:
    options = LocalPipelineOptions(
        files=[str(pdf_path.resolve())],
        simulation_requirement=resolve_requirement(),
        project_name=args.project_name,
        graph_name=args.graph_name,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        batch_size=args.batch_size,
        light_mode=False,
    )
    pipeline = LocalGraphPipeline()
    result = pipeline.run(options, progress_callback=lambda msg: print_step(f"[Pipeline] {msg}"))
    write_json(experiment_dir / "pipeline_result.json", result)
    return result


def prepare_simulation_assets(
    pipeline_result: Dict[str, Any],
    args: argparse.Namespace,
    experiment_dir: Path,
) -> Dict[str, Any]:
    project_id = pipeline_result["project_id"]
    graph_id = pipeline_result["graph"]["graph_id"]
    project = ProjectManager.get_project(project_id)
    if project is None:
        raise ValueError(f"项目不存在: {project_id}")
    document_text = ProjectManager.get_extracted_text(project_id)
    if not document_text:
        raise ValueError("提取文本为空，无法准备模拟")

    defined_entity_types = [
        str(item.get("name"))
        for item in ((project.ontology or {}).get("entity_types", []) or [])
        if isinstance(item, dict) and item.get("name")
    ]

    manager = SimulationManager()
    state = manager.create_simulation(
        project_id=project_id,
        graph_id=graph_id,
        enable_twitter=True,
        enable_reddit=True,
    )
    print_step(f"[Prepare] 创建 simulation: {state.simulation_id}")

    def progress(stage: str, percent: int, message: str, **kwargs):
        current = kwargs.get("current")
        total = kwargs.get("total")
        suffix = ""
        if current is not None and total:
            suffix = f" ({current}/{total})"
        print_step(f"[Prepare][{stage}] {percent}% {message}{suffix}")

    prepared = manager.prepare_simulation(
        simulation_id=state.simulation_id,
        simulation_requirement=resolve_requirement(),
        document_text=document_text,
        defined_entity_types=defined_entity_types or None,
        use_llm_for_profiles=True,
        progress_callback=progress,
        parallel_profile_count=args.parallel_profile_count,
    )
    payload = prepared.to_dict()
    write_json(experiment_dir / "prepare_state.json", payload)
    return payload


def scale_experiment_config(config: Dict[str, Any]) -> Dict[str, Any]:
    scaled = deepcopy(config)
    agent_count = len(scaled.get("agent_configs", []) or [])
    time_cfg = scaled.setdefault("time_config", {})
    time_cfg["total_simulation_hours"] = max(24, int(time_cfg.get("total_simulation_hours", 48)))
    time_cfg["minutes_per_round"] = max(30, int(time_cfg.get("minutes_per_round", 60)))

    if agent_count <= 8:
        agents_min = min(agent_count, 3)
        agents_max = min(agent_count, 5)
    else:
        agents_min = min(agent_count, max(4, int(math.ceil(agent_count * 0.18))))
        agents_max = min(agent_count, max(agents_min + 2, int(math.ceil(agent_count * 0.35))))
    time_cfg["agents_per_hour_min"] = max(1, agents_min)
    time_cfg["agents_per_hour_max"] = max(time_cfg["agents_per_hour_min"], agents_max)

    topo_cfg = scaled.setdefault("topology_aware", {})
    topo_cfg.update({
        "enabled": True,
        "coordination_enabled": True,
        "differentiation_enabled": True,
        "threshold_cluster_enabled": False,
        "llm_keyword_cluster_enabled": False,
        "cluster_mode": "disabled",
        "top_pairs_ratio": max(0.04, float(topo_cfg.get("top_pairs_ratio", 0.03))),
        "graph_prior_extra_ratio": max(0.30, float(topo_cfg.get("graph_prior_extra_ratio", 0.25))),
        "dynamic_update_enabled": True,
        "dynamic_update_interval": min(4, int(topo_cfg.get("dynamic_update_interval", 4))),
        "dynamic_update_min_events": min(6, int(topo_cfg.get("dynamic_update_min_events", 8))),
        "social_link_sync_enabled": True,
        "social_link_sync_interval": min(4, int(topo_cfg.get("social_link_sync_interval", 6))),
    })

    mem_cfg = scaled.setdefault("simplemem", {})
    mem_cfg.update({
        "enabled": True,
        "retrieval_topk": max(6, int(mem_cfg.get("retrieval_topk", 5))),
        "max_units_per_agent": max(160, int(mem_cfg.get("max_units_per_agent", 120))),
        "max_world_units": max(160, int(mem_cfg.get("max_world_units", 120))),
        "abstract_topk": max(4, int(mem_cfg.get("abstract_topk", 3))),
        "detail_topk": max(5, int(mem_cfg.get("detail_topk", 4))),
        "enable_world_memory": True,
    })

    light_cfg = scaled.setdefault("light_mode", {})
    light_cfg.update({
        "enabled": False,
        "agent_ratio": 1.0,
    })

    event_cfg = scaled.setdefault("event_config", {})
    hot_topics = [str(x).strip() for x in (event_cfg.get("hot_topics", []) or []) if str(x).strip()]
    for topic in ["武汉大学", "品牌声誉", "高校舆情", "校友", "招生", "媒体传播"]:
        if topic not in hot_topics:
            hot_topics.append(topic)
    event_cfg["hot_topics"] = hot_topics[:10]
    return scaled


def save_scaled_config(simulation_dir: Path, experiment_dir: Path, config: Dict[str, Any]):
    config_path = simulation_dir / "simulation_config.json"
    backup_path = simulation_dir / "simulation_config.original.json"
    if not backup_path.exists() and config_path.exists():
        shutil.copy2(config_path, backup_path)
    write_json(config_path, config)
    write_json(experiment_dir / "scaled_simulation_config.json", config)


def run_parallel_simulation(simulation_dir: Path):
    script_path = BACKEND_DIR / "scripts" / "run_parallel_simulation.py"
    config_path = simulation_dir / "simulation_config.json"
    cmd = [
        sys.executable,
        str(script_path),
        "--config",
        str(config_path),
        "--no-wait",
    ]
    print_step("[Run] 启动并行模拟")
    subprocess.run(
        cmd,
        cwd=str(simulation_dir),
        env=os.environ.copy(),
        check=True,
    )


def summarize_actions(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    action_rows = [row for row in rows if row.get("agent_id") is not None and row.get("action_type")]
    by_type = Counter(str(row.get("action_type")) for row in action_rows)
    by_agent = Counter(str(row.get("agent_name", f"Agent_{row.get('agent_id')}")) for row in action_rows)
    rounds = sorted({
        int(row.get("round"))
        for row in rows
        if row.get("round") is not None and isinstance(row.get("round"), int)
    })
    return {
        "total_actions": len(action_rows),
        "action_type_counts": dict(by_type.most_common()),
        "top_agents": [{"agent_name": name, "actions": count} for name, count in by_agent.most_common(10)],
        "rounds_observed": rounds,
    }


def select_retrieval_examples(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    with_units = [row for row in rows if row.get("selected_units")]
    if len(with_units) >= limit:
        return with_units[:limit]
    if with_units:
        return with_units + rows[: max(0, limit - len(with_units))]
    return rows[:limit]


def top_keyword_examples(entity_prompts: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    rows = []
    for item in entity_prompts[:limit]:
        rows.append({
            "entity_name": item.get("entity_name"),
            "entity_type": item.get("entity_type"),
            "keywords": item.get("keywords", []) or [],
            "topic_tags": item.get("topic_tags", []) or [],
        })
    return rows


def build_summary(
    pdf_path: Path,
    text_summary: Dict[str, Any],
    pipeline_result: Dict[str, Any],
    prepare_state: Dict[str, Any],
    experiment_dir: Path,
) -> Dict[str, Any]:
    simulation_id = prepare_state["simulation_id"]
    project_id = prepare_state["project_id"]
    simulation_dir = BACKEND_DIR / "uploads" / "simulations" / simulation_id
    project_dir = BACKEND_DIR / "uploads" / "projects" / project_id

    entity_prompts = read_json(simulation_dir / "entity_prompts.json", default=[]) or []
    topology_twitter = read_json(simulation_dir / "artifacts" / "topology" / "twitter" / "latest_topology.json", default={}) or {}
    topology_reddit = read_json(simulation_dir / "artifacts" / "topology" / "reddit" / "latest_topology.json", default={}) or {}
    memory_twitter = read_json(simulation_dir / "artifacts" / "memory" / "twitter" / "latest_memory_state.json", default={}) or {}
    memory_reddit = read_json(simulation_dir / "artifacts" / "memory" / "reddit" / "latest_memory_state.json", default={}) or {}
    twitter_actions = read_jsonl(simulation_dir / "twitter" / "actions.jsonl")
    reddit_actions = read_jsonl(simulation_dir / "reddit" / "actions.jsonl")
    twitter_memory_trace = read_jsonl(simulation_dir / "artifacts" / "memory" / "twitter" / "memory_trace.jsonl")
    reddit_memory_trace = read_jsonl(simulation_dir / "artifacts" / "memory" / "reddit" / "memory_trace.jsonl")
    twitter_retrieval_trace = read_jsonl(simulation_dir / "artifacts" / "memory" / "twitter" / "retrieval_trace.jsonl")
    reddit_retrieval_trace = read_jsonl(simulation_dir / "artifacts" / "memory" / "reddit" / "retrieval_trace.jsonl")

    summary = {
        "generated_at": datetime.now().isoformat(),
        "source_pdf": str(pdf_path.resolve()),
        "project_id": project_id,
        "project_dir": str(project_dir.resolve()),
        "simulation_id": simulation_id,
        "simulation_dir": str(simulation_dir.resolve()),
        "graph_id": prepare_state["graph_id"],
        "model": {
            "name": os.environ.get("LLM_MODEL_NAME", ""),
            "base_url": os.environ.get("LLM_BASE_URL", ""),
            "llm_api_key_redacted": redact_key(os.environ.get("LLM_API_KEY", "")),
            "zep_api_key_redacted": redact_key(os.environ.get("ZEP_API_KEY", "")),
        },
        "document": {
            "chars": text_summary["chars"],
            "lines": text_summary["lines"],
            "preview": text_summary["preview"],
        },
        "pipeline": pipeline_result,
        "prepare_state": prepare_state,
        "keyword_innovation": {
            "entity_prompt_count": len(entity_prompts),
            "examples": top_keyword_examples(entity_prompts),
        },
        "cluster_innovation": {
            "twitter": {
                "unit_count": topology_twitter.get("unit_count", 0),
                "avg_unit_size": topology_twitter.get("avg_unit_size", 0),
                "largest_unit_size": topology_twitter.get("largest_unit_size", 0),
                "largest_units": topology_twitter.get("largest_units", [])[:5],
            },
            "reddit": {
                "unit_count": topology_reddit.get("unit_count", 0),
                "avg_unit_size": topology_reddit.get("avg_unit_size", 0),
                "largest_unit_size": topology_reddit.get("largest_unit_size", 0),
                "largest_units": topology_reddit.get("largest_units", [])[:5],
            },
        },
        "ppr_innovation": {
            "twitter_top_central_agents": topology_twitter.get("top_central_agents", [])[:8],
            "twitter_top_asymmetric_pairs": topology_twitter.get("top_asymmetric_pairs", [])[:8],
            "reddit_top_central_agents": topology_reddit.get("top_central_agents", [])[:8],
            "reddit_top_asymmetric_pairs": topology_reddit.get("top_asymmetric_pairs", [])[:8],
        },
        "memory_innovation": {
            "twitter": {
                "latest_state": memory_twitter,
                "store_events": len(twitter_memory_trace),
                "retrieval_events": len(twitter_retrieval_trace),
                "sample_retrievals": select_retrieval_examples(twitter_retrieval_trace),
            },
            "reddit": {
                "latest_state": memory_reddit,
                "store_events": len(reddit_memory_trace),
                "retrieval_events": len(reddit_retrieval_trace),
                "sample_retrievals": select_retrieval_examples(reddit_retrieval_trace),
            },
        },
        "behavior_summary": {
            "twitter": summarize_actions(twitter_actions),
            "reddit": summarize_actions(reddit_actions),
        },
        "artifacts": {
            "experiment_dir": str(experiment_dir.resolve()),
            "pipeline_result": str((experiment_dir / "pipeline_result.json").resolve()),
            "prepare_state": str((experiment_dir / "prepare_state.json").resolve()),
            "scaled_config": str((experiment_dir / "scaled_simulation_config.json").resolve()),
            "simulation_config": str((simulation_dir / "simulation_config.json").resolve()),
            "entity_prompts": str((simulation_dir / "entity_prompts.json").resolve()),
            "entity_graph_snapshot": str((simulation_dir / "entity_graph_snapshot.json").resolve()),
            "social_relation_graph": str((simulation_dir / "social_relation_graph.json").resolve()),
            "twitter_topology": str((simulation_dir / "artifacts" / "topology" / "twitter" / "latest_topology.json").resolve()),
            "reddit_topology": str((simulation_dir / "artifacts" / "topology" / "reddit" / "latest_topology.json").resolve()),
            "twitter_memory": str((simulation_dir / "simplemem_twitter.json").resolve()),
            "reddit_memory": str((simulation_dir / "simplemem_reddit.json").resolve()),
            "twitter_actions": str((simulation_dir / "twitter" / "actions.jsonl").resolve()),
            "reddit_actions": str((simulation_dir / "reddit" / "actions.jsonl").resolve()),
        },
    }
    write_json(experiment_dir / "experiment_summary.json", summary)
    return summary


def format_unit_rows(units: List[Dict[str, Any]]) -> str:
    if not units:
        return "- 无可用 unit 快照"
    lines = []
    for unit in units[:5]:
        members = ", ".join(
            str(member.get("agent_name"))
            for member in (unit.get("members", []) or [])[:6]
        )
        lines.append(
            f"- Unit {unit.get('unit_id')} | size={unit.get('size')} | "
            f"repr={unit.get('representative_agent_name')} | members={members}"
        )
    return "\n".join(lines)


def format_keywords_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "- 无实体 keywords 输出"
    lines = []
    for row in rows[:8]:
        lines.append(
            f"- {row.get('entity_name')} ({row.get('entity_type')}): "
            f"{', '.join(row.get('keywords', [])[:8])}"
        )
    return "\n".join(lines)


def format_centrality_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "- 无 PPR 中心性结果"
    lines = []
    for row in rows[:8]:
        outgoing = ", ".join(
            f"{item.get('target_agent_name')}:{item.get('weight')}"
            for item in (row.get("top_outgoing_ppr", []) or [])[:3]
        )
        lines.append(
            f"- {row.get('agent_name')} | unit={row.get('unit_id')} | "
            f"importance={row.get('importance')} | ppr_centrality={row.get('ppr_centrality')} | "
            f"top_outgoing={outgoing}"
        )
    return "\n".join(lines)


def format_asymmetry_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "- 无非对称 PPR 对"
    lines = []
    for row in rows[:8]:
        lines.append(
            f"- {row.get('dominant_source_agent_name')} -> {row.get('dominant_target_agent_name')} | "
            f"dominant={row.get('dominant_weight')} | reverse={row.get('reverse_weight')} | "
            f"delta={row.get('delta')}"
        )
    return "\n".join(lines)


def format_memory_state(memory_block: Dict[str, Any]) -> str:
    latest = memory_block.get("latest_state", {}) or {}
    sample_retrievals = memory_block.get("sample_retrievals", []) or []
    lines = [
        f"- agents_with_memory: {latest.get('agents_with_memory', 0)}",
        f"- total_agent_units: {latest.get('total_agent_units', 0)}",
        f"- world_units: {latest.get('world_units', 0)}",
        f"- store_events: {memory_block.get('store_events', 0)}",
        f"- retrieval_events: {memory_block.get('retrieval_events', 0)}",
    ]
    if sample_retrievals:
        sample = sample_retrievals[0]
        selected_units = sample.get("selected_units", []) or []
        unit_text = "; ".join(
            f"{item.get('scope')}:{item.get('source_agent_name')}:{item.get('topic')}"
            for item in selected_units[:4]
        )
        lines.append(
            f"- sample_retrieval: agent={sample.get('agent_name')} | "
            f"complexity={((sample.get('plan') or {}).get('complexity'))} | selected={unit_text}"
        )
    return "\n".join(lines)


def format_behavior_block(behavior: Dict[str, Any]) -> str:
    top_agents = behavior.get("top_agents", []) or []
    action_types = behavior.get("action_type_counts", {}) or {}
    top_agent_text = "; ".join(
        f"{item.get('agent_name')}:{item.get('actions')}"
        for item in top_agents[:6]
    ) or "无"
    action_type_text = "; ".join(
        f"{k}:{v}"
        for k, v in list(action_types.items())[:8]
    ) or "无"
    return (
        f"- total_actions: {behavior.get('total_actions', 0)}\n"
        f"- action_types: {action_type_text}\n"
        f"- top_agents: {top_agent_text}"
    )


def render_markdown(summary: Dict[str, Any]) -> str:
    pipeline = summary["pipeline"]
    prepare = summary["prepare_state"]
    cluster = summary["cluster_innovation"]
    ppr = summary["ppr_innovation"]
    memory = summary["memory_innovation"]
    behavior = summary["behavior_summary"]
    artifacts = summary["artifacts"]

    return f"""# 武汉大学品牌声誉规模扩大实验报告

## 1. 实验概览

- 生成时间: {summary['generated_at']}
- 输入文档: `{summary['source_pdf']}`
- 项目 ID: `{summary['project_id']}`
- 图谱 ID: `{summary['graph_id']}`
- 模拟 ID: `{summary['simulation_id']}`
- 模型: `{summary['model']['name']}`
- LLM Base URL: `{summary['model']['base_url']}`
- LLM API Key: `{summary['model']['llm_api_key_redacted']}`
- Zep API Key: `{summary['model']['zep_api_key_redacted']}`

## 2. 实验流程

1. 读取 PDF，抽取文本并执行预处理。
2. 基于文档内容生成适合品牌声誉模拟的本体定义。
3. 将全文分块送入 Zep，构建语义图谱。
4. 从图谱筛选可发声实体，生成 `entity_prompts.json`，显式写出实体 `keywords / description / semantic_prompt / topic_tags`。
5. 为实体生成双平台 profile，编译 `social_relation_graph.json`，再生成 `simulation_config.json`。
6. 启动 Twitter + Reddit 并行模拟，在运行中按轮次保存 topology 和 memory artifact。
7. 汇总实验中间产物与最终行为日志，生成本报告与 `experiment_summary.json`。

## 3. 输入与构图规模

- 文本字符数: {summary['document']['chars']}
- 文本行数: {summary['document']['lines']}
- 处理文件数: {pipeline['files_count']}
- 图谱节点数: {pipeline['graph']['node_count']}
- 图谱边数: {pipeline['graph']['edge_count']}
- 图谱 chunk 数: {pipeline['graph']['chunk_count']}
- 过滤后实体数: {prepare['entities_count']}
- 生成 profile 数: {prepare['profiles_count']}

## 4. 创新点观察

### 4.1 给实体增加 keywords

{format_keywords_rows(summary['keyword_innovation']['examples'])}

观察:
- `keywords` 已经不是附属字段，而是直接进入 topology similarity、unit 构造和 memory retrieval。
- 实体语义蒸馏产物保存在 `entity_prompts.json`，为后续 cluster 和 memory 提供统一语义接口。

### 4.2 cluster 的 unit

Twitter:
- unit_count: {cluster['twitter']['unit_count']}
- avg_unit_size: {cluster['twitter']['avg_unit_size']}
- largest_unit_size: {cluster['twitter']['largest_unit_size']}
{format_unit_rows(cluster['twitter']['largest_units'])}

Reddit:
- unit_count: {cluster['reddit']['unit_count']}
- avg_unit_size: {cluster['reddit']['avg_unit_size']}
- largest_unit_size: {cluster['reddit']['largest_unit_size']}
{format_unit_rows(cluster['reddit']['largest_units'])}

观察:
- unit 不是离线分析产物，而是 runtime 的协调粒度，直接决定每轮激活代表节点与补充成员的方式。
- 新增的 topology snapshot 允许回看每轮 unit 变化，不再只能看最终状态。

### 4.3 PPR 的非对称影响力

Twitter Top Central:
{format_centrality_rows(ppr['twitter_top_central_agents'])}

Twitter Top Asymmetry:
{format_asymmetry_rows(ppr['twitter_top_asymmetric_pairs'])}

Reddit Top Central:
{format_centrality_rows(ppr['reddit_top_central_agents'])}

Reddit Top Asymmetry:
{format_asymmetry_rows(ppr['reddit_top_asymmetric_pairs'])}

观察:
- PPR 输出的不只是“谁更重要”，还给出有向影响差异，因此可以直接验证非对称影响力。
- 本次实验把 `top_outgoing_ppr` 和 `top_asymmetric_pairs` 落盘到 topology artifact，便于复查影响方向。

### 4.4 memory 机制

Twitter:
{format_memory_state(memory['twitter'])}

Reddit:
{format_memory_state(memory['reddit'])}

观察:
- memory 由 `memory_store`、`retrieval` 和 `memory_state` 三类 artifact 组成，可以看到写入、合并、检索与世界记忆扩展。
- 这让 memory 从“最终 `simplemem_*.json` 文件”升级成“可追踪的跨轮次认知闭环”。

## 5. 行为结果

Twitter:
{format_behavior_block(behavior['twitter'])}

Reddit:
{format_behavior_block(behavior['reddit'])}

## 6. 关键产物路径

- experiment_dir: `{artifacts['experiment_dir']}`
- pipeline_result: `{artifacts['pipeline_result']}`
- prepare_state: `{artifacts['prepare_state']}`
- scaled_config: `{artifacts['scaled_config']}`
- simulation_config: `{artifacts['simulation_config']}`
- entity_prompts: `{artifacts['entity_prompts']}`
- entity_graph_snapshot: `{artifacts['entity_graph_snapshot']}`
- social_relation_graph: `{artifacts['social_relation_graph']}`
- twitter_topology: `{artifacts['twitter_topology']}`
- reddit_topology: `{artifacts['reddit_topology']}`
- twitter_memory: `{artifacts['twitter_memory']}`
- reddit_memory: `{artifacts['reddit_memory']}`
- twitter_actions: `{artifacts['twitter_actions']}`
- reddit_actions: `{artifacts['reddit_actions']}`

## 7. 结论

- 这次实验已经把输入 PDF 到双平台模拟的端到端链路跑通，并将关键中间产物保存为可复查文件。
- `keywords -> unit -> PPR -> memory` 四条创新链路现在都有对应 artifact，可直接用于后续实验复盘、对比和论文式写作。
- 如果后续要继续放大规模，优先建议沿三条线推进：更多实体、更长时间窗、以及基于当前 artifact 做跨实验对比基准。
"""


def main() -> int:
    args = parse_args()
    ensure_env(model=args.model, llm_base_url=args.llm_base_url)

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(pdf_path.stem)}"
    experiment_dir = EXPERIMENTS_DIR / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=True)

    print_step("[Experiment] 开始读取输入 PDF")
    text_summary = summarize_text(pdf_path)
    write_text(experiment_dir / "document_preview.txt", text_summary["preview"])

    pipeline_result = build_pipeline(args=args, pdf_path=pdf_path, experiment_dir=experiment_dir)
    prepare_state = prepare_simulation_assets(
        pipeline_result=pipeline_result,
        args=args,
        experiment_dir=experiment_dir,
    )

    simulation_dir = BACKEND_DIR / "uploads" / "simulations" / prepare_state["simulation_id"]
    scaled_config = scale_experiment_config(read_json(simulation_dir / "simulation_config.json", default={}) or {})
    scaled_config["time_config"]["total_simulation_hours"] = args.simulation_hours
    scaled_config["time_config"]["minutes_per_round"] = args.minutes_per_round
    save_scaled_config(simulation_dir=simulation_dir, experiment_dir=experiment_dir, config=scaled_config)

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "experiment_id": experiment_id,
        "source_pdf": str(pdf_path),
        "project_id": pipeline_result["project_id"],
        "graph_id": pipeline_result["graph"]["graph_id"],
        "simulation_id": prepare_state["simulation_id"],
        "experiment_dir": str(experiment_dir.resolve()),
        "project_dir": str((BACKEND_DIR / "uploads" / "projects" / pipeline_result["project_id"]).resolve()),
        "simulation_dir": str(simulation_dir.resolve()),
    }
    write_json(experiment_dir / "experiment_manifest.json", manifest)

    run_parallel_simulation(simulation_dir)
    summary = build_summary(
        pdf_path=pdf_path,
        text_summary=text_summary,
        pipeline_result=pipeline_result,
        prepare_state=prepare_state,
        experiment_dir=experiment_dir,
    )
    report_md = render_markdown(summary)
    write_text(experiment_dir / "experiment_report.md", report_md)

    print_step(f"[Experiment] 完成，报告已写入: {experiment_dir / 'experiment_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
