from pathlib import Path

from PIL import Image

from app.application.multimodal_ingestion import (
    MultimodalIngestionService,
    _VideoSegmentPayload,
)


def test_ingest_text_and_image_files(tmp_path):
    text_path = tmp_path / "brief.txt"
    text_path.write_text("武汉大学回应网络舆情，校友和媒体持续跟进。", encoding="utf-8")

    image_path = tmp_path / "poster.png"
    Image.new("RGB", (32, 24), color=(255, 255, 255)).save(image_path)

    service = MultimodalIngestionService()
    service._analyze_image_with_llm = lambda *args, **kwargs: {
        "summary": "海报显示高校声明和媒体报道截图。",
        "visible_text": "武汉大学 官方声明",
        "key_entities": ["武汉大学", "媒体"],
        "social_signals": ["官方回应", "舆论扩散"],
        "evidence_text": "图片包含高校声明与媒体传播线索。",
    }

    result = service.ingest_files(
        [
            {"path": str(text_path), "display_name": "brief.txt"},
            {"path": str(image_path), "display_name": "poster.png"},
        ],
        simulation_requirement="模拟高校品牌舆情传播",
    )

    assert len(result["document_texts"]) == 2
    assert result["manifest"]["file_count"] == 2
    assert result["manifest"]["block_count"] == 2
    assert "document" in result["manifest"]["modalities"]
    assert "image" in result["manifest"]["modalities"]
    assert "武汉大学回应网络舆情" in result["all_text"]
    assert "[IMAGE][source=poster.png]" in result["all_text"]
    assert "VisibleText: 武汉大学 官方声明" in result["all_text"]


def test_ingest_video_file_uses_segment_blocks(tmp_path):
    video_path = tmp_path / "news.mp4"
    video_path.write_bytes(b"fake-video")

    frame_a = tmp_path / "frame_a.jpg"
    frame_b = tmp_path / "frame_b.jpg"
    Image.new("RGB", (16, 16), color=(10, 10, 10)).save(frame_a)
    Image.new("RGB", (16, 16), color=(20, 20, 20)).save(frame_b)

    service = MultimodalIngestionService()
    service._extract_video_segments = lambda *_args, **_kwargs: [
        _VideoSegmentPayload(
            segment_index=0,
            start=0.0,
            end=30.0,
            frame_paths=[str(frame_a), str(frame_b)],
            audio_path=None,
        )
    ]
    service._transcribe_audio = lambda *_args, **_kwargs: "学生发布视频，媒体随后转载。"
    service._analyze_video_segment_with_llm = lambda *args, **kwargs: {
        "summary": "视频片段展示校园声明发布与媒体跟进。",
        "visible_text": "官方声明",
        "key_entities": ["学生", "媒体", "高校"],
        "social_signals": ["声明发布", "媒体转载"],
        "evidence_text": "视频画面和转写都表明事件进入公开传播阶段。",
    }

    result = service.ingest_files(
        [{"path": str(video_path), "display_name": "news.mp4"}],
        simulation_requirement="模拟校园事件扩散",
    )

    assert result["manifest"]["file_count"] == 1
    assert result["manifest"]["block_count"] == 1
    assert result["manifest"]["modalities"] == ["video"]
    assert "[VIDEO_SEGMENT][source=news.mp4][00:00:00-00:00:30]" in result["all_text"]
    assert "Transcript: 学生发布视频，媒体随后转载。" in result["all_text"]
    assert "KeyEntities: 学生, 媒体, 高校" in result["all_text"]
