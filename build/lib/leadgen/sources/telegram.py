"""Telegram: публичные каналы бизнесов через MTProto (Telethon), только чтение.

Используется личный аккаунт, поэтому темп консервативный: поиск
contacts.Search + по одному GetFullChannel на канал с паузой 2–4 с.
FloodWait от Telegram выполняется буквально (ждём ровно сколько сказано),
а слишком долгий FloodWait останавливает источник до следующего запуска.

Групповые чаты (megagroup) сознательно пропускаются: участники чата — не
бизнесы, и выгрузка участников для рассылки — это ровно тот спам, от
которого инструмент защищает. Чаты — для ручного чтения.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

from ..extract import extract_contacts
from ..models import Contacts, RawLead
from ..ratelimit import RateLimiter
from .base import Source, SourceError

MAX_FLOOD_WAIT = 300


class TelegramSource(Source):
    name = "telegram"

    def __init__(self, api_id: int | None, api_hash: str, session: str, logos_dir: Path,
                 limiter: RateLimiter | None = None):
        if not api_id or not api_hash:
            raise SourceError("TG_API_ID / TG_API_HASH не заданы")
        try:
            import telethon  # noqa: F401
        except ImportError as e:
            raise SourceError("установите telethon: pip install 'leadgen[telegram]'") from e
        self.api_id, self.api_hash, self.session = api_id, api_hash, session
        self.logos_dir = logos_dir
        self.limiter = limiter or RateLimiter(min_interval=2.0, jitter=2.0, max_requests=60)

    def search(self, query: str, limit: int) -> Iterator[RawLead]:
        yield from asyncio.run(self._search(query, limit))

    async def _search(self, query: str, limit: int) -> list[RawLead]:
        from telethon import TelegramClient, errors, functions
        from telethon.tl.types import Channel

        leads: list[RawLead] = []
        async with TelegramClient(self.session, self.api_id, self.api_hash) as client:
            if not await client.is_user_authorized():
                raise SourceError("Telegram-сессия не авторизована: выполните `leadgen tg-login`")
            self.limiter.wait()
            found = await client(functions.contacts.SearchRequest(q=query, limit=min(limit, 100)))
            for chat in found.chats:
                if not isinstance(chat, Channel) or not chat.broadcast or not chat.username:
                    continue
                try:
                    self.limiter.wait()
                    full = await client(functions.channels.GetFullChannelRequest(chat))
                except errors.FloodWaitError as e:
                    if e.seconds > MAX_FLOOD_WAIT:
                        break
                    self.limiter.pause(e.seconds)
                    continue
                about = full.full_chat.about or ""
                logo = await self._logo(client, chat)
                username = chat.username.lower()
                leads.append(
                    RawLead(
                        source=self.name,
                        external_id=str(chat.id),
                        url=f"https://t.me/{username}",
                        name=chat.title,
                        kind="business",
                        description=about,
                        contacts=extract_contacts(about).merge(Contacts(telegram=[username])),
                        # Писать в канал нельзя — ссылка ведёт на канал, контакт для связи
                        # человек берёт из описания (он подсвечен в карточке).
                        contact_url=f"https://t.me/{username}",
                        logo_url=logo,
                        extra={"subscribers": full.full_chat.participants_count},
                    )
                )
        return leads

    async def _logo(self, client, chat) -> str | None:
        if not chat.photo:
            return None
        self.logos_dir.mkdir(parents=True, exist_ok=True)
        path = await client.download_profile_photo(chat, file=str(self.logos_dir / f"tg_{chat.id}.jpg"))
        return Path(path).resolve().as_uri() if path else None


async def login(api_id: int, api_hash: str, session: str) -> None:
    """Интерактивный вход один раз: код из Telegram вводится в терминале."""
    from telethon import TelegramClient

    async with TelegramClient(session, api_id, api_hash) as client:
        await client.start()
        me = await client.get_me()
        print(f"Сессия сохранена: {me.first_name} (@{me.username})")
