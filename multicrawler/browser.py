from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright

from .models import FetchOutcome
from .profiles import pick_profile


@dataclass(slots=True)
class BrowserCapture:
    outcome: FetchOutcome
    mhtml_path: Path | None
    html_path: Path | None


class BrowserManager:
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()
        self._profile = pick_profile()

    async def open(self) -> None:
        async with self._lock:
            if self._context is not None:
                return

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                ignore_https_errors=True,
                viewport={"width": 1365, "height": 900},
                user_agent=self._profile["user_agent"],
                locale=self._profile["accept_language"].split(",", 1)[0],
            )

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def _ensure_context(self):
        if self._context is None:
            await self.open()
        assert self._context is not None
        return self._context

    async def _collect_protocol(self, url: str, wait_until: str) -> tuple[str | None, str, str]:
        context = await self._ensure_context()
        page = await context.new_page()
        protocols: list[str] = []

        cdp = await context.new_cdp_session(page)
        await cdp.send("Network.enable")

        def on_response(event: dict) -> None:
            response = event.get("response", {})
            protocol = str(response.get("protocol", "")).lower()
            if protocol:
                protocols.append(protocol)

        cdp.on("Network.responseReceived", on_response)

        try:
            try:
                await page.goto(url, wait_until=wait_until, timeout=self.timeout_ms)
            except Exception:
                try:
                    await page.goto(url, wait_until="commit", timeout=self.timeout_ms)
                except Exception:
                    pass

            html = await page.content()
            final_url = page.url

            protocol = None
            for candidate in protocols:
                if candidate in {"h3", "h2", "http/1.1"}:
                    protocol = candidate
                    break

            return protocol, final_url, html
        finally:
            await page.close()

    async def probe_protocol(self, url: str) -> str | None:
        protocol, _, _ = await self._collect_protocol(url, wait_until="domcontentloaded")
        return protocol

    async def capture(self, url: str, mhtml_path: Path | None, html_path: Path | None) -> BrowserCapture:
        context = await self._ensure_context()
        page = await context.new_page()
        protocols: list[str] = []

        cdp = await context.new_cdp_session(page)
        await cdp.send("Network.enable")

        def on_response(event: dict) -> None:
            response = event.get("response", {})
            protocol = str(response.get("protocol", "")).lower()
            if protocol:
                protocols.append(protocol)

        cdp.on("Network.responseReceived", on_response)

        try:
            try:
                await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                except Exception:
                    pass

            html = await page.content()

            if html_path is not None:
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html, encoding="utf-8", errors="ignore")

            if mhtml_path is not None:
                mhtml_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                mhtml_text = snapshot.get("data", "")
                mhtml_path.write_text(mhtml_text, encoding="utf-8", errors="ignore")

            protocol = None
            for candidate in protocols:
                if candidate in {"h3", "h2", "http/1.1"}:
                    protocol = candidate
                    break

            outcome = FetchOutcome(
                url=url,
                final_url=page.url,
                status_code=200,
                http_version=protocol,
                content_type="text/html",
                body=html,
                raw_bytes=len(html.encode("utf-8", errors="ignore")),
                elapsed=0.0,
                transport="browser",
                user_agent=await page.evaluate("navigator.userAgent"),
            )

            return BrowserCapture(outcome=outcome, mhtml_path=mhtml_path, html_path=html_path)
        finally:
            await page.close()
