from __future__ import annotations

from pathlib import Path

from .browser import BrowserManager
from .utils import ensure_dir, safe_filename_from_url


class Archiver:
    def __init__(self, root: Path, browser: BrowserManager) -> None:
        self.root = root
        self.browser = browser

    def domain_dir(self, domain: str) -> Path:
        path = self.root / "domains" / domain
        ensure_dir(path)
        return path

    def pick_targets(self, domain: str, url: str) -> tuple[Path, Path]:
        folder = self.domain_dir(domain)
        mhtml = folder / safe_filename_from_url(url, ".mhtml")
        html = folder / safe_filename_from_url(url, ".html")
        return mhtml, html
