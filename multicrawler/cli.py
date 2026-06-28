
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from typing import Any

from .config import CrawlerConfig
from .crawler import Crawler

try:
    import psutil
except Exception:
    psutil: Any | None = None


def _logical_cpu_count() -> int:
    if psutil is not None:
        try:
            value = psutil.cpu_count(logical=True)
            if value:
                return int(value)
        except Exception:
            pass
    return max(1, os.cpu_count() or 1)


def _physical_core_count() -> int:
    if psutil is not None:
        try:
            value = psutil.cpu_count(logical=False)
            if value:
                return int(value)
        except Exception:
            pass
    logical = _logical_cpu_count()
    return max(1, logical // 2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="multicrawler")
    parser.add_argument("--seed", required=True, help="Seed URL")
    parser.add_argument("--data-dir", default="./data", help="Directory for database and archived pages")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=500, help="Maximum number of pages to save")
    parser.add_argument("--max-links-per-page", type=int, default=200, help="Maximum extracted links per page")
    parser.add_argument("--max-queued-pages", type=int, default=10000, help="Maximum pending pages in frontier")
    parser.add_argument("--same-domain-only", action="store_true", help="Do not leave the seed domain")
    parser.add_argument("--global-concurrency", type=int, default=_logical_cpu_count())
    parser.add_argument("--min-global-concurrency", type=int, default=_physical_core_count())
    parser.add_argument("--request-timeout", type=float, default=25.0)
    parser.add_argument("--browser-timeout", type=float, default=40.0)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    parser.add_argument("--save-format", choices=("mhtml", "html"), default="mhtml")
    parser.add_argument("--no-robots", action="store_true")
    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def main() -> int:
    _configure_logging()
    args = build_parser().parse_args()
    config = CrawlerConfig(
        seed=args.seed,
        data_dir=Path(args.data_dir),
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        max_global_concurrency=args.global_concurrency,
        min_global_concurrency=args.min_global_concurrency,
        request_timeout=args.request_timeout,
        browser_timeout=args.browser_timeout,
        checkpoint_every=args.checkpoint_every,
        save_format=args.save_format,
        respect_robots=not args.no_robots,
        max_links_per_page=args.max_links_per_page,
        max_queued_pages=args.max_queued_pages,
        same_domain_only=args.same_domain_only,
    )
    crawler = Crawler(config)
    return asyncio.run(crawler.run())
