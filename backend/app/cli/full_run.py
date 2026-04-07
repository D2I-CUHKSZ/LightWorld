"""End-to-end local pipeline runner.

Run order:
1. Local multimodal pipeline
2. Simulation preparation
3. Parallel Twitter/Reddit simulation
4. Optional report generation
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.application.report_agent import ReportAgent, ReportManager, ReportStatus
from app.application.simulation_manager import SimulationManager
from app.core.settings import Config
from app.domain.project import ProjectManager
from app.modules.graph.local_pipeline import LocalGraphPipeline, LocalPipelineOptions


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
FULL_RUNS_DIR = BACKEND_DIR / "uploads" / "full_runs"
LATEST_MANIFEST_PATH = FULL_RUNS_DIR / "latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiroFish 一键全流程运行器")
    parser.add_argument("--config", required=True, help="全流程配置文件路径（JSON）")
    return parser.parse_args()


def print_step(message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 JSON 对象: {path}")
    return data


def write_json(path: Path, payload: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def resolve_path(path: str, base_dir: Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def load_paths_from_file(list_file: Path) -> List[Path]:
    if not list_file.exists():
        raise FileNotFoundError(f"文件列表不存在: {list_file}")

    paths: List[Path] = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            paths.append(resolve_path(item, list_file.parent))
    return paths


def slugify(text: str) -> str:
    chars: List[str] = []
    for ch in str(text).strip().lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_"}:
            chars.append("-")
    slug = "".join(chars).strip("-")
    return slug or "run"


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def ensure_runtime_env():
    runtime_pairs = {
        "LLM_API_KEY": Config.LLM_API_KEY,
        "LLM_BASE_URL": Config.LLM_BASE_URL,
        "LLM_MODEL_NAME": Config.LLM_MODEL_NAME,
        "ZEP_API_KEY": Config.ZEP_API_KEY,
    }
    for env_key, env_value in runtime_pairs.items():
        if env_value and not os.environ.get(env_key):
            os.environ[env_key] = str(env_value)

    if os.environ.get("LLM_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL") and not os.environ.get("OPENAI_API_BASE_URL"):
        os.environ["OPENAI_API_BASE_URL"] = os.environ["LLM_BASE_URL"]


def collect_input_files(config: Dict[str, Any], config_dir: Path) -> List[str]:
    files_value = config.get("files", []) or []
    if isinstance(files_value, str):
        files_value = [files_value]
    if not isinstance(files_value, list):
        raise ValueError("config.files 必须是字符串列表")

    file_paths = [str(resolve_path(str(item), config_dir)) for item in files_value]

    files_from = config.get("files_from", "")
    if files_from:
        file_paths.extend(
            str(path) for path in load_paths_from_file(resolve_path(str(files_from), config_dir))
        )

    deduped: List[str] = []
    seen = set()
    for path in file_paths:
        abs_path = str(Path(path).resolve())
        if abs_path in seen:
            continue
        seen.add(abs_path)
        deduped.append(abs_path)
    return deduped


def build_pipeline_options(config: Dict[str, Any], files: List[str]) -> LocalPipelineOptions:
    pipeline_cfg = config.get("pipeline", {}) or {}
    return LocalPipelineOptions(
        files=files,
        simulation_requirement=str(config.get("simulation_requirement", "") or "").strip(),
        project_name=str(config.get("project_name", "LightWorld Local Run") or "LightWorld Local Run"),
        additional_context=str(config.get("additional_context", "") or ""),
        graph_name=str(config.get("graph_name", "") or ""),
        chunk_size=int(pipeline_cfg.get("chunk_size", Config.DEFAULT_CHUNK_SIZE)),
        chunk_overlap=int(pipeline_cfg.get("chunk_overlap", Config.DEFAULT_CHUNK_OVERLAP)),
        batch_size=int(pipeline_cfg.get("batch_size", 3)),
        light_mode=bool(pipeline_cfg.get("light_mode", False)),
        light_text_max_chars=int(pipeline_cfg.get("light_text_max_chars", 120000)),
        light_ontology_max_chars=int(pipeline_cfg.get("light_ontology_max_chars", 80000)),
        light_max_chunks=int(pipeline_cfg.get("light_max_chunks", 120)),
        light_chunk_size=int(pipeline_cfg.get("light_chunk_size", 1200)),
        light_chunk_overlap=int(pipeline_cfg.get("light_chunk_overlap", 40)),
    )


def create_run_dir(config: Dict[str, Any], config_path: Path) -> Path:
    configured_output_dir = str(config.get("output_dir", "") or "").strip()
    if configured_output_dir:
        run_dir = resolve_path(configured_output_dir, config_path.parent)
    else:
        run_name = str(config.get("project_name", "") or config_path.stem)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = FULL_RUNS_DIR / f"run_{timestamp}_{slugify(run_name)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def remove_path(path: Path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def expose_artifact(target: Path, exposed_path: Path) -> str:
    if not target.exists():
        return ""

    exposed_path.parent.mkdir(parents=True, exist_ok=True)
    remove_path(exposed_path)

    try:
        relative_target = os.path.relpath(str(target), start=str(exposed_path.parent))
        os.symlink(relative_target, str(exposed_path))
    except OSError:
        if target.is_dir():
            shutil.copytree(target, exposed_path)
        else:
            shutil.copy2(target, exposed_path)

    return str(exposed_path.absolute())


def prepare_simulation_assets(
    pipeline_result: Dict[str, Any],
    config: Dict[str, Any],
    run_dir: Path,
) -> Dict[str, Any]:
    project_id = str(pipeline_result["project_id"])
    graph_id = str((pipeline_result.get("graph") or {}).get("graph_id") or "")
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

    sim_cfg = config.get("simulation", {}) or {}
    manager = SimulationManager()
    state = manager.create_simulation(
        project_id=project_id,
        graph_id=graph_id,
        enable_twitter=bool(sim_cfg.get("enable_twitter", True)),
        enable_reddit=bool(sim_cfg.get("enable_reddit", True)),
    )
    print_step(f"[Prepare] 创建 simulation: {state.simulation_id}")

    def progress(stage: str, percent: int, message: str, **kwargs):
        current = kwargs.get("current")
        total = kwargs.get("total")
        suffix = f" ({current}/{total})" if current is not None and total else ""
        print_step(f"[Prepare][{stage}] {percent}% {message}{suffix}")

    prepared = manager.prepare_simulation(
        simulation_id=state.simulation_id,
        simulation_requirement=project.simulation_requirement or str(config.get("simulation_requirement", "")),
        document_text=document_text,
        defined_entity_types=defined_entity_types or None,
        use_llm_for_profiles=bool(sim_cfg.get("use_llm_for_profiles", True)),
        progress_callback=progress,
        parallel_profile_count=int(sim_cfg.get("parallel_profile_count", 3)),
    )

    payload = prepared.to_dict()
    write_json(run_dir / "prepare_state.json", payload)
    return payload


def apply_simulation_config_overrides(simulation_dir: Path, run_dir: Path, config: Dict[str, Any]):
    config_path = simulation_dir / "simulation_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"simulation_config.json 不存在: {config_path}")

    simulation_cfg = config.get("simulation", {}) or {}
    config_overrides = simulation_cfg.get("config_overrides", {}) or {}
    current_config = read_json(config_path)

    if config_overrides:
        backup_path = simulation_dir / "simulation_config.original.json"
        if not backup_path.exists():
            shutil.copy2(config_path, backup_path)
        current_config = deep_merge(current_config, config_overrides)
        write_json(config_path, current_config)

    write_json(run_dir / "simulation_config.final.json", current_config)


def run_parallel_simulation(simulation_dir: Path, config: Dict[str, Any]):
    run_cfg = config.get("run", {}) or {}
    script_path = BACKEND_DIR / "scripts" / "run_parallel_simulation.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--config",
        str(simulation_dir / "simulation_config.json"),
    ]

    if bool(run_cfg.get("twitter_only", False)):
        cmd.append("--twitter-only")
    if bool(run_cfg.get("reddit_only", False)):
        cmd.append("--reddit-only")
    if bool(run_cfg.get("no_wait", True)):
        cmd.append("--no-wait")
    if bool(run_cfg.get("light_mode", False)):
        cmd.append("--light-mode")
    if bool(run_cfg.get("topology_aware", False)):
        cmd.append("--topology-aware")

    max_rounds = run_cfg.get("max_rounds")
    if max_rounds is not None:
        cmd.extend(["--max-rounds", str(int(max_rounds))])

    print_step("[Run] 启动并行模拟")
    subprocess.run(
        cmd,
        cwd=str(simulation_dir),
        env=os.environ.copy(),
        check=True,
    )


def maybe_generate_report(config: Dict[str, Any], prepare_state: Dict[str, Any], run_dir: Path) -> Dict[str, Any] | None:
    report_cfg = config.get("report", {}) or {}
    if not bool(report_cfg.get("generate", False)):
        return None

    project = ProjectManager.get_project(str(prepare_state["project_id"]))
    if project is None:
        raise ValueError(f"项目不存在: {prepare_state['project_id']}")

    report_id = str(report_cfg.get("report_id", "") or "").strip() or None
    agent = ReportAgent(
        graph_id=str(prepare_state["graph_id"]),
        simulation_id=str(prepare_state["simulation_id"]),
        simulation_requirement=project.simulation_requirement or str(config.get("simulation_requirement", "")),
    )

    def progress(stage: str, percent: int, message: str):
        print_step(f"[Report][{stage}] {percent}% {message}")

    report = agent.generate_report(progress_callback=progress, report_id=report_id)
    payload = report.to_dict()
    payload["full_report_path"] = (
        ReportManager._get_report_markdown_path(report.report_id)
        if report.status == ReportStatus.COMPLETED
        else ""
    )
    write_json(run_dir / "report_meta.json", payload)
    return payload


def create_consolidated_view(
    run_dir: Path,
    pipeline_result: Dict[str, Any],
    prepare_state: Dict[str, Any],
    report_meta: Dict[str, Any] | None,
) -> Dict[str, str]:
    project_id = str(prepare_state["project_id"])
    simulation_id = str(prepare_state["simulation_id"])
    project_dir = (BACKEND_DIR / "uploads" / "projects" / project_id).resolve()
    simulation_dir = (BACKEND_DIR / "uploads" / "simulations" / simulation_id).resolve()

    project_view_dir = run_dir / "01_project_artifacts"
    simulation_view_dir = run_dir / "02_simulation_artifacts"
    report_view_dir = run_dir / "03_report_artifacts"

    project_view_dir.mkdir(parents=True, exist_ok=True)
    simulation_view_dir.mkdir(parents=True, exist_ok=True)
    report_view_dir.mkdir(parents=True, exist_ok=True)

    exposed: Dict[str, str] = {
        "guide": str((run_dir / "00_artifacts_guide.md").absolute()),
        "project_artifacts_dir": str(project_view_dir.absolute()),
        "simulation_artifacts_dir": str(simulation_view_dir.absolute()),
        "report_artifacts_dir": str(report_view_dir.absolute()),
    }

    project_links = {
        "project_workspace": project_dir,
        "input_files": project_dir / "files",
        "project_metadata.json": project_dir / "project.json",
        "extracted_text.txt": project_dir / "extracted_text.txt",
        "parsed_content.json": project_dir / "parsed_content.json",
        "source_manifest.json": project_dir / "source_manifest.json",
    }
    for name, target in project_links.items():
        exposed[f"project::{name}"] = expose_artifact(target, project_view_dir / name)

    simulation_links = {
        "simulation_workspace": simulation_dir,
        "simulation_status.json": simulation_dir / "state.json",
        "simulation_env_status.json": simulation_dir / "env_status.json",
        "simulation_runtime_log.log": simulation_dir / "simulation.log",
        "generated_simulation_config.json": simulation_dir / "simulation_config.json",
        "original_simulation_config.json": simulation_dir / "simulation_config.original.json",
        "entity_prompts.json": simulation_dir / "entity_prompts.json",
        "entity_graph_snapshot.json": simulation_dir / "entity_graph_snapshot.json",
        "social_relation_graph.json": simulation_dir / "social_relation_graph.json",
        "twitter_profiles.csv": simulation_dir / "twitter_profiles.csv",
        "reddit_profiles.json": simulation_dir / "reddit_profiles.json",
        "twitter_actions.jsonl": simulation_dir / "twitter" / "actions.jsonl",
        "reddit_actions.jsonl": simulation_dir / "reddit" / "actions.jsonl",
        "twitter_simulation.db": simulation_dir / "twitter_simulation.db",
        "reddit_simulation.db": simulation_dir / "reddit_simulation.db",
        "twitter_memory.json": simulation_dir / "simplemem_twitter.json",
        "reddit_memory.json": simulation_dir / "simplemem_reddit.json",
    }
    for name, target in simulation_links.items():
        exposed[f"simulation::{name}"] = expose_artifact(target, simulation_view_dir / name)

    report_lines = ["## 03_report_artifacts", ""]
    if report_meta and str(report_meta.get("report_id", "") or "").strip():
        report_id = str(report_meta["report_id"])
        report_dir = (BACKEND_DIR / "uploads" / "reports" / report_id).resolve()
        report_links = {
            "report_workspace": report_dir,
            "report_metadata.json": report_dir / "meta.json",
            "report_outline.json": report_dir / "outline.json",
            "report_progress.json": report_dir / "progress.json",
            "full_report.md": report_dir / "full_report.md",
            "agent_log.jsonl": report_dir / "agent_log.jsonl",
            "console_log.txt": report_dir / "console_log.txt",
        }
        for name, target in report_links.items():
            exposed[f"report::{name}"] = expose_artifact(target, report_view_dir / name)
            if target.exists():
                report_lines.append(f"- `{name}`")
    else:
        write_text(report_view_dir / "README.md", "本次运行未生成最终报告。\n")
        report_lines.append("- 本次运行未生成最终报告。")

    guide_lines = [
        f"# Run Artifact Guide",
        "",
        f"- 运行目录: `{run_dir}`",
        f"- 项目ID: `{project_id}`",
        f"- 图谱ID: `{str((pipeline_result.get('graph') or {}).get('graph_id') or '')}`",
        f"- 模拟ID: `{simulation_id}`",
        "",
        "这个时间戳目录是本次实验的集中视图。",
        "真实文件仍然保存在 `uploads/projects`、`uploads/simulations`、`uploads/reports` 中，以保持现有逻辑兼容。",
        "这里提供的是更容易寻找的同目录入口；大多数条目是符号链接，少数环境下会自动退回为复制。",
        "",
        "## 01_project_artifacts",
        "",
        "- `project_workspace`: 项目原始目录入口",
        "- `input_files`: 本次项目复制后的输入文件",
        "- `project_metadata.json`: 项目元数据",
        "- `extracted_text.txt`: 提取出的全文文本",
        "- `parsed_content.json`: 多模态解析结果",
        "- `source_manifest.json`: 输入文件清单",
        "",
        "## 02_simulation_artifacts",
        "",
        "- `simulation_workspace`: 模拟原始目录入口",
        "- `simulation_status.json`: 模拟准备状态",
        "- `simulation_env_status.json`: 运行结束状态",
        "- `simulation_runtime_log.log`: 主日志",
        "- `generated_simulation_config.json`: 实际运行使用的模拟配置",
        "- `original_simulation_config.json`: 覆盖前的原始模拟配置",
        "- `entity_prompts.json`: 实体画像提示",
        "- `entity_graph_snapshot.json`: 初始实体图快照",
        "- `social_relation_graph.json`: 社交关系图",
        "- `twitter_profiles.csv` / `reddit_profiles.json`: 双平台人设文件",
        "- `twitter_actions.jsonl` / `reddit_actions.jsonl`: 双平台动作日志",
        "- `twitter_simulation.db` / `reddit_simulation.db`: 双平台数据库",
        "- `twitter_memory.json` / `reddit_memory.json`: 双平台记忆产物",
        "",
    ]
    guide_lines.extend(report_lines)
    guide_lines.append("")
    write_text(run_dir / "00_artifacts_guide.md", "\n".join(guide_lines))

    return exposed


def build_manifest(
    config_path: Path,
    run_dir: Path,
    pipeline_result: Dict[str, Any],
    prepare_state: Dict[str, Any],
    report_meta: Dict[str, Any] | None,
    consolidated_view: Dict[str, str],
) -> Dict[str, Any]:
    simulation_id = str(prepare_state["simulation_id"])
    project_id = str(prepare_state["project_id"])
    simulation_dir = (BACKEND_DIR / "uploads" / "simulations" / simulation_id).resolve()
    project_dir = (BACKEND_DIR / "uploads" / "projects" / project_id).resolve()

    report_id = ""
    report_dir = ""
    full_report_path = ""
    if report_meta:
        report_id = str(report_meta.get("report_id", "") or "")
        if report_id:
            report_dir = str((BACKEND_DIR / "uploads" / "reports" / report_id).resolve())
        full_report_path = str(report_meta.get("full_report_path", "") or "")

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "config_path": str(config_path.resolve()),
        "run_dir": str(run_dir.resolve()),
        "project_id": project_id,
        "graph_id": str((pipeline_result.get("graph") or {}).get("graph_id") or ""),
        "simulation_id": simulation_id,
        "report_id": report_id,
        "artifacts": {
            "pipeline_result": str((run_dir / "pipeline_result.json").resolve()),
            "prepare_state": str((run_dir / "prepare_state.json").resolve()),
            "final_simulation_config": str((run_dir / "simulation_config.final.json").resolve()),
            "report_meta": str((run_dir / "report_meta.json").resolve()) if report_meta else "",
            "project_dir": str(project_dir),
            "simulation_dir": str(simulation_dir),
            "report_dir": report_dir,
            "full_report": full_report_path,
        },
        "consolidated_view": {
            "guide": consolidated_view.get("guide", ""),
            "project_artifacts_dir": consolidated_view.get("project_artifacts_dir", ""),
            "simulation_artifacts_dir": consolidated_view.get("simulation_artifacts_dir", ""),
            "report_artifacts_dir": consolidated_view.get("report_artifacts_dir", ""),
        },
    }
    return manifest


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    ensure_runtime_env()
    config = read_json(config_path)
    config_dir = config_path.parent
    files = collect_input_files(config, config_dir)
    if not files:
        raise ValueError("请在配置文件中通过 files 或 files_from 提供至少一个输入文件")
    if not str(config.get("simulation_requirement", "") or "").strip():
        raise ValueError("请在配置文件中提供 simulation_requirement")

    run_dir = create_run_dir(config, config_path)
    shutil.copy2(config_path, run_dir / "run_config.json")

    pipeline_opts = build_pipeline_options(config, files)
    pipeline = LocalGraphPipeline()
    pipeline_result = pipeline.run(pipeline_opts, progress_callback=lambda msg: print_step(f"[Pipeline] {msg}"))
    write_json(run_dir / "pipeline_result.json", pipeline_result)

    prepare_state = prepare_simulation_assets(pipeline_result, config, run_dir)
    simulation_dir = BACKEND_DIR / "uploads" / "simulations" / str(prepare_state["simulation_id"])
    apply_simulation_config_overrides(simulation_dir, run_dir, config)
    run_parallel_simulation(simulation_dir, config)

    report_meta = maybe_generate_report(config, prepare_state, run_dir)
    consolidated_view = create_consolidated_view(
        run_dir=run_dir,
        pipeline_result=pipeline_result,
        prepare_state=prepare_state,
        report_meta=report_meta,
    )

    manifest = build_manifest(
        config_path=config_path,
        run_dir=run_dir,
        pipeline_result=pipeline_result,
        prepare_state=prepare_state,
        report_meta=report_meta,
        consolidated_view=consolidated_view,
    )
    write_json(run_dir / "run_manifest.json", manifest)
    write_json(LATEST_MANIFEST_PATH, manifest)

    print_step(f"[Done] 全流程完成，运行清单: {run_dir / 'run_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
