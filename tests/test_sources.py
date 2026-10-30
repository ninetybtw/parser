import json
from pathlib import Path

import httpx2 as httpx
import pytest

from leadgen.ratelimit import RateLimiter
from leadgen.sources.base import SourceError
from leadgen.sources.rss import RSSSource, parse_feed
from leadgen.sources.vk import VKSource

FIXTURES = Path(__file__).parent / "fixtures"


def no_wait():
    return RateLimiter(min_interval=0, sleep=lambda s: None)


def test_parse_feed_strips_html():
    items = parse_feed((FIXTURES / "habr.rss").read_text(encoding="utf-8"))
    assert len(items) == 2
    assert "<p>" not in items[0]["description"]
    assert "owner@remont.ru" in items[0]["description"]


def test_rss_source_yields_requests():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text=(FIXTURES / "habr.rss").read_text(encoding="utf-8"))

    src = RSSSource("test", "https://feed.example/rss?q={query}", limiter=no_wait(),
                    client=httpx.Client(transport=httpx.MockTransport(handler)))
    leads = list(src.search("ремонт телефонов", 10))
    assert "q=%D1%80" in seen["url"]
    assert [l.kind for l in leads] == ["request", "request"]
    assert leads[0].contacts.emails == ["owner@remont.ru"]
    assert leads[0].contact_url == "https://freelance.example/tasks/101"


def vk_handler(calls):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "groups.search":
            body = {"response": {"count": 2, "items": [{"id": 11}, {"id": 12}]}}
        elif method == "groups.getById":
            body = {"response": {"groups": [
                {"id": 11, "name": "Сервис Фикс", "screen_name": "fix_service", "is_closed": 0,
                 "description": "Ремонт ноутбуков. Звоните +7 912 000-11-22", "can_message": 1,
                 "city": {"title": "Казань"}, "photo_200": "https://img.example/11.png",
                 "contacts": [{"user_id": 42, "email": "Boss@Fix.ru"}], "market": {"enabled": 1}},
                {"id": 12, "name": "Закрытая", "is_closed": 1},
            ]}}
        elif method == "market.get":
            body = {"response": {"items": [{"title": "Чистка ноутбука", "price": {"text": "1 200 ₽"}}]}}
        else:
            body = {"error": {"error_code": 100, "error_msg": "unknown"}}
        return httpx.Response(200, json=body)
    return handler


def test_vk_search_maps_public_groups():
    calls = []
    src = VKSource("token", limiter=no_wait(), client=httpx.Client(transport=httpx.MockTransport(vk_handler(calls))))
    leads = list(src.search("ремонт", 10))
    assert len(leads) == 1  # закрытая группа пропущена
    lead = leads[0]
    assert lead.contact_url == "https://vk.com/im?sel=-11"
    assert lead.city == "Казань"
    assert lead.contacts.phones == ["79120001122"]
    assert lead.contacts.emails == ["boss@fix.ru"]
    assert "id42" in lead.contacts.vk and "fix_service" in lead.contacts.vk
    assert lead.prices[0].title == "Чистка ноутбука"
    assert calls == ["groups.search", "groups.getById", "market.get"]


def test_vk_retries_rate_limit_then_fails_on_bad_token():
    responses = iter([
        {"error": {"error_code": 6, "error_msg": "Too many requests per second"}},
        {"error": {"error_code": 5, "error_msg": "User authorization failed"}},
    ])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(responses))))
    src = VKSource("token", limiter=no_wait(), client=client)
    with pytest.raises(SourceError, match="токен"):
        src.call("groups.search", q="x")


def test_vk_requires_token():
    with pytest.raises(SourceError):
        VKSource("")


def test_feed_without_query_is_filtered_by_niche():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=(FIXTURES / "habr.rss").read_text(encoding="utf-8"))))
    src = RSSSource("all", "https://feed.example/all.xml", limiter=no_wait(), client=client)
    assert [l.external_id for l in src.search("ремонт техники", 10)] == ["https://freelance.example/tasks/101"]
    assert [l.name for l in src.search("бот", 10)] == ["Telegram-бот для записи в салон"]
    assert len(list(src.search("сайт для салона", 10))) == 2  # «сайт» в первом, «салон» во втором
    assert list(src.search("доставка цветов", 10)) == []


def test_feed_with_wrong_charset_header_is_decoded_by_xml_declaration():
    body = (FIXTURES / "habr.rss").read_bytes()  # UTF-8 с encoding="UTF-8" в декларации
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=body, headers={"content-type": "text/xml; charset=windows-1251"})))
    src = RSSSource("fl", "https://feed.example/all.xml", limiter=no_wait(), client=client)
    assert [l.name for l in src.search("салон", 10)] == ["Telegram-бот для записи в салон"]


def test_double_encoded_text_is_repaired():
    from leadgen.sources.rss import fix_mojibake

    assert fix_mojibake("Р—Р°РєР°Р·С‹ РЅР° FL.ru") == "Заказы на FL.ru"
    assert fix_mojibake("Заказы на FL.ru") == "Заказы на FL.ru"
    assert fix_mojibake("Ремонт техники, Россия") == "Ремонт техники, Россия"
