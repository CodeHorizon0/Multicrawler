from __future__ import annotations

from dataclasses import dataclass

from .http_client import HttpProbe


@dataclass(slots=True)
class TransportDecision:
    transport: str
    preferred_protocol: str
    reason: str
    browser_required: bool = False


class TransportSelector:
    def __init__(self) -> None:
        pass

    async def decide(self, probe: HttpProbe, browser_protocol: str | None, alt_svc_h3: bool) -> TransportDecision:
        if browser_protocol == "h3":
            return TransportDecision("browser", "h3", "browser confirmed h3", True)
        if browser_protocol == "h2":
            return TransportDecision("browser", "h2", "browser confirmed h2", False)

        http_version = (probe.http_version or "").lower()
        if alt_svc_h3:
            return TransportDecision("browser", "h3", "alt-svc advertises h3", True)
        if http_version in {"http/2", "h2"}:
            return TransportDecision("httpx", "h2", "httpx negotiated h2")
        if http_version in {"http/1.1", "http/1", "h1"}:
            return TransportDecision("httpx", "h1", "httpx negotiated h1")
        return TransportDecision("httpx", "h1", "fallback to h1")
