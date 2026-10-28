"""ВКонтакте через официальный API (groups.search → groups.getById → market.get).

Лимит API для пользовательского токена — 3 запроса в секунду; держим ~1 запрос
в 0.6–1.0 с и бюджет на запуск. Закрытые и заблокированные сообщества пропускаем:
в них нет публичных данных.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..extract import extract_contacts, normalize_phone
from ..http import make_client, polite_get
from ..models import Contacts, PriceItem, RawLead
from ..ratelimit import RateLimiter
from .base import Source, SourceError

API = "https://api.vk.com/method/"
GROUP_FIELDS = "description,contacts,site,city,members_count,market,can_message,activity,status,addresses,links"
# 6 — слишком много запросов в секунду, 9 — flood control, 10 — внутренняя ошибка
RETRY_CODES = {6, 9, 10}
# 29 — достигнут суточный лимит метода: продолжать бессмысленно
FATAL_CODES = {5: "неверный или просроченный токен", 29: "достигнут лимит метода, попробуйте завтра"}


class VKSource(Source):
    name = "vk"

    def __init__(
        self,
        token: str,
        version: str = "5.199",
        city_id: int | None = None,
        fetch_market: bool = True,
        limiter: RateLimiter | None = None,
        client=None,
    ):
        if not token:
            raise SourceError("VK_TOKEN не задан")
        self.token = token
        self.version = version
        self.city_id = city_id
        self.fetch_market = fetch_market
        self.limiter = limiter or RateLimiter(min_interval=0.6, jitter=0.4, max_requests=300)
        self.client = client or make_client()

    def call(self, method: str, **params) -> dict | list:
        params = {k: v for k, v in params.items() if v is not None}
        params.update(access_token=self.token, v=self.version)
        for attempt in range(4):
            data = polite_get(self.client, API + method, self.limiter, params=params).json()
            if "error" not in data:
                return data["response"]
            code = data["error"].get("error_code")
            if code in FATAL_CODES:
                raise SourceError(f"VK {method}: {FATAL_CODES[code]}")
            if code in RETRY_CODES and attempt < 3:
                self.limiter.pause(2.0 * (attempt + 1))
                continue
            raise SourceError(f"VK {method}: {data['error'].get('error_msg')} (код {code})")
        raise SourceError(f"VK {method}: не удалось выполнить запрос")

    def search(self, query: str, limit: int) -> Iterator[RawLead]:
        found = self.call("groups.search", q=query, count=min(limit, 1000), city_id=self.city_id)
        ids = [str(g["id"]) for g in found.get("items", [])]
        for start in range(0, len(ids), 100):
            batch = self.call("groups.getById", group_ids=",".join(ids[start:start + 100]), fields=GROUP_FIELDS)
            groups = batch["groups"] if isinstance(batch, dict) else batch
            for group in groups:
                if group.get("is_closed") or group.get("deactivated"):
                    continue
                yield self.to_lead(group)

    def to_lead(self, g: dict) -> RawLead:
        gid = g["id"]
        screen = g.get("screen_name") or f"club{gid}"
        url = f"https://vk.com/{screen}"
        text = "\n".join(filter(None, [g.get("description", ""), g.get("status", ""), g.get("site", "")]))
        contacts = extract_contacts(text).merge(self._listed_contacts(g))
        contacts = contacts.merge(Contacts(vk=[screen.lower()]))

        prices: list[PriceItem] = []
        if self.fetch_market and g.get("market", {}).get("enabled"):
            prices = self._market(gid)

        return RawLead(
            source=self.name,
            external_id=str(gid),
            url=url,
            name=g.get("name", screen),
            kind="business",
            description=g.get("description", ""),
            city=(g.get("city") or {}).get("title"),
            contacts=contacts,
            contact_url=f"https://vk.com/im?sel=-{gid}" if g.get("can_message") else url,
            logo_url=g.get("photo_200") or g.get("photo_100"),
            prices=prices,
            extra={"members": g.get("members_count"), "activity": g.get("activity")},
        )

    @staticmethod
    def _listed_contacts(g: dict) -> Contacts:
        """Контакты, которые сообщество само указало в блоке «Контакты»."""
        phones, emails, vk = [], [], []
        for c in g.get("contacts", []) or []:
            if c.get("phone") and (p := normalize_phone(c["phone"])):
                phones.append(p)
            if c.get("email"):
                emails.append(c["email"].lower())
            if c.get("user_id"):
                vk.append(f"id{c['user_id']}")
        return Contacts(phones=phones, emails=emails, vk=vk)

    def _market(self, gid: int) -> list[PriceItem]:
        try:
            resp = self.call("market.get", owner_id=-gid, count=30)
        except SourceError:
            return []
        items = []
        for item in resp.get("items", []):
            price = (item.get("price") or {}).get("text", "")
            items.append(PriceItem(title=item.get("title", ""), price=price))
        return items

    def close(self) -> None:
        self.client.close()
