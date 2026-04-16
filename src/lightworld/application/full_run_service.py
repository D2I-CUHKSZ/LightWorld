from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from lightworld.domain.project import ProjectManager
from lightworld.graph.local_graph_pipeline import LocalGraphPipeline, LocalPipelineOptions
from lightworld.simulation.cluster_cli import (
    CLUSTER_METHOD_LLM_KEYWORD,
    CLUSTER_METHOD_THRESHOLD,
    apply_cluster_method_to_full_run_config,
    describe_cluster_method,
    maybe_prompt_cluster_method,
)
from lightworld.simulation.cluster_flags import normalize_topology_cluster_config
from lightworld.config.settings import Config
from lightworld.reporting.report_agent import ReportAgent, ReportManager, ReportStatus
from lightworld.simulation.simulation_manager import SimulationManager


@dataclass(frozen=True)
class FullRunPaths:
    repo_root: Path
    full_runs_dir: Path
    latest_manifest_path: Path
    projects_root: Path
    simulations_root: Path
    reports_root: Path

    @classmethod
    def create(cls) -> "FullRunPaths":
        repo_root = Path(__file__).resolve().parents[3]
        return cls(
            repo_root=repo_root,
            full_runs_dir=repo_root / "runs",
            latest_manifest_path=(repo_root / "runs" / "latest.json"),
            projects_root=Path(Config.UPLOAD_FOLDER) / "projects",
            simulations_root=Path(Config.OASIS_SIMULATION_DATA_DIR),
            reports_root=Path(Config.REPORTS_DIR),
        )


class FullRunService:
    def __init__(
        self,
        paths: Optional[FullRunPaths] = None,
        simulation_manager: Optional[SimulationManager] = None,
        pipeline: Optional[LocalGraphPipeline] = None,
    ):
        self.paths = paths or FullRunPaths.create()
        self.simulation_manager = simulation_manager or SimulationManager()
        self.pipeline = pipeline or LocalGraphPipeline()

    def print_step(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}", flush=True)

    def read_json(self, path: Path) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Config file must be a JSON object: {path}")
        return data

    def write_json(self, path: Path, payload: Dict[str, Any]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def write_text(self, path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def resolve_path(self, path: str, base_dir: Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (base_dir / p).resolve()

    def load_paths_from_file(self, list_file: Path) -> List[Path]:
        if not list_file.exists():
            raise FileNotFoundError(f"File list does not exist: {list_file}")
        paths: List[Path] = []
        with open(list_file, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if not item or item.startswith("#"):
                    continue
                paths.append(self.resolve_path(item, list_file.parent))
        return paths

    @staticmethod
    def slugify(text: str) -> str:
        chars: List[str] = []
        for ch in str(text).strip().lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch in {" ", "-", "_"}:
                chars.append("-")
        slug = "".join(chars).strip("-")
        return slug or "run"

    @staticmethod
    def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = deepcopy(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = FullRunService.deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    def ensure_runtime_env(self):
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

    def collect_input_files(self, config: Dict[str, Any], config_dir: Path) -> List[str]:
        files_value = config.get("files", []) or []
        if isinstance(files_value, str):
            files_value = [files_value]
        if not isinstance(files_value, list):
            raise ValueError("config.files must be a list of strings")

        file_paths = [str(self.resolve_path(str(item), config_dir)) for item in files_value]
        files_from = config.get("files_from", "")
        if files_from:
            file_paths.extend(
                str(path)
                for path in self.load_paths_from_file(self.resolve_path(str(files_from), config_dir))
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

    def build_pipeline_options(self, config: Dict[str, Any], files: List[str]) -> LocalPipelineOptions:
        pipeline_cfg = config.get("pipeline", {}) or {}
        return LocalPipelineOptions(
            files=files,
            simulation_requirement=str(config.get("simulation_requirement", "") or "").strip(),
            project_name=str(config.get("project_name", "MicroWorld Local Run") or "MicroWorld Local Run"),
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

    def create_run_dir(self, config: Dict[str, Any], config_path: Path) -> Path:
        configured_output_dir = str(config.get("output_dir", "") or "").strip()
        if configured_output_dir:
            run_dir = self.resolve_path(configured_output_dir, config_path.parent)
        else:
            run_name = str(config.get("project_name", "") or config_path.stem)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = self.paths.full_runs_dir / f"run_{timestamp}_{self.slugify(run_name)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def remove_path(path: Path):
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    def get_project_dir(self, project_id: str) -> Path:
        return (self.paths.projects_root / project_id).resolve()

    def get_simulation_dir(self, simulation_id: str) -> Path:
        return (self.paths.simulations_root / simulation_id).resolve()

    def get_report_dir(self, report_id: str) -> Path:
        return (self.paths.reports_root / report_id).resolve()

    def expose_artifact(self, target: Path, exposed_path: Path) -> str:
        if not target.exists():
            return ""

        exposed_path.parent.mkdir(parents=True, exist_ok=True)
        self.remove_path(exposed_path)
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
        self,
        pipeline_result: Dict[str, Any],
        config: Dict[str, Any],
        run_dir: Path,
    ) -> Dict[str, Any]:
        project_id = str(pipeline_result["project_id"])
        graph_id = str((pipeline_result.get("graph") or {}).get("graph_id") or "")
        project = ProjectManager.get_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        document_text = ProjectManager.get_extracted_text(project_id)
        if not document_text:
            raise ValueError("Extracted text is empty; cannot prepare simulation")

        defined_entity_types = [
            str(item.get("name"))
            for item in ((project.ontology or {}).get("entity_types", []) or [])
            if isinstance(item, dict) and item.get("name")
        ]

        sim_cfg = config.get("simulation", {}) or {}
        state = self.simulation_manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=bool(sim_cfg.get("enable_twitter", True)),
            enable_reddit=bool(sim_cfg.get("enable_reddit", True)),
        )
        self.print_step(f"[Prepare] Created simulation: {state.simulation_id}")

        def progress(stage: str, percent: int, message: str, **kwargs):
            current = kwargs.get("current")
            total = kwargs.get("total")
            suffix = f" ({current}/{total})" if current is not None and total else ""
            self.print_step(f"[Prepare][{stage}] {percent}% {message}{suffix}")

        prepared = self.simulation_manager.prepare_simulation(
            simulation_id=state.simulation_id,
            simulation_requirement=project.simulation_requirement or str(config.get("simulation_requirement", "")),
            document_text=document_text,
            defined_entity_types=defined_entity_types or None,
            use_llm_for_profiles=bool(sim_cfg.get("use_llm_for_profiles", True)),
            progress_callback=progress,
            parallel_profile_count=int(sim_cfg.get("parallel_profile_count", 3)),
        )
        payload = prepared.to_dict()
        self.write_json(run_dir / "prepare_state.json", payload)
        return payload

    def apply_simulation_config_overrides(self, simulation_dir: Path, run_dir: Path, config: Dict[str, Any]):
        config_path = simulation_dir / "simulation_config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"simulation_config.json not found: {config_path}")

        simulation_cfg = config.get("simulation", {}) or {}
        config_overrides = simulation_cfg.get("config_overrides", {}) or {}
        current_config = self.read_json(config_path)

        if config_overrides:
            backup_path = simulation_dir / "simulation_config.original.json"
            if not backup_path.exists():
                shutil.copy2(config_path, backup_path)
            current_config = self.deep_merge(current_config, config_overrides)

        normalize_topology_cluster_config(current_config)
        self.write_json(config_path, current_config)
        self.write_json(run_dir / "simulation_config.final.json", current_config)

    def run_parallel_simulation(
        self,
        simulation_dir: Path,
        config: Dict[str, Any],
        cluster_method: Optional[str] = None,
    ):
        run_cfg = config.get("run", {}) or {}
        cmd = [
            sys.executable,
            "-m", "lightworld.simulation.parallel_simulation_main",
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
        if cluster_method:
            cmd.extend(["--cluster-method", cluster_method])

        max_rounds = run_cfg.get("max_rounds")
        if max_rounds is not None:
            cmd.extend(["--max-rounds", str(int(max_rounds))])

        self.print_step("[Run] Starting parallel simulation")
        subprocess.run(cmd, cwd=str(simulation_dir), env=os.environ.copy(), check=True)

    def maybe_generate_report(
        self,
        config: Dict[str, Any],
        prepare_state: Dict[str, Any],
        run_dir: Path,
    ) -> Optional[Dict[str, Any]]:
        report_cfg = config.get("report", {}) or {}
        if not bool(report_cfg.get("generate", False)):
            return None

        project = ProjectManager.get_project(str(prepare_state["project_id"]))
        if project is None:
            raise ValueError(f"Project not found: {prepare_state['project_id']}")

        report_id = str(report_cfg.get("report_id", "") or "").strip() or None
        report_mode = str(report_cfg.get("mode", "public_report") or "public_report")
        agent = ReportAgent(
            graph_id=str(prepare_state["graph_id"]),
            simulation_id=str(prepare_state["simulation_id"]),
            simulation_requirement=project.simulation_requirement or str(config.get("simulation_requirement", "")),
            report_mode=report_mode,
        )

        def progress(stage: str, percent: int, message: str):
            self.print_step(f"[Report][{stage}] {percent}% {message}")

        report = agent.generate_report(progress_callback=progress, report_id=report_id)
        payload = report.to_dict()
        payload["full_report_path"] = (
            ReportManager._get_report_markdown_path(report.report_id)
            if report.status == ReportStatus.COMPLETED
            else ""
        )
        self.write_json(run_dir / "report_meta.json", payload)
        return payload

    def create_consolidated_view(
        self,
        run_dir: Path,
        pipeline_result: Dict[str, Any],
        prepare_state: Dict[str, Any],
        report_meta: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        project_id = str(prepare_state["project_id"])
        simulation_id = str(prepare_state["simulation_id"])
        project_dir = self.get_project_dir(project_id)
        simulation_dir = self.get_simulation_dir(simulation_id)

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
            exposed[f"project::{name}"] = self.expose_artifact(target, project_view_dir / name)

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
            exposed[f"simulation::{name}"] = self.expose_artifact(target, simulation_view_dir / name)

        report_lines = ["## 03_report_artifacts", ""]
        if report_meta and str(report_meta.get("report_id", "") or "").strip():
            report_id = str(report_meta["report_id"])
            report_dir = self.get_report_dir(report_id)
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
                exposed[f"report::{name}"] = self.expose_artifact(target, report_view_dir / name)
                if target.exists():
                    report_lines.append(f"- `{name}`")
        else:
            self.write_text(report_view_dir / "README.md", "No final report was generated for this run.\n")
            report_lines.append("- No final report was generated for this run.")

        guide_lines = [
            "# Run Artifact Guide",
            "",
            f"- Run directory: `{run_dir}`",
            f"- Project ID: `{project_id}`",
            f"- Graph ID: `{str((pipeline_result.get('graph') or {}).get('graph_id') or '')}`",
            f"- Simulation ID: `{simulation_id}`",
            "",
            "This timestamped directory is a consolidated view of this experiment.",
            "Canonical files remain under `input2graph/projects`, `output/simulations`, and `output/reports` for compatibility with existing logic.",
            "This folder provides colocated entry points for easier discovery; most entries are symlinks, and in some environments they fall back to copies.",
            "",
            "## 01_project_artifacts",
            "",
            "- `project_workspace`: Project workspace root",
            "- `input_files`: Input files copied for this project",
            "- `project_metadata.json`: Project metadata",
            "- `extracted_text.txt`: Extracted full text",
            "- `parsed_content.json`: Multimodal parse output",
            "- `source_manifest.json`: Input file manifest",
            "",
            "## 02_simulation_artifacts",
            "",
            "- `simulation_workspace`: Simulation workspace root",
            "- `simulation_status.json`: Simulation preparation status",
            "- `simulation_env_status.json`: Post-run environment status",
            "- `simulation_runtime_log.log`: Main runtime log",
            "- `generated_simulation_config.json`: Simulation config used for the run",
            "- `original_simulation_config.json`: Original simulation config before overrides",
            "- `entity_prompts.json`: Entity profile prompts",
            "- `entity_graph_snapshot.json`: Initial entity graph snapshot",
            "- `social_relation_graph.json`: Social relation graph",
            "- `twitter_profiles.csv` / `reddit_profiles.json`: Cross-platform persona files",
            "- `twitter_actions.jsonl` / `reddit_actions.jsonl`: Cross-platform action logs",
            "- `twitter_simulation.db` / `reddit_simulation.db`: Cross-platform databases",
            "- `twitter_memory.json` / `reddit_memory.json`: Cross-platform memory artifacts",
            "",
        ]
        guide_lines.extend(report_lines)
        guide_lines.append("")
        self.write_text(run_dir / "00_artifacts_guide.md", "\n".join(guide_lines))

        return exposed

    def build_manifest(
        self,
        config_path: Path,
        run_dir: Path,
        pipeline_result: Dict[str, Any],
        prepare_state: Dict[str, Any],
        report_meta: Optional[Dict[str, Any]],
        consolidated_view: Dict[str, str],
    ) -> Dict[str, Any]:
        simulation_id = str(prepare_state["simulation_id"])
        project_id = str(prepare_state["project_id"])
        simulation_dir = self.get_simulation_dir(simulation_id)
        project_dir = self.get_project_dir(project_id)

        report_id = ""
        report_dir = ""
        full_report_path = ""
        if report_meta:
            report_id = str(report_meta.get("report_id", "") or "")
            if report_id:
                report_dir = str(self.get_report_dir(report_id))
            full_report_path = str(report_meta.get("full_report_path", "") or "")

        return {
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

    @staticmethod
    def detect_cluster_method(config: Dict[str, Any]) -> Optional[str]:
        simulation_cfg = config.get("simulation", {}) or {}
        if not isinstance(simulation_cfg, dict):
            return None
        config_overrides = simulation_cfg.get("config_overrides", {}) or {}
        if not isinstance(config_overrides, dict):
            return None
        topo_cfg = config_overrides.get("topology_aware", {}) or {}
        if not isinstance(topo_cfg, dict):
            return None
        threshold_enabled = bool(topo_cfg.get("threshold_cluster_enabled", False))
        llm_enabled = bool(topo_cfg.get("llm_keyword_cluster_enabled", False))
        if llm_enabled:
            return CLUSTER_METHOD_LLM_KEYWORD
        if threshold_enabled:
            return CLUSTER_METHOD_THRESHOLD
        cluster_mode = str(topo_cfg.get("cluster_mode", "") or "").strip().lower()
        if cluster_mode == "llm_keyword_consistency":
            return CLUSTER_METHOD_LLM_KEYWORD
        if cluster_mode == "threshold_only":
            return CLUSTER_METHOD_THRESHOLD
        return None

    def run(self, config_path: Path, cluster_method_override: Optional[str] = None) -> Dict[str, Any]:
        config_path = config_path.resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self.ensure_runtime_env()
        config = self.read_json(config_path)
        config_dir = config_path.parent
        files = self.collect_input_files(config, config_dir)
        if not files:
            raise ValueError("Provide at least one input file via files or files_from in the config")
        if not str(config.get("simulation_requirement", "") or "").strip():
            raise ValueError("simulation_requirement must be set in the config")

        current_method = self.detect_cluster_method(config)
        selected_cluster_method = maybe_prompt_cluster_method(cluster_method_override, current_method)
        if selected_cluster_method:
            apply_cluster_method_to_full_run_config(config, selected_cluster_method)
            self.print_step(f"[Config] Cluster method: {describe_cluster_method(selected_cluster_method)}")

        run_dir = self.create_run_dir(config, config_path)
        self.write_json(run_dir / "run_config.json", config)

        pipeline_opts = self.build_pipeline_options(config, files)
        pipeline_result = self.pipeline.run(
            pipeline_opts,
            progress_callback=lambda msg: self.print_step(f"[Pipeline] {msg}"),
        )
        self.write_json(run_dir / "pipeline_result.json", pipeline_result)

        prepare_state = self.prepare_simulation_assets(pipeline_result, config, run_dir)
        simulation_dir = self.get_simulation_dir(str(prepare_state["simulation_id"]))
        self.apply_simulation_config_overrides(simulation_dir, run_dir, config)
        self.run_parallel_simulation(
            simulation_dir,
            config,
            cluster_method=selected_cluster_method,
        )

        report_meta = self.maybe_generate_report(config, prepare_state, run_dir)
        consolidated_view = self.create_consolidated_view(
            run_dir=run_dir,
            pipeline_result=pipeline_result,
            prepare_state=prepare_state,
            report_meta=report_meta,
        )

        manifest = self.build_manifest(
            config_path=config_path,
            run_dir=run_dir,
            pipeline_result=pipeline_result,
            prepare_state=prepare_state,
            report_meta=report_meta,
            consolidated_view=consolidated_view,
        )
        self.write_json(run_dir / "run_manifest.json", manifest)
        self.write_json(self.paths.latest_manifest_path, manifest)
        self.print_step(f"[Done] Full run finished. Manifest: {run_dir / 'run_manifest.json'}")
        return manifest
