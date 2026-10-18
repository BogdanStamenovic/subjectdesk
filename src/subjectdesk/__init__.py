"""Subjectdesk: researched documents from subject-folder assignments."""

from __future__ import annotations

__version__ = "0.1.0"

from .cli import main
from .core import SubjectdeskError

__all__ = ["SubjectdeskError", "__version__", "main"]
