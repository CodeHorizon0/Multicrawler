from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CrawlerConfig:
    seed: str
    data_dir: Path
    max_depth: int = 2
    max_pages: int = 500
    max_global_concurrency: int = 12
    min_global_concurrency: int = 2
    request_timeout: float = 25.0
    browser_timeout: float = 40.0
    checkpoint_every: int = 20
    max_retries: int = 3
    save_format: str = "mhtml"
    respect_robots: bool = True
    allowed_schemes: tuple[str, ...] = ("http", "https")
    max_links_per_page: int = 200
    max_queued_pages: int = 10000
    same_domain_only: bool = False
