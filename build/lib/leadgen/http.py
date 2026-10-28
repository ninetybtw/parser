"""Общий HTTP-клиент: честный User-Agent, таймауты, повтор на 429/5xx с Retry-After."""

from __future__ import annotations

import httpx2 as httpx

from .ratelimit import RateLimiter, backoff_delay

USER_AGENT = "leadgen/0.1 (personal lead research tool; manual outreach)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def make_client(**kwargs) -> httpx.Client:
    kwargs.setdefault("timeout", httpx.Timeout(20.0, connect=10.0))
    kwargs.setdefault("follow_redirects", True)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.Client(headers=headers, **kwargs)


def polite_get(
    client: httpx.Client, url: str, limiter: RateLimiter, *, params=None, attempts: int = 4
) -> httpx.Response:
    for attempt in range(attempts):
        limiter.wait()
        try:
            resp = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            limiter.pause(backoff_delay(attempt))
            continue
        if resp.status_code in RETRY_STATUSES and attempt < attempts - 1:
            limiter.pause(_retry_after(resp) or backoff_delay(attempt))
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("unreachable")


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After", "")
    try:
        return min(float(value), 300.0)
    except ValueError:
        return None
