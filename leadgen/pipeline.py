"""Конвейер: поиск → дедупликация → классификация ниши → макет → предложение.

Поиск и подготовка разделены: поиск дешёвый и наполняет базу, подготовка
(LLM, загрузка логотипа, скриншот) делается только для новых лидов.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import mockup, niches
from .db import Store
from .models import Lead
from .offer import OfferGenerator, choose_service
from .ratelimit import BudgetExceeded
from .sources import Source, SourceError

log = logging.getLogger(__name__)


@dataclass
class SearchStats:
    found: int = 0
    new: int = 0
    merged: int = 0
    blocked: int = 0
    errors: list[str] = field(default_factory=list)
    new_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        s = f"найдено {self.found}, новых {self.new}, уже было {self.merged}, в стоп-листе {self.blocked}"
        if self.errors:
            s += "; ошибки: " + "; ".join(self.errors)
        return s


def run_search(store: Store, sources: list[Source], niche_query: str, limit: int = 50,
               expand: bool = False) -> SearchStats:
    hint = niches.resolve(niche_query)
    queries = [niche_query]
    if expand:
        queries += [q for q in hint.search_queries if q.lower() != niche_query.lower()]

    stats = SearchStats()
    for source in sources:
        for query in queries:
            try:
                for raw in source.search(query, limit):
                    stats.found += 1
                    if store.is_blocked(raw):
                        stats.blocked += 1
                        continue
                    profile = niches.classify(f"{raw.name}\n{raw.description}", hint=hint)
                    lead_id, created = store.upsert(raw, profile.key, query=query)
                    if created:
                        stats.new += 1
                        stats.new_ids.append(lead_id)
                    else:
                        stats.merged += 1
            except (SourceError, BudgetExceeded) as e:
                stats.errors.append(f"{source.name}: {e}")
                break  # у источника кончился доступ/бюджет — остальные фразы не пробуем
            except Exception as e:  # сеть, неожиданный формат — не роняем весь поиск
                log.exception("источник %s упал на фразе %r", source.name, query)
                stats.errors.append(f"{source.name} / {query}: {e}")
    return stats


def prepare_lead(store: Store, lead_id: int, generator: OfferGenerator,
                 builder: mockup.MockupBuilder | None) -> Lead | None:
    lead = store.get(lead_id)
    if lead is None:
        return None
    profile = niches.get(lead.niche)

    has_mockup = False
    if builder is not None and mockup.should_build(lead, choose_service(lead, profile)):
        try:
            path = builder.build(lead, profile)
            store.set_mockup(lead_id, str(path))
            has_mockup = True
        except Exception:
            log.exception("макет для лида %s не собран", lead_id)

    draft, source = generator.generate(lead, profile, has_mockup=has_mockup)
    if has_mockup and "site" not in draft.service:
        # Модель решила, что тут уместнее бот — макет сайта к такому тексту не прикладываем.
        mockup.remove(store.get(lead_id).mockup_path)
        store.set_mockup(lead_id, None)
    store.set_offer(lead_id, draft.subject, draft.message, draft.service, source)
    return store.get(lead_id)


def prepare_pending(store: Store, generator: OfferGenerator, builder: mockup.MockupBuilder | None,
                    ids: list[int] | None = None) -> int:
    done = 0
    for lead_id in ids if ids is not None else store.ids_without_offer():
        if prepare_lead(store, lead_id, generator, builder):
            done += 1
    return done
