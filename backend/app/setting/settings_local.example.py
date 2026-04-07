"""Local-only secret overrides.

Copy this file to settings_local.py for machine-specific secrets.
The real settings_local.py is gitignored and should never be committed.
"""

LLM_API_KEY = ""
ZEP_API_KEY = ""

# Optional overrides:
# LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# LLM_MODEL_NAME = "qwen-plus"
# MULTIMODAL_AUDIO_API_KEY = LLM_API_KEY
# MULTIMODAL_AUDIO_BASE_URL = LLM_BASE_URL
