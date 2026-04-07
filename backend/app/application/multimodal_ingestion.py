"""
Unified multimodal ingestion service.

This module converts text, image, and video inputs into a shared evidence-block
representation, then flattens those blocks back into text so the downstream
LightWorld ontology/Zep/simulation flow can stay unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import mimetypes
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from PIL import Image

from ..core.settings import Config
from ..infrastructure.file_parser import FileParser
from ..infrastructure.llm_client import LLMClient
from ..infrastructure.logger import get_logger
from .text_processor import TextProcessor

logger = get_logger("mirofish.multimodal_ingestion")


IMAGE_ANALYSIS_SYSTEM_PROMPT = """你是一个多模态内容分析助手。

你的任务是把图片转换为适合“社会舆情/群体行为模拟”的结构化证据。
重点关注：
1. 图片中的人物、组织、品牌、机构、平台、地点、事件主体
2. 可见文字、横幅、字幕、海报、截图中的账号名或组织名
3. 能影响社交传播的视觉信号：情绪、冲突、号召、象征物、Logo、立场线索

必须只返回 JSON。"""


VIDEO_SEGMENT_SYSTEM_PROMPT = """你是一个视频片段分析助手。

你的任务是把视频片段转换为适合“社会舆情/群体行为模拟”的结构化证据。
请综合画面与转写文本，提取：
1. 片段中的人物、组织、品牌、平台、地点、事件主体
2. 片段正在发生的关键事件、行为和互动
3. 画面中出现的可见文字、字幕、横幅、海报、Logo、账号名
4. 可能驱动传播的情绪、立场、冲突、号召、公共议题线索

必须只返回 JSON。"""


@dataclass
class EvidenceBlock:
    block_id: str
    block_type: str
    source_modality: str
    source_path: str
    source_name: str
    summary: str = ""
    raw_text: str = ""
    visible_text: str = ""
    transcript: str = ""
    key_entities: List[str] = field(default_factory=list)
    social_signals: List[str] = field(default_factory=list)
    page_idx: Optional[int] = None
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None
    evidence_ref: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "type": self.block_type,
            "source_modality": self.source_modality,
            "source_path": self.source_path,
            "source_name": self.source_name,
            "summary": self.summary,
            "raw_text": self.raw_text,
            "visible_text": self.visible_text,
            "transcript": self.transcript,
            "key_entities": self.key_entities,
            "social_signals": self.social_signals,
            "page_idx": self.page_idx,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "evidence_ref": self.evidence_ref,
            "metadata": self.metadata,
        }

    def to_flat_text(self) -> str:
        if self.block_type == "text":
            return (self.raw_text or self.summary).strip()

        lines = [f"[{self.block_type.upper()}][source={self.source_name}]"]
        if self.page_idx is not None:
            lines[0] += f"[page={self.page_idx}]"
        if self.timestamp_start is not None and self.timestamp_end is not None:
            lines[0] += f"[{_format_seconds(self.timestamp_start)}-{_format_seconds(self.timestamp_end)}]"

        if self.summary:
            lines.append(f"Summary: {self.summary}")
        if self.visible_text:
            lines.append(f"VisibleText: {self.visible_text}")
        if self.transcript:
            lines.append(f"Transcript: {self.transcript}")
        if self.key_entities:
            lines.append("KeyEntities: " + ", ".join(self.key_entities))
        if self.social_signals:
            lines.append("SocialSignals: " + ", ".join(self.social_signals))
        if self.raw_text:
            lines.append(f"Evidence: {self.raw_text}")
        return "\n".join(line.strip() for line in lines if str(line).strip())


@dataclass
class FileIngestionResult:
    source_path: str
    source_name: str
    source_modality: str
    document_text: str
    blocks: List[EvidenceBlock]
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_name": self.source_name,
            "source_modality": self.source_modality,
            "document_text": self.document_text,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass
class _VideoSegmentPayload:
    segment_index: int
    start: float
    end: float
    frame_paths: List[str]
    audio_path: Optional[str] = None


class MultimodalIngestionService:
    """Convert heterogeneous inputs into shared evidence blocks."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        audio_model_name: Optional[str] = None,
        use_remote_analysis: Optional[bool] = None,
    ):
        self.model_name = model_name or Config.MULTIMODAL_VISION_MODEL_NAME
        self.audio_model_name = audio_model_name or Config.MULTIMODAL_AUDIO_MODEL_NAME
        self.use_remote_analysis = (
            Config.MULTIMODAL_USE_REMOTE_ANALYSIS
            if use_remote_analysis is None
            else bool(use_remote_analysis)
        )
        self._llm_client: Optional[LLMClient] = None
        self._audio_llm_client: Optional[LLMClient] = None

    def ingest_files(
        self,
        files: Sequence[Any],
        simulation_requirement: str = "",
        additional_context: str = "",
    ) -> Dict[str, Any]:
        normalized_files = [self._normalize_file_descriptor(item) for item in files]
        file_results: List[FileIngestionResult] = []
        all_blocks: List[EvidenceBlock] = []
        all_texts: List[str] = []
        document_texts: List[str] = []
        warnings: List[str] = []
        modalities = set()

        for file_item in normalized_files:
            result = self.ingest_file(
                file_path=file_item["path"],
                display_name=file_item["display_name"],
                simulation_requirement=simulation_requirement,
                additional_context=additional_context,
            )
            file_results.append(result)
            all_blocks.extend(result.blocks)
            warnings.extend(result.warnings)
            modalities.add(result.source_modality)

            if result.document_text.strip():
                document_texts.append(result.document_text)
                all_texts.append(f"=== {result.source_name} ===\n{result.document_text}")

        block_type_counter = Counter(block.block_type for block in all_blocks)
        parsed_content = {
            "generated_at": datetime.now().isoformat(),
            "file_count": len(file_results),
            "block_count": len(all_blocks),
            "modalities": sorted(modalities),
            "files": [result.to_dict() for result in file_results],
            "blocks": [block.to_dict() for block in all_blocks],
        }
        manifest = {
            "generated_at": parsed_content["generated_at"],
            "file_count": len(file_results),
            "block_count": len(all_blocks),
            "modalities": sorted(modalities),
            "block_type_counts": dict(block_type_counter),
            "warnings": warnings,
        }

        return {
            "document_texts": document_texts,
            "all_text": "\n\n".join(all_texts).strip(),
            "parsed_content": parsed_content,
            "manifest": manifest,
        }

    def ingest_file(
        self,
        file_path: str,
        display_name: Optional[str] = None,
        simulation_requirement: str = "",
        additional_context: str = "",
    ) -> FileIngestionResult:
        display_name = display_name or os.path.basename(file_path)
        suffix = os.path.splitext(file_path)[1].lower()

        if suffix in FileParser.SUPPORTED_EXTENSIONS:
            return self._ingest_text_file(file_path, display_name)
        if suffix.lstrip(".") in Config.IMAGE_EXTENSIONS:
            return self._ingest_image_file(
                file_path=file_path,
                display_name=display_name,
                simulation_requirement=simulation_requirement,
                additional_context=additional_context,
            )
        if suffix.lstrip(".") in Config.VIDEO_EXTENSIONS:
            return self._ingest_video_file(
                file_path=file_path,
                display_name=display_name,
                simulation_requirement=simulation_requirement,
                additional_context=additional_context,
            )

        raise ValueError(f"不支持的文件格式: {suffix}")

    def _ingest_text_file(self, file_path: str, display_name: str) -> FileIngestionResult:
        text = TextProcessor.preprocess_text(FileParser.extract_text(file_path))
        block = EvidenceBlock(
            block_id=_make_block_id(file_path, "text", 0),
            block_type="text",
            source_modality="document",
            source_path=file_path,
            source_name=display_name,
            summary=text[:300],
            raw_text=text,
            evidence_ref=f"text:{display_name}",
        )
        return FileIngestionResult(
            source_path=file_path,
            source_name=display_name,
            source_modality="document",
            document_text=text,
            blocks=[block],
            metadata={"extension": os.path.splitext(file_path)[1].lower()},
        )

    def _ingest_image_file(
        self,
        file_path: str,
        display_name: str,
        simulation_requirement: str,
        additional_context: str,
    ) -> FileIngestionResult:
        warnings: List[str] = []
        width = height = None
        try:
            with Image.open(file_path) as image:
                width, height = image.size
        except Exception as exc:
            warnings.append(f"读取图片尺寸失败: {exc}")

        analysis = self._analyze_image_with_llm(
            file_path=file_path,
            display_name=display_name,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context,
        )
        summary = analysis.get("summary", "")
        visible_text = analysis.get("visible_text", "")
        raw_text = analysis.get("evidence_text") or summary
        key_entities = _normalize_list(analysis.get("key_entities"))
        social_signals = _normalize_list(analysis.get("social_signals"))

        block = EvidenceBlock(
            block_id=_make_block_id(file_path, "image", 0),
            block_type="image",
            source_modality="image",
            source_path=file_path,
            source_name=display_name,
            summary=summary,
            raw_text=raw_text,
            visible_text=visible_text,
            key_entities=key_entities,
            social_signals=social_signals,
            evidence_ref=f"image:{display_name}",
            metadata={
                "width": width,
                "height": height,
                "mime_type": mimetypes.guess_type(file_path)[0] or "image/*",
            },
        )
        document_text = TextProcessor.preprocess_text(block.to_flat_text())

        return FileIngestionResult(
            source_path=file_path,
            source_name=display_name,
            source_modality="image",
            document_text=document_text,
            blocks=[block],
            warnings=warnings,
            metadata={"width": width, "height": height},
        )

    def _ingest_video_file(
        self,
        file_path: str,
        display_name: str,
        simulation_requirement: str,
        additional_context: str,
    ) -> FileIngestionResult:
        warnings: List[str] = []
        cache_dir = tempfile.mkdtemp(prefix="lightworld_video_")
        try:
            segments = self._extract_video_segments(file_path, cache_dir)
            if not segments:
                raise RuntimeError("未能从视频中提取任何片段")

            blocks: List[EvidenceBlock] = []
            for segment in segments:
                transcript = self._transcribe_audio(segment.audio_path)
                if segment.audio_path and not transcript:
                    warnings.append(
                        f"视频片段 {segment.segment_index} 音频转写失败，继续仅使用画面描述"
                    )

                analysis = self._analyze_video_segment_with_llm(
                    frame_paths=segment.frame_paths,
                    transcript=transcript,
                    display_name=display_name,
                    start=segment.start,
                    end=segment.end,
                    simulation_requirement=simulation_requirement,
                    additional_context=additional_context,
                )
                summary = analysis.get("summary", "")
                visible_text = analysis.get("visible_text", "")
                raw_text = analysis.get("evidence_text") or summary or transcript
                key_entities = _normalize_list(analysis.get("key_entities"))
                social_signals = _normalize_list(analysis.get("social_signals"))

                blocks.append(
                    EvidenceBlock(
                        block_id=_make_block_id(file_path, "video_segment", segment.segment_index),
                        block_type="video_segment",
                        source_modality="video",
                        source_path=file_path,
                        source_name=display_name,
                        summary=summary,
                        raw_text=raw_text,
                        visible_text=visible_text,
                        transcript=transcript,
                        key_entities=key_entities,
                        social_signals=social_signals,
                        timestamp_start=segment.start,
                        timestamp_end=segment.end,
                        evidence_ref=(
                            f"video:{display_name}:{_format_seconds(segment.start)}"
                            f"-{_format_seconds(segment.end)}"
                        ),
                        metadata={
                            "segment_index": segment.segment_index,
                            "frame_count": len(segment.frame_paths),
                        },
                    )
                )

            document_text = TextProcessor.preprocess_text(
                "\n\n".join(block.to_flat_text() for block in blocks)
            )
            return FileIngestionResult(
                source_path=file_path,
                source_name=display_name,
                source_modality="video",
                document_text=document_text,
                blocks=blocks,
                warnings=warnings,
                metadata={"segment_count": len(blocks)},
            )
        finally:
            shutil.rmtree(cache_dir, ignore_errors=True)

    def _analyze_image_with_llm(
        self,
        file_path: str,
        display_name: str,
        simulation_requirement: str,
        additional_context: str,
    ) -> Dict[str, Any]:
        fallback = {
            "summary": f"Image input {display_name}.",
            "visible_text": "",
            "key_entities": [],
            "social_signals": [],
            "evidence_text": f"Image file: {display_name}",
        }
        if not self.use_remote_analysis:
            return fallback
        try:
            client = self._get_llm_client()
        except Exception as exc:
            logger.warning(f"图片分析未启用 LLM，使用回退结果: {exc}")
            return fallback

        prompt = f"""
请分析这张图片，并输出适合社会模拟与图谱构建的结构化证据。

simulation_requirement:
{simulation_requirement or "无"}

additional_context:
{additional_context or "无"}

请只返回 JSON，包含字段：
{{
  "summary": "图片内容摘要，突出事件、主体、立场和场景",
  "visible_text": "图片中可辨识文字，没有则为空字符串",
  "key_entities": ["人物/组织/品牌/机构/平台/地点"],
  "social_signals": ["情绪、冲突、号召、象征物、传播线索"],
  "evidence_text": "供后续图谱和实体抽取使用的简洁文字证据"
}}
""".strip()

        image_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": _make_data_url(file_path)},
                },
            ],
        }
        try:
            result = client.chat_json(
                messages=[
                    {"role": "system", "content": IMAGE_ANALYSIS_SYSTEM_PROMPT},
                    image_message,
                ],
                temperature=0.1,
                max_tokens=1200,
            )
        except Exception as exc:
            logger.warning(f"图片分析失败，使用回退结果: {exc}")
            return fallback

        return {
            "summary": str(result.get("summary", "") or "").strip() or fallback["summary"],
            "visible_text": str(result.get("visible_text", "") or "").strip(),
            "key_entities": _normalize_list(result.get("key_entities")),
            "social_signals": _normalize_list(result.get("social_signals")),
            "evidence_text": str(result.get("evidence_text", "") or "").strip()
            or str(result.get("summary", "") or "").strip()
            or fallback["evidence_text"],
        }

    def _analyze_video_segment_with_llm(
        self,
        frame_paths: Sequence[str],
        transcript: str,
        display_name: str,
        start: float,
        end: float,
        simulation_requirement: str,
        additional_context: str,
    ) -> Dict[str, Any]:
        fallback = {
            "summary": (
                f"Video segment from {display_name} at "
                f"{_format_seconds(start)}-{_format_seconds(end)}."
            ),
            "visible_text": "",
            "key_entities": [],
            "social_signals": [],
            "evidence_text": transcript.strip(),
        }
        if not self.use_remote_analysis:
            return fallback
        try:
            client = self._get_llm_client()
        except Exception as exc:
            logger.warning(f"视频片段分析未启用 LLM，使用回退结果: {exc}")
            return fallback

        prompt = f"""
请分析当前视频片段，并抽取适合图谱构建和社会模拟的结构化证据。

video_segment:
source={display_name}
time={_format_seconds(start)}-{_format_seconds(end)}

simulation_requirement:
{simulation_requirement or "无"}

additional_context:
{additional_context or "无"}

transcript:
{transcript or "无转写"}

请只返回 JSON，包含字段：
{{
  "summary": "片段摘要，突出主体、事件和互动",
  "visible_text": "片段画面中的可见文字，没有则为空字符串",
  "key_entities": ["人物/组织/品牌/地点/平台/节目/账号"],
  "social_signals": ["情绪、冲突、号召、公共议题、传播线索"],
  "evidence_text": "供后续实体抽取使用的简洁文字证据"
}}
""".strip()

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for frame_path in frame_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _make_data_url(frame_path)},
                }
            )

        try:
            result = client.chat_json(
                messages=[
                    {"role": "system", "content": VIDEO_SEGMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.1,
                max_tokens=1400,
            )
        except Exception as exc:
            logger.warning(
                "视频片段分析失败，使用回退结果: "
                f"{display_name} {_format_seconds(start)}-{_format_seconds(end)}: {exc}"
            )
            return fallback

        return {
            "summary": str(result.get("summary", "") or "").strip() or fallback["summary"],
            "visible_text": str(result.get("visible_text", "") or "").strip(),
            "key_entities": _normalize_list(result.get("key_entities")),
            "social_signals": _normalize_list(result.get("social_signals")),
            "evidence_text": str(result.get("evidence_text", "") or "").strip()
            or str(result.get("summary", "") or "").strip()
            or transcript.strip()
            or fallback["summary"],
        }

    def _get_llm_client(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient(model=self.model_name)
        return self._llm_client

    def _get_audio_llm_client(self) -> LLMClient:
        if self._audio_llm_client is None:
            self._audio_llm_client = LLMClient(
                api_key=Config.MULTIMODAL_AUDIO_API_KEY,
                base_url=Config.MULTIMODAL_AUDIO_BASE_URL,
                model=self.audio_model_name,
            )
        return self._audio_llm_client

    def _normalize_file_descriptor(self, item: Any) -> Dict[str, str]:
        if isinstance(item, str):
            return {"path": item, "display_name": os.path.basename(item)}
        if isinstance(item, dict):
            path = str(item.get("path", "") or "").strip()
            if not path:
                raise ValueError(f"无效文件描述，缺少 path: {item}")
            display_name = str(item.get("display_name", "") or os.path.basename(path))
            return {"path": path, "display_name": display_name}
        raise TypeError(f"不支持的文件描述类型: {type(item)}")

    def _extract_video_segments(self, file_path: str, cache_dir: str) -> List[_VideoSegmentPayload]:
        backends = [
            self._extract_video_segments_with_ffmpeg,
            self._extract_video_segments_with_cv2,
            self._extract_video_segments_with_moviepy,
        ]
        errors: List[str] = []
        for backend in backends:
            try:
                segments = backend(file_path, cache_dir)
                if segments:
                    return segments
            except Exception as exc:
                errors.append(f"{backend.__name__}: {exc}")

        raise RuntimeError(
            "视频解析失败。当前环境未检测到可用的视频后端。"
            "请安装 ffmpeg、opencv-python 或 moviepy。"
            + (f" 详细错误: {' | '.join(errors)}" if errors else "")
        )

    def _extract_video_segments_with_ffmpeg(
        self,
        file_path: str,
        cache_dir: str,
    ) -> List[_VideoSegmentPayload]:
        ffmpeg_path = _resolve_binary_path(
            "ffmpeg",
            Config.MULTIMODAL_FFMPEG_PATH,
        )
        ffprobe_path = _resolve_binary_path(
            "ffprobe",
            Config.MULTIMODAL_FFPROBE_PATH,
        )
        if not ffmpeg_path or not ffprobe_path:
            raise RuntimeError("ffmpeg/ffprobe 不可用")

        duration = self._probe_duration_with_ffprobe(file_path, ffprobe_path)
        segments = self._build_segment_windows(duration)
        payloads: List[_VideoSegmentPayload] = []

        for index, (start, end) in enumerate(segments):
            segment_dir = os.path.join(cache_dir, f"segment_{index:03d}")
            os.makedirs(segment_dir, exist_ok=True)
            frame_paths = self._extract_frames_with_ffmpeg(
                file_path=file_path,
                ffmpeg_path=ffmpeg_path,
                segment_dir=segment_dir,
                start=start,
                end=end,
                frame_count=Config.MULTIMODAL_VIDEO_FRAMES_PER_SEGMENT,
            )
            audio_path = self._extract_audio_with_ffmpeg(
                file_path=file_path,
                ffmpeg_path=ffmpeg_path,
                segment_dir=segment_dir,
                start=start,
                end=end,
            )
            if frame_paths:
                payloads.append(
                    _VideoSegmentPayload(
                        segment_index=index,
                        start=start,
                        end=end,
                        frame_paths=frame_paths,
                        audio_path=audio_path,
                    )
                )
        return payloads

    def _extract_video_segments_with_cv2(
        self,
        file_path: str,
        cache_dir: str,
    ) -> List[_VideoSegmentPayload]:
        try:
            import cv2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("opencv-python 不可用") from exc

        capture = cv2.VideoCapture(file_path)
        if not capture.isOpened():
            raise RuntimeError("OpenCV 无法打开视频文件")

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (frame_count / fps) if fps > 0 and frame_count > 0 else 0.0
        if duration <= 0:
            capture.release()
            raise RuntimeError("无法读取视频时长")

        segments = self._build_segment_windows(duration)
        payloads: List[_VideoSegmentPayload] = []
        try:
            for index, (start, end) in enumerate(segments):
                segment_dir = os.path.join(cache_dir, f"segment_{index:03d}")
                os.makedirs(segment_dir, exist_ok=True)
                frame_paths = []
                for frame_index, timestamp in enumerate(
                    _sample_timestamps(start, end, Config.MULTIMODAL_VIDEO_FRAMES_PER_SEGMENT)
                ):
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        continue
                    frame_path = os.path.join(segment_dir, f"frame_{frame_index:02d}.jpg")
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    Image.fromarray(rgb_frame).save(frame_path, format="JPEG")
                    frame_paths.append(frame_path)

                if frame_paths:
                    payloads.append(
                        _VideoSegmentPayload(
                            segment_index=index,
                            start=start,
                            end=end,
                            frame_paths=frame_paths,
                            audio_path=None,
                        )
                    )
        finally:
            capture.release()

        return payloads

    def _extract_video_segments_with_moviepy(
        self,
        file_path: str,
        cache_dir: str,
    ) -> List[_VideoSegmentPayload]:
        try:
            from moviepy.video.io.VideoFileClip import VideoFileClip  # type: ignore
        except ImportError as exc:
            raise RuntimeError("moviepy 不可用") from exc

        payloads: List[_VideoSegmentPayload] = []
        with VideoFileClip(file_path) as video:
            duration = float(video.duration or 0.0)
            if duration <= 0:
                raise RuntimeError("moviepy 无法读取视频时长")

            segments = self._build_segment_windows(duration)
            for index, (start, end) in enumerate(segments):
                segment_dir = os.path.join(cache_dir, f"segment_{index:03d}")
                os.makedirs(segment_dir, exist_ok=True)
                frame_paths = []
                for frame_index, timestamp in enumerate(
                    _sample_timestamps(start, end, Config.MULTIMODAL_VIDEO_FRAMES_PER_SEGMENT)
                ):
                    frame = video.get_frame(timestamp)
                    frame_path = os.path.join(segment_dir, f"frame_{frame_index:02d}.jpg")
                    Image.fromarray(frame.astype("uint8")).save(frame_path, format="JPEG")
                    frame_paths.append(frame_path)

                audio_path = None
                try:
                    subvideo = video.subclip(start, end)
                    if subvideo.audio is not None:
                        audio_path = os.path.join(segment_dir, "segment_audio.mp3")
                        subvideo.audio.write_audiofile(
                            audio_path,
                            codec="mp3",
                            verbose=False,
                            logger=None,
                        )
                except Exception as exc:
                    logger.warning(
                        "moviepy 提取音频失败，继续使用画面信息: "
                        f"{file_path}: {exc}"
                    )

                if frame_paths:
                    payloads.append(
                        _VideoSegmentPayload(
                            segment_index=index,
                            start=start,
                            end=end,
                            frame_paths=frame_paths,
                            audio_path=audio_path,
                        )
                    )
        return payloads

    def _probe_duration_with_ffprobe(self, file_path: str, ffprobe_path: str) -> float:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout or "{}")
        duration = float(payload.get("format", {}).get("duration", 0.0) or 0.0)
        if duration <= 0:
            raise RuntimeError("ffprobe 未返回有效时长")
        return duration

    def _extract_frames_with_ffmpeg(
        self,
        file_path: str,
        ffmpeg_path: str,
        segment_dir: str,
        start: float,
        end: float,
        frame_count: int,
    ) -> List[str]:
        frame_paths: List[str] = []
        for frame_index, timestamp in enumerate(_sample_timestamps(start, end, frame_count)):
            frame_path = os.path.join(segment_dir, f"frame_{frame_index:02d}.jpg")
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    file_path,
                    "-frames:v",
                    "1",
                    frame_path,
                ],
                check=True,
            )
            if os.path.exists(frame_path):
                frame_paths.append(frame_path)
        return frame_paths

    def _extract_audio_with_ffmpeg(
        self,
        file_path: str,
        ffmpeg_path: str,
        segment_dir: str,
        start: float,
        end: float,
    ) -> Optional[str]:
        audio_path = os.path.join(segment_dir, "segment_audio.mp3")
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{start:.3f}",
                    "-to",
                    f"{end:.3f}",
                    "-i",
                    file_path,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    audio_path,
                ],
                check=True,
            )
        except Exception:
            return None
        return audio_path if os.path.exists(audio_path) else None

    def _transcribe_audio(self, audio_path: Optional[str]) -> str:
        if not audio_path or not os.path.exists(audio_path):
            return ""
        if not self.use_remote_analysis:
            return ""

        try:
            client = self._get_audio_llm_client()
            return client.transcribe_audio(audio_path, model=self.audio_model_name)
        except Exception as exc:
            logger.warning(
                "音频转写失败: "
                f"{exc}. 当前配置为 "
                f"base_url={Config.MULTIMODAL_AUDIO_BASE_URL}, "
                f"model={self.audio_model_name}"
            )
            return ""

    def _build_segment_windows(self, duration: float) -> List[tuple[float, float]]:
        segment_length = max(5, Config.MULTIMODAL_VIDEO_SEGMENT_SECONDS)
        starts = list(range(0, max(int(math.ceil(duration)), 1), segment_length))
        windows = [(float(start), min(float(start + segment_length), duration)) for start in starts]
        windows = [window for window in windows if window[1] - window[0] > 0.5]
        if len(windows) <= Config.MULTIMODAL_MAX_VIDEO_SEGMENTS:
            return windows

        last_index = len(windows) - 1
        sampled: List[tuple[float, float]] = []
        for i in range(Config.MULTIMODAL_MAX_VIDEO_SEGMENTS):
            idx = int(round(i * last_index / max(Config.MULTIMODAL_MAX_VIDEO_SEGMENTS - 1, 1)))
            sampled.append(windows[idx])
        # 去重，避免极短视频时重复采样
        deduped: List[tuple[float, float]] = []
        seen = set()
        for start, end in sampled:
            key = (round(start, 3), round(end, 3))
            if key in seen:
                continue
            seen.add(key)
            deduped.append((start, end))
        return deduped


def _format_seconds(value: float) -> str:
    total_seconds = max(int(value), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _make_block_id(file_path: str, block_type: str, index: int) -> str:
    raw = f"{file_path}:{block_type}:{index}"
    return "blk_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _make_data_url(file_path: str) -> str:
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _normalize_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace("，", ",").split(",")]
        return [item for item in parts if item]

    if isinstance(value, Iterable):
        items = []
        for item in value:
            item_str = str(item).strip()
            if item_str:
                items.append(item_str)
        return items
    return []


def _sample_timestamps(start: float, end: float, count: int) -> List[float]:
    duration = max(end - start, 0.0)
    if count <= 1 or duration <= 0:
        return [start]

    step = duration / count
    return [start + (idx + 0.5) * step for idx in range(count)]


def _resolve_binary_path(binary_name: str, configured_path: str = "") -> Optional[str]:
    candidates: List[str] = []
    configured_path = str(configured_path or "").strip()
    if configured_path:
        candidates.append(configured_path)

    env_keys = {
        "ffmpeg": ["FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE"],
        "ffprobe": ["FFPROBE_BINARY"],
    }.get(binary_name, [])
    for key in env_keys:
        value = str(os.environ.get(key, "") or "").strip()
        if value:
            candidates.append(value)

    path_hit = shutil.which(binary_name)
    if path_hit:
        candidates.append(path_hit)

    home = os.path.expanduser("~")
    candidates.extend(
        [
            os.path.join(home, "ENTER/envs/oasis-venv/bin", binary_name),
            os.path.join(home, ".local/bin", binary_name),
            f"/usr/bin/{binary_name}",
            f"/usr/local/bin/{binary_name}",
            f"/opt/homebrew/bin/{binary_name}",
            f"/opt/local/bin/{binary_name}",
        ]
    )

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
