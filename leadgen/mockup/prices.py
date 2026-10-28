"""Прайс из свободного текста: строки вида «Замена экрана — от 1 500 ₽»."""

from __future__ import annotations

import re

from ..models import PriceItem

PRICE_LINE_RE = re.compile(
    r"^\s*[-•*–—\d.)]*\s*(?P<title>[^\n:—–\-]{3,80}?)\s*[:—–\-]+\s*"
    r"(?P<price>(?:от\s*)?\d[\d\s]*(?:[.,]\d+)?\s*(?:₽|руб\.?|р\.?|rub)(?:\s*/\s*[\wа-я.]+)?)",
    re.I | re.M,
)


def parse_prices(text: str, limit: int = 12) -> list[PriceItem]:
    items: list[PriceItem] = []
    for m in PRICE_LINE_RE.finditer(text or ""):
        title = m.group("title").strip(" .,")
        price = re.sub(r"\s+", " ", m.group("price")).strip()
        if title and not any(i.title == title for i in items):
            items.append(PriceItem(title=title[:1].upper() + title[1:], price=price))
        if len(items) >= limit:
            break
    return items
