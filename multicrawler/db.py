from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS frontier (
    url TEXT PRIMARY KEY,
    depth INTEGER NOT NULL,
    referrer TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    retries INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    protocol_hint TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visited (
    url TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    http_version TEXT,
    content_type TEXT,
    bytes INTEGER NOT NULL DEFAULT 0,
    saved_path TEXT,
    error TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    url TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS domain_policies (
    domain TEXT PRIMARY KEY,
    preferred_transport TEXT,
    preferred_protocol TEXT,
    browser_required INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status);
CREATE INDEX IF NOT EXISTS idx_frontier_depth ON frontier(depth);
"""


@dataclass(slots=True)
class FrontierItem:
    url: str
    depth: int
    referrer: str | None = None
    status: str = "queued"
    retries: int = 0
    last_error: str | None = None
    protocol_hint: str | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def enqueue(self, item: FrontierItem) -> bool:
        assert self.conn is not None
        cur = await self.conn.execute(
            """
            INSERT OR IGNORE INTO frontier(url, depth, referrer, status, retries, last_error, protocol_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item.url, item.depth, item.referrer, item.status, item.retries, item.last_error, item.protocol_hint),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def pop_queued(self, limit: int) -> list[FrontierItem]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """
            SELECT url, depth, referrer, status, retries, last_error, protocol_hint
            FROM frontier
            WHERE status = 'queued'
            ORDER BY depth ASC, updated_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        items = [
            FrontierItem(
                url=row["url"],
                depth=row["depth"],
                referrer=row["referrer"],
                status=row["status"],
                retries=row["retries"],
                last_error=row["last_error"],
                protocol_hint=row["protocol_hint"],
            )
            for row in rows
        ]
        for item in items:
            await self.conn.execute(
                "UPDATE frontier SET status='in_progress', updated_at=CURRENT_TIMESTAMP WHERE url=?",
                (item.url,),
            )
        await self.conn.commit()
        return items

    async def mark_frontier_done(self, url: str, status: str = "done", error: str | None = None) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "UPDATE frontier SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE url=?",
            (status, error, url),
        )
        await self.conn.commit()

    async def mark_visited(
        self,
        url: str,
        domain: str,
        status: str,
        http_version: str | None = None,
        content_type: str | None = None,
        bytes_count: int = 0,
        saved_path: str | None = None,
        error: str | None = None,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO visited(url, domain, status, http_version, content_type, bytes, saved_path, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status=excluded.status,
                http_version=excluded.http_version,
                content_type=excluded.content_type,
                bytes=excluded.bytes,
                saved_path=excluded.saved_path,
                error=excluded.error,
                fetched_at=CURRENT_TIMESTAMP
            """,
            (url, domain, status, http_version, content_type, bytes_count, saved_path, error),
        )
        await self.conn.commit()

    async def store_artifact(self, url: str, domain: str, path: str, format_: str, bytes_count: int) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO artifacts(url, domain, path, format, bytes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                domain=excluded.domain,
                path=excluded.path,
                format=excluded.format,
                bytes=excluded.bytes,
                created_at=CURRENT_TIMESTAMP
            """,
            (url, domain, path, format_, bytes_count),
        )
        await self.conn.commit()

    async def set_domain_policy(
        self,
        domain: str,
        preferred_transport: str | None,
        preferred_protocol: str | None,
        browser_required: bool,
    ) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO domain_policies(domain, preferred_transport, preferred_protocol, browser_required)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                preferred_transport=excluded.preferred_transport,
                preferred_protocol=excluded.preferred_protocol,
                browser_required=excluded.browser_required,
                updated_at=CURRENT_TIMESTAMP
            """,
            (domain, preferred_transport, preferred_protocol, 1 if browser_required else 0),
        )
        await self.conn.commit()

    async def get_domain_policy(self, domain: str) -> dict[str, object] | None:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """
            SELECT domain, preferred_transport, preferred_protocol, browser_required, updated_at
            FROM domain_policies
            WHERE domain = ?
            """,
            (domain,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def checkpoint(self, label: str, payload: str) -> None:
        assert self.conn is not None
        await self.conn.execute("INSERT INTO checkpoints(label, payload) VALUES (?, ?)", (label, payload))
        await self.conn.commit()

    async def counts(self) -> dict[str, int]:
        assert self.conn is not None
        result: dict[str, int] = {}
        for table in ("frontier", "visited", "artifacts", "domain_policies"):
            cursor = await self.conn.execute(f"SELECT COUNT(*) AS c FROM {table}")
            row = await cursor.fetchone()
            result[table] = int(row["c"])
        return result
