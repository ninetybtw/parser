"""Биржи фриланса через RSS-ленты поиска.

RSS — официальный машиночитаемый канал, который биржи сами публикуют, поэтому
это самый безопасный способ: никакого логина и скрейпинга страниц. Заказ с
биржи — это kind="request": отвечать на него нужно откликом на самой бирже.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from urllib.parse import quote_plus

from ..extract import extract_contacts
from ..http import make_client, polite_get
from ..models import RawLead
from ..ratelimit import RateLimiter
from .base import Source

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>", "\n", text or "", flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(TAG_RE.sub("", text))).strip()


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        def field(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None else ""

        items.append(
            {
                "title": strip_html(field("title")),
                "link": field("link"),
                "guid": field("guid") or field("link"),
                "description": strip_html(field("description")),
                "published": field("pubDate"),
                "category": field("category"),
            }
        )
    return items


class RSSSource(Source):
    def __init__(self, name: str, url_template: str, limiter: RateLimiter | None = None, client=None):
        self.name = f"rss:{name}"
        self.url_template = url_template
        self.limiter = limiter or RateLimiter(min_interval=5.0, jitter=3.0, max_requests=30)
        self.client = client or make_client()

    def search(self, query: str, limit: int) -> Iterator[RawLead]:
        url = self.url_template.format(query=quote_plus(query))
        items = parse_feed(polite_get(self.client, url, self.limiter).text)
        for item in items[:limit]:
            yield RawLead(
                source=self.name,
                external_id=item["guid"],
                url=item["link"],
                name=item["title"],
                kind="request",
                description=item["description"],
                contacts=extract_contacts(item["description"]),
                contact_url=item["link"],
                extra={"published": item["published"], "category": item["category"]},
            )

    def close(self) -> None:
        self.client.close()
