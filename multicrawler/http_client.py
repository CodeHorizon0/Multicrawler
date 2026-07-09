from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
import asyncio

import httpx

from .profiles import pick_profile


@dataclass(slots=True)
class HttpProbe:
    status_code: int
    http_version: str | None
    alt_svc_h3: bool
    content_type: str | None
    body: str
    raw_bytes: int
    elapsed: float
    final_url: str
    user_agent: str

    def to_outcome(self, transport: str) -> "FetchOutcome":
        from .models import FetchOutcome

        protocol = None
        if self.http_version:
            lowered = self.http_version.strip().lower()
            if lowered in {"http/2", "h2"}:
                protocol = "h2"
            elif lowered in {"http/3", "h3"}:
                protocol = "h3"
            elif lowered in {"http/1.1", "http/1", "h1"}:
                protocol = "h1"

        return FetchOutcome(
            url=self.final_url,
            final_url=self.final_url,
            status_code=self.status_code,
            http_version=protocol,
            content_type=self.content_type,
            body=self.body,
            raw_bytes=self.raw_bytes,
            elapsed=self.elapsed,
            transport=transport,
            user_agent=self.user_agent,
        )


class HttpClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.max_retries = 3
        self._client: httpx.AsyncClient | None = None
        self._profile = pick_profile()

    async def open(self) -> None:
        if self._client is None:
            limits = httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            )
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                http2=True,
                limits=limits,
                headers=self.default_headers(),
                verify=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "HttpClient.open() must be called before use"
        return self._client

    def default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._profile["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self._profile["accept_language"],
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        }

    async def request(self, url: str) -> HttpProbe:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            started = monotonic()
            try:
                response = await self.client.get(url, headers=self.default_headers())
                retry_status = response.status_code == 429 or response.status_code >= 500
                if retry_status and attempt < self.max_retries - 1:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                    await asyncio.sleep(min(delay, 15))
                    continue

                elapsed = monotonic() - started
                http_version = getattr(response, "http_version", None)
                content_type = response.headers.get("content-type")
                alt_svc_header = response.headers.get("alt-svc", "")
                alt_svc_h3 = "h3" in alt_svc_header.lower() or "quic" in alt_svc_header.lower()
                try:
                    body = response.text
                except Exception:
                    encoding = response.encoding or "utf-8"
                    body = response.content.decode(encoding, errors="ignore")
                return HttpProbe(
                    status_code=response.status_code,
                    http_version=http_version,
                    alt_svc_h3=alt_svc_h3,
                    content_type=content_type,
                    body=body,
                    raw_bytes=len(response.content),
                    elapsed=elapsed,
                    final_url=str(response.url),
                    user_agent=self.default_headers()["User-Agent"],
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        if last_error:
            raise last_error
        raise RuntimeError("request failed")

    async def probe(self, url: str) -> HttpProbe:
        return await self.request(url)
