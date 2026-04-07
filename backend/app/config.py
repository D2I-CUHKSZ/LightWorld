"""Backward-compatible config import.

Prefer importing `Config` from `app.core.settings`.
"""

from .setting.settings import Config

__all__ = ["Config"]
