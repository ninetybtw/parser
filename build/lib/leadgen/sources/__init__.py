"""Реестр источников: собирает подключённые источники из настроек."""

from __future__ import annotations

from ..config import Settings
from .base import Source, SourceError
from .rss import RSSSource
from .telegram import TelegramSource
from .vk import VKSource

__all__ = ["Source", "SourceError", "build_sources", "available_sources"]


def available_sources(settings: Settings) -> list[str]:
    names = []
    if settings.vk_token:
        names.append("vk")
    if settings.tg_api_id and settings.tg_api_hash:
        names.append("telegram")
    names += [f"rss:{name}" for name in settings.rss_feeds]
    return names


def build_sources(settings: Settings, names: list[str]) -> tuple[list[Source], list[str]]:
    """Возвращает (источники, ошибки подключения). Ошибка одного не мешает остальным."""
    sources: list[Source] = []
    errors: list[str] = []
    for name in names:
        try:
            if name == "vk":
                sources.append(VKSource(settings.vk_token, settings.vk_api_version, settings.vk_city_id,
                                        settings.vk_fetch_market))
            elif name == "telegram":
                sources.append(TelegramSource(settings.tg_api_id, settings.tg_api_hash, settings.tg_session,
                                              settings.logos_dir))
            elif name.startswith("rss:") and name[4:] in settings.rss_feeds:
                sources.append(RSSSource(name[4:], settings.rss_feeds[name[4:]]))
            else:
                errors.append(f"{name}: источник не настроен")
        except SourceError as e:
            errors.append(f"{name}: {e}")
    return sources, errors
