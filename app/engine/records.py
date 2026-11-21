"""Shared data contract. Parsers emit Records; rules emit Findings; the UI reads only Result dicts.

Frozen at 23:15 - changes need agreement between engine owner and UI builder.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

PLATFORMS = ("instagram", "whatsapp", "spotify", "google", "gmail", "chrome", "device", "ios", "android")
CATEGORIES = ("location", "interest", "contact", "activity", "account", "message", "device")
CORE_CATEGORIES = ("location", "interest", "contact", "activity")  # coverage grid columns


@dataclass
class Record:
    id: str
    platform: str
    category: str
    item: str
    timestamp: str | None  # ISO 8601 UTC, or None
    kind: str = "recorded"  # "recorded" | "inferred"
    inferenceOrigin: str | None = None  # "platform" | "app" | None
    sourceFile: str = ""
    recordRef: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        assert self.platform in PLATFORMS, self.platform
        assert self.category in CATEGORIES, self.category
        assert self.kind in ("recorded", "inferred"), self.kind


@dataclass
class Finding:
    id: str
    layer: int  # 1-5
    title: str
    detail: str
    priority: str  # "high" | "medium" | "low"
    category: str
    platforms: list[str]
    metric: dict[str, Any]  # {"value": 23, "unit": "companies"}
    evidence: list[str]  # Record ids
    action: dict[str, Any]  # {"steps": [...], "link": "https://..."}

    def __post_init__(self):
        assert self.priority in ("high", "medium", "low"), self.priority
        assert 1 <= self.layer <= 5


class ParseError(Exception):
    """Raised by parsers; code is one of the UI error codes."""

    CODES = ("wrong_format", "corrupt_zip", "too_large", "html_export", "unknown")

    def __init__(self, code: str, message: str, file: str = ""):
        assert code in self.CODES, code
        super().__init__(message)
        self.code, self.message, self.file = code, message, file

    def to_dict(self):
        return {"code": self.code, "message": self.message, "file": self.file}


def empty_coverage(platform: str) -> dict[str, str]:
    return {c: "not_assessed" for c in CORE_CATEGORIES}


def to_dict(obj) -> dict:
    return asdict(obj)
