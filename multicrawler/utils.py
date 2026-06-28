from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urldefrag, urlsplit, urlunsplit

INVALID_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or "unknown"
    return host.replace(":", "_")


def safe_filename_from_url(url: str, suffix: str) -> str:
    parts = urlsplit(url)
    stem = parts.path.strip("/") or "index"
    stem = stem.replace("/", "__")
    if parts.query:
        stem += "__q_" + hashlib.sha1(parts.query.encode("utf-8")).hexdigest()[:12]
    stem = INVALID_CHARS.sub("_", stem)
    stem = stem[:180]
    return f"{stem}{suffix}"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_alt_svc(header: str | None) -> bool:
    if not header:
        return False
    lower = header.lower()
    return "h3" in lower or "quic" in lower
