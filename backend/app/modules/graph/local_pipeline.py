"""Local document pipeline (application service).

Encapsulates: read local docs -> preprocess -> ontology -> graph build.
"""

import json
import os
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...setting.settings import Config
from ...domain.project import ProjectManager, ProjectStatus
from ...utils.graph_builder import GraphBuilderService
from ...utils.multimodal_ingestion import MultimodalIngestionService
from ...utils.ontology_generator import OntologyGenerator
from ...utils.text_processor import TextProcessor


@dataclass
class LocalPipelineOptions:
    files: List[str]
    simulation_requirement: str
    project_name: str = "Local Pipeline Project"
    additional_context: str = ""
    graph_name: str = ""
    chunk_size: int = Config.DEFAULT_CHUNK_SIZE
    chunk_overlap: int = Config.DEFAULT_CHUNK_OVERLAP
    batch_size: int = 3
    light_mode: bool = False
    light_text_max_chars: int = 120000
    light_ontology_max_chars: int = 80000
    light_max_chunks: int = 120
    light_chunk_size: int = 1200
    light_chunk_overlap: int = 40


class LocalGraphPipeline:
    """Application service for backend-only local pipeline."""

    def __init__(self, zep_api_key: Optional[str] = None):
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY

    @staticmethod
    def _is_allowed_path(file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        return ext in Config.ALLOWED_EXTENSIONS

    @staticmethod
    def _compact_text_for_light(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text

        marker = "\n\n...[light模式省略部分]...\n\n"
        if max_chars <= len(marker) * 2 + 64:
            return text[:max_chars]

        head_len = max_chars // 3
        tail_len = max_chars // 3
        middle_len = max_chars - head_len - tail_len - len(marker) * 2
        if middle_len < 32:
            middle_len = 32

        middle_start = max(0, (len(text) - middle_len) // 2)
        middle_end = middle_start + middle_len

        return (
            text[:head_len]
            + marker
            + text[middle_start:middle_end]
            + marker
            + text[-tail_len:]
        )

    @staticmethod
    def _downsample_chunks_evenly(chunks: List[str], max_chunks: int) -> List[str]:
        if max_chunks <= 0 or len(chunks) <= max_chunks:
            return chunks
        if max_chunks == 1:
            return [chunks[0]]

        sampled: List[str] = []
        last_index = len(chunks) - 1
        for i in range(max_chunks):
            idx = int(round(i * last_index / (max_chunks - 1)))
            sampled.append(chunks[idx])
        return sampled

    def run(
        self,
        opts: LocalPipelineOptions,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not opts.files:
            raise ValueError("请提供至少一个文档路径")

        if not Config.LLM_API_KEY:
            raise ValueError("LLM_API_KEY 未配置，无法生成本体")

        if not self.zep_api_key:
            raise ValueError("ZEP_API_KEY 未配置，无法构建图谱")

        def log_step(msg: str):
            if progress_callback:
                progress_callback(msg)

        project = None
        try:
            log_step("创建项目")
            project = ProjectManager.create_project(name=opts.project_name)
            project.simulation_requirement = opts.simulation_requirement
            project.chunk_size = opts.chunk_size
            project.chunk_overlap = opts.chunk_overlap
            ProjectManager.save_project(project)

            log_step("读取并提取本地文档文本")
            saved_inputs: List[Dict[str, str]] = []
            skipped = []

            for src in [os.path.abspath(p) for p in opts.files]:
                if not os.path.exists(src):
                    skipped.append((src, "文件不存在"))
                    continue
                if not os.path.isfile(src):
                    skipped.append((src, "不是文件"))
                    continue
                if not self._is_allowed_path(src):
                    skipped.append((src, f"不支持格式，仅支持 {sorted(Config.ALLOWED_EXTENSIONS)}"))
                    continue

                file_info = ProjectManager.save_local_file_to_project(project.project_id, src)
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                saved_inputs.append({
                    "path": file_info["path"],
                    "display_name": file_info["original_filename"],
                })

            if not saved_inputs:
                raise ValueError("没有可用文档可处理，请检查文件路径和格式")

            log_step("执行多模态输入解析")
            ingestion = MultimodalIngestionService().ingest_files(
                saved_inputs,
                simulation_requirement=opts.simulation_requirement,
                additional_context=opts.additional_context,
            )

            document_texts = ingestion.get("document_texts", [])
            all_text = ingestion.get("all_text", "")
            if not document_texts or not all_text.strip():
                raise ValueError("多模态输入解析后未生成可用文本，请检查输入内容")

            project.total_text_length = len(all_text)
            project.ingestion_summary = ingestion.get("manifest")
            ProjectManager.save_extracted_text(project.project_id, all_text)
            ProjectManager.save_json_artifact(
                project.project_id,
                "parsed_content.json",
                ingestion.get("parsed_content", {}),
            )
            ProjectManager.save_json_artifact(
                project.project_id,
                "source_manifest.json",
                ingestion.get("manifest", {}),
            )
            ProjectManager.save_project(project)

            ontology_texts = document_texts
            graph_input_text = all_text
            light_summary = None

            if opts.light_mode:
                ontology_texts = [
                    self._compact_text_for_light(text, opts.light_ontology_max_chars)
                    for text in document_texts
                ]
                graph_input_text = self._compact_text_for_light(all_text, opts.light_text_max_chars)
                light_summary = {
                    "graph_text_before": len(all_text),
                    "graph_text_after": len(graph_input_text),
                    "ontology_per_doc_max_chars": opts.light_ontology_max_chars,
                }

            log_step("生成本体定义")
            ontology = OntologyGenerator().generate(
                document_texts=ontology_texts,
                simulation_requirement=opts.simulation_requirement,
                additional_context=opts.additional_context or None,
            )
            project.ontology = {
                "entity_types": ontology.get("entity_types", []),
                "edge_types": ontology.get("edge_types", []),
            }
            project.analysis_summary = ontology.get("analysis_summary", "")
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            ProjectManager.save_project(project)

            log_step("开始构建图谱（同步）")
            graph_name = opts.graph_name or project.name or "MiroFish Graph"
            builder = GraphBuilderService(api_key=self.zep_api_key)

            chunk_size = opts.chunk_size
            chunk_overlap = opts.chunk_overlap
            if opts.light_mode:
                chunk_size = max(200, opts.light_chunk_size)
                chunk_overlap = max(0, opts.light_chunk_overlap)

            chunks = TextProcessor.split_text(
                graph_input_text,
                chunk_size=chunk_size,
                overlap=chunk_overlap,
            )
            original_chunk_count = len(chunks)
            if opts.light_mode:
                chunks = self._downsample_chunks_evenly(chunks, opts.light_max_chunks)

            graph_id = builder.create_graph(name=graph_name)
            project.graph_id = graph_id
            ProjectManager.save_project(project)

            builder.set_ontology(graph_id, project.ontology)
            episodes = builder.add_text_batches(
                graph_id=graph_id,
                chunks=chunks,
                batch_size=opts.batch_size,
            )
            builder._wait_for_episodes(episodes)

            graph_data = builder.get_graph_data(graph_id)
            project.status = ProjectStatus.GRAPH_COMPLETED
            ProjectManager.save_project(project)

            result = {
                "success": True,
                "project_id": project.project_id,
                "project_name": project.name,
                "files_count": len(project.files),
                "total_text_length": project.total_text_length,
                "skipped": [{"path": p, "reason": r} for p, r in skipped],
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "ingestion_summary": project.ingestion_summary,
                "graph": {
                    "graph_id": graph_id,
                    "node_count": graph_data.get("node_count", 0),
                    "edge_count": graph_data.get("edge_count", 0),
                    "chunk_count": len(chunks),
                    "original_chunk_count": original_chunk_count,
                    "light_mode": opts.light_mode,
                },
            }
            if light_summary:
                result["light_summary"] = light_summary

            return result

        except Exception as e:
            if project:
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                try:
                    ProjectManager.save_project(project)
                except Exception:
                    pass
            raise RuntimeError(f"本地管线执行失败: {e}\n{traceback.format_exc()}") from e
