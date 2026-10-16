"""Job queue (Module 18).

Redis list-based FIFO queue for production; an in-memory deque fallback keeps
development and tests functional without a Redis server. The queue carries
ONLY ephemeral coordination signals (job ids) — durable state lives in JobStore.
"""

import threading
from collections import deque
from typing import Protocol


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...
    def dequeue(self, timeout_s: float = 1.0) -> str | None: ...
    def requeue(self, job_id: str, delay_s: float = 0.0) -> None: ...


class InMemoryQueue:
    """Development/tests fallback. Thread-safe, no persistence."""

    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._lock = threading.Condition()

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            self._items.append(job_id)
            self._lock.notify()

    def dequeue(self, timeout_s: float = 1.0) -> str | None:
        with self._lock:
            if not self._items and not self._lock.wait(timeout=timeout_s):
                return None
            return self._items.popleft() if self._items else None

    def requeue(self, job_id: str, delay_s: float = 0.0) -> None:
        # Delay handling lives in the store via next_attempt_at; simply re-enqueue.
        self.enqueue(job_id)


class RedisQueue:
    """Redis-backed FIFO queue (BLPOP blocking dequeue)."""

    def __init__(self, redis_client, key: str = "answer_eval:jobs:queue") -> None:
        import redis  # noqa: F401 — validated by caller

        self._r = redis_client
        self._key = key

    def enqueue(self, job_id: str) -> None:
        self._r.rpush(self._key, job_id)

    def dequeue(self, timeout_s: float = 1.0) -> str | None:
        item = self._r.blpop(self._key, timeout=max(0, int(timeout_s)) or 1)
        if not item:
            return None
        value = item[1]
        return value.decode() if isinstance(value, bytes) else value

    def requeue(self, job_id: str, delay_s: float = 0.0) -> None:
        if delay_s > 0:
            self._r.zadd(f"{self._key}:delayed", {job_id: _now() + delay_s})
            return
        self.enqueue(job_id)


def _now() -> float:
    import time

    return time.time()


def create_queue(redis_url: str | None = None, key: str = "answer_eval:jobs:queue") -> JobQueue:
    """Factory: Redis when reachable, in-memory fallback otherwise (documented dev mode)."""
    if redis_url:
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(redis_url, decode_responses=False)
            client.ping()
            logger_q = __import__("answer_eval.core.logging", fromlist=["get_logger"]).get_logger("jobs.queue")
            logger_q.info("Using Redis job queue", url=redis_url, key=key)
            return RedisQueue(client, key)
        except Exception as e:
            from answer_eval.core.logging import get_logger

            get_logger("jobs.queue").warning(
                "Redis unavailable — falling back to in-memory queue (development only)", error=str(e)
            )
    return InMemoryQueue()
