from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urldefrag, urlsplit

IGNORE_PREFIXES = ("mailto:", "javascript:", "tel:", "data:", "blob:", "sms:", "whatsapp:")
LINK_ATTRS = (
    "href",
    "src",
    "action",
    "data",
    "poster",
    "cite",
    "xlink:href",
    "data-src",
    "data-href",
    "data-url",
    "data-original",
)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _clean_candidate(base_url: str, candidate: str) -> str | None:
    candidate = candidate.strip()
    if not candidate or candidate.startswith(IGNORE_PREFIXES):
        return None

    lowered = candidate.lower()
    if lowered.startswith("//"):
        scheme = urlsplit(base_url).scheme or "https"
        candidate = f"{scheme}:{candidate}"

    if candidate.startswith("#"):
        return None

    resolved = urljoin(base_url, candidate)
    resolved, _ = urldefrag(resolved)
    scheme = urlsplit(resolved).scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    return resolved


def _add_candidate(base_url: str, links: set[str], value: str | None) -> None:
    if not value:
        return
    cleaned = _clean_candidate(base_url, value)
    if cleaned:
        links.add(cleaned)


def _extract_srcset(base_url: str, links: set[str], value: str | None) -> None:
    if not value:
        return
    for part in str(value).split(","):
        item = part.strip()
        if not item:
            continue
        url = item.split(None, 1)[0]
        _add_candidate(base_url, links, url)


def _extract_jsonld_urls(base_url: str, links: set[str], payload: str) -> None:
    try:
        data = json.loads(payload)
    except Exception:
        return

    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if isinstance(value, str) and key.lower() in {"url", "contenturl", "thumbnailurl", "embedurl", "sameas"}:
                    _add_candidate(base_url, links, value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)


def extract_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_tag = soup.find("base", href=True)
    if base_tag is not None:
        base_href = str(base_tag.get("href", "")).strip()
        if base_href:
            resolved_base = urljoin(base_url, base_href)
            resolved_base, _ = urldefrag(resolved_base)
            if urlsplit(resolved_base).scheme.lower() in {"http", "https"}:
                base_url = resolved_base

    links: set[str] = set()

    for tag in soup.find_all(True):
        if tag.name == "base":
            continue

        for attr in LINK_ATTRS:
            value = tag.get(attr)
            if value:
                _add_candidate(base_url, links, str(value))

        srcset = tag.get("srcset")
        if srcset:
            _extract_srcset(base_url, links, str(srcset))

        if tag.name == "meta" and str(tag.get("http-equiv", "")).lower() == "refresh":
            content = str(tag.get("content", ""))
            match = re.search(r"url\s*=\s*(.+)$", content, flags=re.IGNORECASE)
            if match:
                _add_candidate(base_url, links, match.group(1).strip().strip("'\""))

        if tag.name == "script" and str(tag.get("type", "")).lower() in {"application/ld+json", "application/json"}:
            payload = tag.string or tag.get_text(" ", strip=False)
            if payload:
                _extract_jsonld_urls(base_url, links, payload)

    raw_text = soup.get_text(" ", strip=False)
    for match in URL_RE.finditer(raw_text):
        _add_candidate(base_url, links, match.group(0))

    return sorted(links)


def is_likely_spa(html: str) -> bool:
    lowered = html.lower()
    score = 0
    if "__next_data__" in lowered or "window.__nuxt__" in lowered:
        score += 1
    if 'id="root"' in lowered or "id='root'" in lowered:
        score += 1
    if 'id="app"' in lowered or "id='app'" in lowered:
        score += 1
    if lowered.count("<script") > 8:
        score += 1
    if "data-reactroot" in lowered or "data-v-" in lowered:
        score += 1
    if len(lowered) < 4000:
        score += 1
    return score >= 2
