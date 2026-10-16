import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            hits = self.hits[key]
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def client_ip(request: Request, trusted_proxies: frozenset[str]) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in trusted_proxies:
        return forwarded.split(",")[-1].strip()
    return peer
