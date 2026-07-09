from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx

from .archiver import Archiver
from .browser import BrowserManager
from .config import CrawlerConfig
from .controller import AdaptiveLimiter, Sample, ThroughputController
from .db import Database, FrontierItem
from .extractor import extract_links, is_likely_spa
from .http_client import HttpClient, HttpProbe
from .models import FetchOutcome
from .robots import RobotsManager
from .transport import TransportSelector
from .utils import domain_of, ensure_dir, normalize_url


def _extract_links_job(base_url: str, html: str) -> list[str]:
    return extract_links(base_url, html)


def _format_http_version(version: str | None) -> str:
    if not version:
        return "HTTP/?"
    normalized = version.strip().lower()
    mapping = {
        "h3": "HTTP/3",
        "h2": "HTTP/2",
        "h1": "HTTP/1.1",
        "http/3": "HTTP/3",
        "http/2": "HTTP/2",
        "http/1.1": "HTTP/1.1",
        "http/1": "HTTP/1.1",
    }
    return mapping.get(normalized, version.upper())


class Crawler:
    def __init__(self, config: CrawlerConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("multicrawler")
        self.db = Database(config.data_dir / "crawler.sqlite3")
        self.http_client = HttpClient(config.request_timeout)
        self.browser = BrowserManager(timeout_ms=int(config.browser_timeout * 1000))
        self.archiver = Archiver(config.data_dir, self.browser)
        self.transport_selector = TransportSelector()
        self.robots = RobotsManager()
        self.shutdown_event = asyncio.Event()
        self.queue: asyncio.Queue[FrontierItem] = asyncio.Queue()
        self.global_limiter = AdaptiveLimiter(config.min_global_concurrency, config.max_global_concurrency)
        self.controller = ThroughputController(self.global_limiter)
        self.process_pool = ProcessPoolExecutor(max_workers=max(1, os.cpu_count() or 1))
        self.pages_seen = 0
        self.seed_domain = domain_of(normalize_url(config.seed))
        self._signal_count = 0
        self._main_task: asyncio.Task[object] | None = None
        self._managed_tasks: list[asyncio.Task[object]] = []

    async def initialize(self) -> None:
        ensure_dir(self.config.data_dir)
        await self.db.open()
        await self.http_client.open()
        queued = await self.db.pop_queued(limit=100000)
        for item in queued:
            await self.queue.put(item)

        if self.queue.empty():
            seed_url = normalize_url(self.config.seed)
            await self.db.enqueue(FrontierItem(url=seed_url, depth=0, referrer=None))
            await self.queue.put(FrontierItem(url=seed_url, depth=0, referrer=None))

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def force_cancel() -> None:
            for task in list(self._managed_tasks):
                if not task.done():
                    task.cancel()
            if self._main_task is not None and not self._main_task.done():
                self._main_task.cancel()

        def request_stop() -> None:
            self._signal_count += 1
            self.shutdown_event.set()

            if self._signal_count == 1:
                self.logger.info("Shutdown requested, finishing in-flight work before exit.")
                return

            self.logger.warning("Force shutdown requested, cancelling remaining work.")
            force_cancel()

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, request_stop)
            except NotImplementedError:
                signal.signal(sig, lambda *_: request_stop())

    async def run(self) -> int:
        self._main_task = asyncio.current_task()
        await self.initialize()
        self.install_signal_handlers()

        workers = [asyncio.create_task(self.worker(i), name=f"worker-{i}") for i in range(self.config.max_global_concurrency)]
        rebalancer = asyncio.create_task(self.rebalance_loop(), name="rebalancer")
        checkpoint = asyncio.create_task(self.checkpoint_loop(), name="checkpoint")
        self._managed_tasks = [*workers, rebalancer, checkpoint]

        interrupted = False
        try:
            await self.queue.join()
        except asyncio.CancelledError:
            interrupted = True
        finally:
            self.shutdown_event.set()
            for task in self._managed_tasks:
                task.cancel()
            await asyncio.gather(*self._managed_tasks, return_exceptions=True)

            counts = await self.db.counts()
            await self.db.checkpoint(
                "shutdown",
                json.dumps({"counts": counts, "pages_seen": self.pages_seen}, ensure_ascii=False),
            )

            await self.browser.close()
            await self.http_client.close()
            await self.db.close()
            self.process_pool.shutdown(wait=True, cancel_futures=True)

        return 130 if interrupted else 0

    async def rebalance_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(5.0)
            await self.controller.rebalance()

    async def checkpoint_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(max(10, self.config.checkpoint_every))
            counts = await self.db.counts()
            payload = json.dumps(
                {
                    "pages_seen": self.pages_seen,
                    "queue_size": self.queue.qsize(),
                    "counts": counts,
                    "global_limit": self.global_limiter.current,
                },
                ensure_ascii=False,
            )
            await self.db.checkpoint("periodic", payload)

    async def worker(self, worker_id: int) -> None:
        while True:
            if self.shutdown_event.is_set() and self.queue.empty():
                return

            if self.pages_seen >= self.config.max_pages:
                self.shutdown_event.set()

            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if self.shutdown_event.is_set() and self.queue.empty():
                    return
                continue
            except asyncio.CancelledError:
                return

            try:
                await self.process_item(item)
            finally:
                self.queue.task_done()

    async def process_item(self, item: FrontierItem) -> None:
        url = normalize_url(item.url)
        domain = domain_of(url)
        if item.depth > self.config.max_depth:
            await self.db.mark_frontier_done(url, "depth_exceeded")
            return

        profile = self.http_client.default_headers()
        allowed = await self.robots.can_fetch(
            client=self.http_client.client,
            url=url,
            user_agent=profile["User-Agent"],
            respect_robots=self.config.respect_robots,
        )

        if not allowed:
            await self.db.mark_visited(url, domain, "blocked_by_robots", error="robots.txt disallow")
            await self.db.mark_frontier_done(url, "blocked_by_robots")
            return

        await self.global_limiter.acquire()
        started = monotonic()
        body = ""
        try:
            policy = await self.db.get_domain_policy(domain)
            browser_protocol_hint = None
            browser_required = False
            if policy:
                browser_protocol_hint = policy.get("preferred_protocol") or None
                browser_required = bool(policy.get("browser_required", 0))

            probe = await self.http_client.request(url)

            if probe.status_code in {204, 304}:
                await self.db.mark_visited(url, domain, "empty_response", http_version=probe.http_version)
                await self.db.mark_frontier_done(url, "done")
                return

            if probe.status_code == 404:
                await self.db.mark_visited(url, domain, "not_found", http_version=probe.http_version)
                await self.db.mark_frontier_done(url, "not_found")
                return

            if probe.status_code in {401, 403}:
                await self.db.mark_visited(url, domain, "access_denied", http_version=probe.http_version)
                await self.db.mark_frontier_done(url, "access_denied")
                return

            if probe.status_code >= 500 or probe.status_code == 429:
                raise RuntimeError(f"temporary http status: {probe.status_code}")

            if probe.status_code >= 400:
                await self.db.mark_visited(url, domain, f"http_{probe.status_code}", http_version=probe.http_version)
                await self.db.mark_frontier_done(url, f"http_{probe.status_code}")
                return

            alt_svc_h3 = probe.alt_svc_h3
            decision = await self.transport_selector.decide(probe, browser_protocol_hint, alt_svc_h3)

            if decision.transport == "browser" or browser_required or is_likely_spa(probe.body):
                capture = await self.capture_with_browser(url, domain)
                outcome = capture["outcome"]
                saved_path = capture["saved_path"]
                await self.db.set_domain_policy(domain, "browser", capture["protocol"], capture["protocol"] == "h3")
            else:
                outcome = probe.to_outcome("httpx")
                saved_path = await self.save_httpx_result(url, domain, outcome)
                await self.db.set_domain_policy(domain, "httpx", outcome.http_version, False)

            body = outcome.body or ""
            await self.db.mark_visited(
                url,
                domain,
                "saved",
                http_version=outcome.http_version,
                content_type=outcome.content_type,
                bytes_count=outcome.raw_bytes,
                saved_path=saved_path,
            )
            await self.db.mark_frontier_done(url, "done")

            http_version_text = _format_http_version(outcome.http_version)
            self.logger.info(
                "[%s] %s - %s - %s bytes",
                http_version_text,
                domain,
                outcome.status_code,
                outcome.raw_bytes,
            )

            if not self.shutdown_event.is_set():
                links = await self.extract_links_async(url, body)
                links = links[: self.config.max_links_per_page]
                queued_now = self.queue.qsize()
                for link in links:
                    if queued_now >= self.config.max_queued_pages:
                        break
                    if self.should_enqueue(link) and not self.shutdown_event.is_set():
                        child = FrontierItem(url=link, depth=item.depth + 1, referrer=url)
                        created = await self.db.enqueue(child)
                        if created and not self.shutdown_event.is_set():
                            await self.queue.put(child)
                            queued_now += 1

            self.pages_seen += 1

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("Failed to process %s", domain)
            await self.db.mark_visited(url, domain, "error", error=str(exc))
            retries = item.retries + 1
            if (not self.shutdown_event.is_set()) and retries <= self.config.max_retries:
                retry = FrontierItem(url=url, depth=item.depth, referrer=item.referrer, status="queued", retries=retries, last_error=str(exc))
                await self.db.enqueue(retry)
                await self.queue.put(retry)
            else:
                await self.db.mark_frontier_done(url, "failed", str(exc))
        finally:
            await self.global_limiter.release()
            ended = monotonic()
            self.controller.add_sample(
                Sample(started=started, finished=ended, bytes_count=len(body.encode("utf-8", errors="ignore")))
            )

    async def capture_with_browser(self, url: str, domain: str) -> dict[str, object]:
        mhtml_path, html_path = self.archiver.pick_targets(domain, url)
        if self.config.save_format.lower() == "html":
            mhtml_path = None

        capture = await self.browser.capture(url, mhtml_path=mhtml_path, html_path=html_path)
        outcome = capture.outcome
        saved_path = str(capture.html_path or capture.mhtml_path) if (capture.html_path or capture.mhtml_path) else None

        if saved_path is None:
            saved_path = str(html_path)
            html_path.write_text(outcome.body, encoding="utf-8", errors="ignore")

        bytes_count = Path(saved_path).stat().st_size if saved_path else outcome.raw_bytes
        await self.db.store_artifact(url, domain, saved_path, Path(saved_path).suffix.lstrip("."), bytes_count)

        http_version_text = _format_http_version(outcome.http_version)
        self.logger.info(
            "[%s] %s - %s - %s bytes",
            http_version_text,
            domain,
            outcome.status_code,
            outcome.raw_bytes,
        )

        return {"outcome": outcome, "saved_path": saved_path, "protocol": outcome.http_version}

    async def save_httpx_result(self, url: str, domain: str, outcome: FetchOutcome) -> str:
        folder = self.archiver.domain_dir(domain)
        filename = (urlsplit(url).path.strip("/") or "index").replace("/", "__")
        target = folder / f"{filename}.html"
        await asyncio.to_thread(target.write_text, outcome.body, "utf-8", "ignore")
        await self.db.store_artifact(url, domain, str(target), "html", target.stat().st_size)

        http_version_text = _format_http_version(outcome.http_version)
        self.logger.info(
            "[%s] %s - %s - %s bytes",
            http_version_text,
            domain,
            outcome.status_code,
            outcome.raw_bytes,
        )

        return str(target)

    async def extract_links_async(self, base_url: str, html: str) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.process_pool, _extract_links_job, base_url, html)

    def should_enqueue(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except Exception:
            return False
        if parts.scheme not in self.config.allowed_schemes or not parts.netloc:
            return False
        if self.config.same_domain_only and domain_of(url) != self.seed_domain:
            return False
        return True
