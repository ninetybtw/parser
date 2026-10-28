"""Вежливый темп запросов: минимальный интервал, случайная добавка и бюджет на запуск.

Задача — не «маскироваться», а не превышать лимиты площадок и не создавать
нагрузку: интервал выбирается ниже официальных лимитов API, а бюджет
останавливает источник, если запрос получился слишком широким.
"""

from __future__ import annotations

import random
import threading
import time


class BudgetExceeded(RuntimeError):
    pass


class RateLimiter:
    def __init__(
        self,
        min_interval: float,
        jitter: float = 0.0,
        max_requests: int | None = None,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.min_interval = min_interval
        self.jitter = jitter
        self.max_requests = max_requests
        self.count = 0
        self._last: float | None = None
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def wait(self) -> None:
        with self._lock:
            if self.max_requests is not None and self.count >= self.max_requests:
                raise BudgetExceeded(f"исчерпан бюджет запросов ({self.max_requests})")
            if self._last is not None:
                interval = self.min_interval + random.uniform(0, self.jitter)
                delay = self._last + interval - self._clock()
                if delay > 0:
                    self._sleep(delay)
            self._last = self._clock()
            self.count += 1

    def pause(self, seconds: float) -> None:
        """Явная пауза по требованию площадки (Retry-After, FloodWait)."""
        self._sleep(seconds)
        with self._lock:
            self._last = self._clock()


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 120.0) -> float:
    """Экспоненциальная задержка с полным джиттером: 0..min(cap, base*2^attempt)."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))
