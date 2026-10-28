"""Извлечение и нормализация контактов из свободного текста."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import Contacts

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zа-я]{2,}", re.I)
PHONE_RE = re.compile(r"(?<![\d\w])(?:\+7|8|7)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')]+|\b[\w-]+(?:\.[\w-]+)*\.(?:ru|рф|com|net|org|su|pro|shop|site|online)(?:/[^\s<>\"')]*)?", re.I)
TG_LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][\w]{3,31})", re.I)
TG_HANDLE_RE = re.compile(r"(?<![\w@/.])@([A-Za-z][\w]{3,31})\b")
VK_LINK_RE = re.compile(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([\w.]+)", re.I)

# Хосты, которые принадлежат платформам, а не бизнесу: по домену их не склеиваем.
SHARED_HOSTS = {
    "vk.com", "vk.ru", "m.vk.com", "t.me", "telegram.me", "instagram.com", "wa.me",
    "ok.ru", "youtube.com", "youtu.be", "taplink.cc", "taplink.ws", "avito.ru",
    "yandex.ru", "maps.yandex.ru", "2gis.ru", "google.com", "goo.gl", "clck.ru",
    "freelance.habr.com", "fl.ru", "kwork.ru", "dzen.ru", "linktr.ee",
}


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "7" + digits
    return None


def normalize_url(raw: str) -> str:
    url = raw.strip().rstrip(".,;:!?")
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"


def host_of(url: str) -> str:
    host = urlsplit(normalize_url(url)).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_shared_host(url: str) -> bool:
    return host_of(url) in SHARED_HOSTS


def extract_contacts(text: str) -> Contacts:
    if not text:
        return Contacts()
    emails = _unique(m.lower() for m in EMAIL_RE.findall(text))
    rest = EMAIL_RE.sub(" ", text)

    phones = _unique(p for p in (normalize_phone(m) for m in PHONE_RE.findall(rest)) if p)
    telegram = _unique(m.lower() for m in TG_LINK_RE.findall(rest) + TG_HANDLE_RE.findall(rest))
    vk = _unique(m.lower() for m in VK_LINK_RE.findall(rest))

    websites = []
    for m in URL_RE.findall(rest):
        if TG_LINK_RE.match(m) or VK_LINK_RE.match(m):
            continue
        url = normalize_url(m)
        if url not in websites:
            websites.append(url)
    return Contacts(phones=phones, emails=emails, websites=websites, telegram=telegram, vk=vk)


def _unique(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen
