"""Shared resilience mechanism — CircuitBreaker.

Extracted from providers/resilient_llm_runtime.py and providers/reranker_client.py.

Each provider (LLM, Embedding, Reranker) keeps its own strategy:
  - retry conditions (which errors are retriable)
  - retry count and backoff strategy
  - circuit-breaker threshold and recovery time
  - degradation logic

Only the *mechanism* is shared. The generic retry policy and semaphore
wrappers that used to live here had no consumer: every provider implements
its own backoff and uses ``threading.BoundedSemaphore`` directly.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Two modes:
      - *raising* (default): before_call() raises on open circuit.
      - *passive*: before_call(*raise_on_open=False*) returns False on open.
    """

    def __init__(
        self,
        threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_running = False

    def before_call(self, *, raise_on_open: bool = True) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.recovery_seconds or self._probe_running:
                if raise_on_open:
                    raise CircuitOpenError("circuit is open")
                return False
            self._probe_running = True
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_running = False

    def failure(self) -> None:
        with self._lock:
            self._probe_running = False
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = self._clock()


class CircuitOpenError(RuntimeError):
    """Raised when a CircuitBreaker is in the open state."""
