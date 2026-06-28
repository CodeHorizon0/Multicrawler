from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Sample:
    started: float
    finished: float
    bytes_count: int
    status_code: int | None = None


class AdaptiveLimiter:
    def __init__(self, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.current = minimum
        self.active = 0
        self._condition = asyncio.Condition()

    async def acquire(self) -> None:
        async with self._condition:
            while self.active >= self.current:
                await self._condition.wait()
            self.active += 1

    async def release(self) -> None:
        async with self._condition:
            self.active = max(0, self.active - 1)
            self._condition.notify_all()

    async def set_limit(self, new_limit: int) -> None:
        new_limit = max(self.minimum, min(self.maximum, new_limit))
        async with self._condition:
            self.current = new_limit
            self._condition.notify_all()


@dataclass
class ThroughputController:
    limiter: AdaptiveLimiter
    samples: deque[Sample] = field(default_factory=lambda: deque(maxlen=48))
    target_latency: float = 1.8
    min_bytes_per_sec: float = 120_000.0
    max_bytes_per_sec: float = 4_000_000.0

    def add_sample(self, sample: Sample) -> None:
        self.samples.append(sample)

    async def rebalance(self) -> None:
        if len(self.samples) < 4:
            return

        window = list(self.samples)
        elapsed = sum(max(0.001, item.finished - item.started) for item in window)
        bytes_count = sum(max(0, item.bytes_count) for item in window)
        throughput = bytes_count / max(0.001, elapsed)
        avg_latency = elapsed / len(window)

        current = self.limiter.current
        if throughput < self.min_bytes_per_sec or avg_latency > self.target_latency * 1.4:
            await self.limiter.set_limit(max(self.limiter.minimum, current - 1))
        elif throughput > self.max_bytes_per_sec and avg_latency < self.target_latency:
            await self.limiter.set_limit(min(self.limiter.maximum, current + 1))
