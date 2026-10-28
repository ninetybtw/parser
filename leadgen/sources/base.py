"""Контракт источника: одна фраза поиска → поток RawLead.

Источник отвечает только за доступ к площадке и приведение её формата к
RawLead. Дедупликация, классификация ниши и генерация — дальше по конвейеру.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..models import RawLead


class SourceError(RuntimeError):
    """Источник не может продолжать (нет доступа, неверный токен, бан по лимиту)."""


class Source(ABC):
    name: str = "source"

    @abstractmethod
    def search(self, query: str, limit: int) -> Iterator[RawLead]:
        ...

    def close(self) -> None:
        pass
