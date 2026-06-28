from __future__ import annotations

from urllib.parse import urlsplit

import httpx


class RobotsManager:
    def __init__(self) -> None:
        self._cache: dict[str, list[str]] = {}

    async def can_fetch(self, client: httpx.AsyncClient, url: str, user_agent: str, respect_robots: bool) -> bool:
        if not respect_robots:
            return True

        parts = urlsplit(url)
        domain = parts.netloc.lower()
        if domain not in self._cache:
            robots_url = f"{parts.scheme}://{domain}/robots.txt"
            self._cache[domain] = await self._download_robots(client, robots_url)

        lines = self._cache[domain]
        if not lines:
            return True

        path = parts.path or "/"
        allowed = True
        current_group = False

        for line in lines:
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            key, _, value = item.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                current_group = value == "*" or value.lower() in user_agent.lower()
            elif current_group and key == "disallow" and value and path.startswith(value):
                allowed = False
            elif current_group and key == "allow" and value and path.startswith(value):
                allowed = True

        return allowed

    async def _download_robots(self, client: httpx.AsyncClient, robots_url: str) -> list[str]:
        try:
            response = await client.get(robots_url, follow_redirects=True)
            if response.status_code >= 400:
                return []
            return response.text.splitlines()
        except Exception:
            return []
