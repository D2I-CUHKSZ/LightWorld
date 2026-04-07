"""Application settings.

This module centralizes environment loading and configuration in a style
similar to common production Python service layouts.
"""

import os

from dotenv import load_dotenv


# Prefer repository root .env, then backend/.env as compatibility fallback.
_current_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root_env = os.path.abspath(os.path.join(_current_dir, "../../../.env"))
_backend_env = os.path.abspath(os.path.join(_current_dir, "../../.env"))

if os.path.exists(_repo_root_env):
    load_dotenv(_repo_root_env, override=True)
elif os.path.exists(_backend_env):
    load_dotenv(_backend_env, override=True)
else:
    load_dotenv(override=True)


class Config:
    """Flask config."""

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "mirofish-secret-key")
    DEBUG = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    JSON_AS_ASCII = False

    # LLM
    # Public defaults live here; secrets should come from .env or settings_local.py.
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL = os.environ.get(
        "LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "qwen-plus")
    LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "90"))

    # Zep
    ZEP_API_KEY = os.environ.get("ZEP_API_KEY", "")

    # Files
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 50MB
    BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    INPUT2GRAPH_ROOT = os.path.join(BACKEND_ROOT, "input2graph")
    OUTPUT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, "..", "output"))
    UPLOAD_FOLDER = INPUT2GRAPH_ROOT
    DOCUMENT_EXTENSIONS = {"pdf", "md", "txt", "markdown"}
    IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tiff", "tif"}
    VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}
    ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

    # Text processing
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # Multimodal ingestion
    # 多模态理解走 Qwen Omni，音频转写走 Qwen ASR
    MULTIMODAL_VISION_MODEL_NAME = "qwen3-omni-flash"
    MULTIMODAL_AUDIO_MODEL_NAME = "qwen3-asr-flash"
    MULTIMODAL_AUDIO_API_KEY = os.environ.get("MULTIMODAL_AUDIO_API_KEY", "")
    MULTIMODAL_AUDIO_BASE_URL = os.environ.get("MULTIMODAL_AUDIO_BASE_URL", "")
    MULTIMODAL_VIDEO_SEGMENT_SECONDS = int(
        os.environ.get("MULTIMODAL_VIDEO_SEGMENT_SECONDS", "30")
    )
    MULTIMODAL_VIDEO_FRAMES_PER_SEGMENT = int(
        os.environ.get("MULTIMODAL_VIDEO_FRAMES_PER_SEGMENT", "4")
    )
    MULTIMODAL_MAX_VIDEO_SEGMENTS = int(
        os.environ.get("MULTIMODAL_MAX_VIDEO_SEGMENTS", "12")
    )
    MULTIMODAL_FFMPEG_PATH = os.environ.get("MULTIMODAL_FFMPEG_PATH", "")
    MULTIMODAL_FFPROBE_PATH = os.environ.get("MULTIMODAL_FFPROBE_PATH", "")
    MULTIMODAL_USE_REMOTE_ANALYSIS = os.environ.get(
        "MULTIMODAL_USE_REMOTE_ANALYSIS",
        "true",
    ).lower() == "true"

    # OASIS simulation
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get("OASIS_DEFAULT_MAX_ROUNDS", "10"))
    OASIS_SIMULATION_DATA_DIR = os.path.join(OUTPUT_ROOT, "simulations")
    REPORTS_DIR = os.path.join(OUTPUT_ROOT, "reports")

    OASIS_TWITTER_ACTIONS = [
        "CREATE_POST", "CREATE_COMMENT", "LIKE_POST", "LIKE_COMMENT",
        "REPOST", "FOLLOW", "DO_NOTHING", "QUOTE_POST"
    ]
    OASIS_REDDIT_ACTIONS = [
        "LIKE_POST", "DISLIKE_POST", "CREATE_POST", "CREATE_COMMENT",
        "LIKE_COMMENT", "DISLIKE_COMMENT", "SEARCH_POSTS", "SEARCH_USER",
        "TREND", "REFRESH", "DO_NOTHING", "FOLLOW", "MUTE"
    ]

    # Report Agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get("REPORT_AGENT_MAX_TOOL_CALLS", "5"))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get("REPORT_AGENT_MAX_REFLECTION_ROUNDS", "2"))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get("REPORT_AGENT_TEMPERATURE", "0.5"))

    # Simulation preparation
    SIMULATION_ENTITY_PROMPTS_USE_LLM = os.environ.get(
        "SIMULATION_ENTITY_PROMPTS_USE_LLM",
        "true",
    ).lower() == "true"

    @classmethod
    def validate(cls):
        """Validate required env vars."""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        return errors


def _apply_local_overrides():
    try:
        from . import settings_local
    except ImportError:
        return

    for name in dir(settings_local):
        if name.isupper():
            setattr(Config, name, getattr(settings_local, name))


def _finalize_derived_settings():
    if not Config.MULTIMODAL_AUDIO_API_KEY:
        Config.MULTIMODAL_AUDIO_API_KEY = Config.LLM_API_KEY
    if not Config.MULTIMODAL_AUDIO_BASE_URL:
        Config.MULTIMODAL_AUDIO_BASE_URL = Config.LLM_BASE_URL


_apply_local_overrides()
_finalize_derived_settings()
