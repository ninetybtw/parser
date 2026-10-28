"""Модели данных, общие для источников, хранилища и генераторов."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LeadKind = Literal["business", "request"]
"""business — бизнес для холодного предложения; request — заказ на бирже (отклик)."""

LeadStatus = Literal["new", "ready", "sent", "replied", "skipped", "do_not_contact"]
STATUSES: tuple[str, ...] = ("new", "ready", "sent", "replied", "skipped", "do_not_contact")


class PriceItem(BaseModel):
    title: str
    price: str = ""


class Contacts(BaseModel):
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    telegram: list[str] = Field(default_factory=list)
    vk: list[str] = Field(default_factory=list)

    def merge(self, other: "Contacts") -> "Contacts":
        data = {}
        for name in type(self).model_fields:
            mine, theirs = getattr(self, name), getattr(other, name)
            data[name] = mine + [v for v in theirs if v not in mine]
        return Contacts(**data)

    def is_empty(self) -> bool:
        return not any(getattr(self, n) for n in type(self).model_fields)


class RawLead(BaseModel):
    """То, что отдаёт источник: одна запись до дедупликации."""

    source: str
    external_id: str
    url: str
    name: str
    kind: LeadKind = "business"
    description: str = ""
    city: str | None = None
    contacts: Contacts = Field(default_factory=Contacts)
    contact_url: str | None = None
    """Куда человек нажимает «написать»: диалог с сообществом, профиль, страница заказа."""
    logo_url: str | None = None
    prices: list[PriceItem] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


class Lead(RawLead):
    """Лид из базы: объединённые данные + рабочие поля карточки."""

    id: int
    niche: str = "generic"
    status: LeadStatus = "new"
    offer_subject: str = ""
    offer_text: str = ""
    offer_service: str = ""
    offer_source: str = ""
    mockup_path: str | None = None
    sources: list[dict] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
