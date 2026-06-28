from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FrontierItem:
    url: str
    depth: int
    referrer: str | None = None
    status: str = "queued"
    retries: int = 0
    last_error: str | None = None
    protocol_hint: str | None = None


@dataclass(slots=True)
class FetchOutcome:
    url: str
    final_url: str
    status_code: int
    http_version: str | None
    content_type: str | None
    body: str
    raw_bytes: int
    elapsed: float
    transport: str
    user_agent: str


@dataclass(slots=True)
class DomainPolicy:
    domain: str
    preferred_transport: str | None
    preferred_protocol: str | None
    browser_required: bool
    updated_at: str | None = None


@dataclass(slots=True)
class ArtifactRecord:
    url: str
    domain: str
    path: Path
    format: str
    bytes_count: int
