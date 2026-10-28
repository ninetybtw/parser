"""SQLite-хранилище лидов с дедупликацией по «идентичностям».

Один бизнес часто находится несколько раз: в разных источниках, по разным
фразам, с разными ссылками. Поэтому лид склеивается не по URL, а по набору
идентификаторов: id в источнике, телефон, e-mail, домен сайта, @username,
ссылка ВК. Совпал хотя бы один — это тот же лид, данные дополняются.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .extract import host_of, is_shared_host, normalize_url
from .models import Contacts, Lead, PriceItem, RawLead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    niche TEXT NOT NULL DEFAULT 'generic',
    city TEXT,
    url TEXT NOT NULL,
    contact_url TEXT,
    logo_url TEXT,
    contacts TEXT NOT NULL DEFAULT '{}',
    prices TEXT NOT NULL DEFAULT '[]',
    extra TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new',
    offer_subject TEXT NOT NULL DEFAULT '',
    offer_text TEXT NOT NULL DEFAULT '',
    offer_service TEXT NOT NULL DEFAULT '',
    offer_source TEXT NOT NULL DEFAULT '',
    mockup_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS leads_niche ON leads(niche);

CREATE TABLE IF NOT EXISTS lead_sources (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    url TEXT NOT NULL,
    query TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS identities (
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    PRIMARY KEY (kind, value)
);

CREATE TABLE IF NOT EXISTS blocklist (
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (kind, value)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    type TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_type_at ON events(type, at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identities_of(raw: RawLead) -> set[tuple[str, str]]:
    ids = {("src", f"{raw.source}:{raw.external_id}")}
    c = raw.contacts
    ids |= {("phone", p) for p in c.phones}
    ids |= {("email", e.lower()) for e in c.emails}
    ids |= {("tg", t.lower().lstrip("@")) for t in c.telegram}
    ids |= {("vk", v.lower()) for v in c.vk}
    for site in c.websites:
        # Ссылка на taplink/instagram — это страница, а не домен бизнеса.
        if is_shared_host(site):
            ids.add(("url", normalize_url(site).lower()))
        else:
            ids.add(("domain", host_of(site)))
    return ids


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            # Веб-интерфейс читает, пока фоновый поиск пишет.
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- запись ---

    def is_blocked(self, raw: RawLead) -> bool:
        ids = list(identities_of(raw))
        if not ids:
            return False
        q = " OR ".join("(kind = ? AND value = ?)" for _ in ids)
        params = [x for pair in ids for x in pair]
        return self.conn.execute(f"SELECT 1 FROM blocklist WHERE {q} LIMIT 1", params).fetchone() is not None

    def find_existing(self, raw: RawLead) -> int | None:
        ids = list(identities_of(raw))
        q = " OR ".join("(kind = ? AND value = ?)" for _ in ids)
        params = [x for pair in ids for x in pair]
        row = self.conn.execute(f"SELECT MIN(lead_id) AS id FROM identities WHERE {q}", params).fetchone()
        return row["id"] if row and row["id"] is not None else None

    def upsert(self, raw: RawLead, niche: str, query: str | None = None) -> tuple[int, bool]:
        """Возвращает (id лида, создан ли новый)."""
        ts = now()
        with self.conn:
            lead_id = self.find_existing(raw)
            created = lead_id is None
            if created:
                cur = self.conn.execute(
                    """INSERT INTO leads (kind, name, description, niche, city, url, contact_url, logo_url,
                                          contacts, prices, extra, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        raw.kind, raw.name, raw.description, niche, raw.city, raw.url, raw.contact_url,
                        raw.logo_url, raw.contacts.model_dump_json(),
                        json.dumps([p.model_dump() for p in raw.prices], ensure_ascii=False),
                        json.dumps(raw.extra, ensure_ascii=False), ts, ts,
                    ),
                )
                lead_id = cur.lastrowid
            else:
                self._merge(lead_id, raw, ts)

            self.conn.execute(
                """INSERT INTO lead_sources (source, external_id, lead_id, url, query, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source, external_id) DO UPDATE SET last_seen = excluded.last_seen""",
                (raw.source, raw.external_id, lead_id, raw.url, query, ts, ts),
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO identities (kind, value, lead_id) VALUES (?, ?, ?)",
                [(k, v, lead_id) for k, v in identities_of(raw)],
            )
        return lead_id, created

    def _merge(self, lead_id: int, raw: RawLead, ts: str) -> None:
        row = self.conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        contacts = Contacts.model_validate_json(row["contacts"]).merge(raw.contacts)
        prices = json.loads(row["prices"]) or [p.model_dump() for p in raw.prices]
        extra = {**raw.extra, **json.loads(row["extra"])}
        self.conn.execute(
            """UPDATE leads SET
                 description = CASE WHEN length(description) >= ? THEN description ELSE ? END,
                 city = COALESCE(city, ?), contact_url = COALESCE(contact_url, ?),
                 logo_url = COALESCE(logo_url, ?), contacts = ?, prices = ?, extra = ?, updated_at = ?
               WHERE id = ?""",
            (
                len(raw.description), raw.description, raw.city, raw.contact_url, raw.logo_url,
                contacts.model_dump_json(), json.dumps(prices, ensure_ascii=False),
                json.dumps(extra, ensure_ascii=False), ts, lead_id,
            ),
        )

    def set_offer(self, lead_id: int, subject: str, text: str, service: str, source: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE leads SET offer_subject = ?, offer_text = ?, offer_service = ?, offer_source = ?,
                       status = CASE WHEN status = 'new' THEN 'ready' ELSE status END, updated_at = ?
                   WHERE id = ?""",
                (subject, text, service, source, now(), lead_id),
            )

    def update_offer_text(self, lead_id: int, subject: str, text: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE leads SET offer_subject = ?, offer_text = ?, offer_source = 'edited', updated_at = ? WHERE id = ?",
                (subject, text, now(), lead_id),
            )

    def set_mockup(self, lead_id: int, path: str | None) -> None:
        with self.conn:
            self.conn.execute("UPDATE leads SET mockup_path = ?, updated_at = ? WHERE id = ?", (path, now(), lead_id))

    def set_status(self, lead_id: int, status: str, note: str = "") -> None:
        ts = now()
        with self.conn:
            self.conn.execute("UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, ts, lead_id))
            self.conn.execute(
                "INSERT INTO events (lead_id, type, note, at) VALUES (?, ?, ?, ?)", (lead_id, status, note, ts)
            )
            if status == "do_not_contact":
                self.conn.execute(
                    """INSERT OR IGNORE INTO blocklist (kind, value, added_at)
                       SELECT kind, value, ? FROM identities WHERE lead_id = ? AND kind != 'src'""",
                    (ts, lead_id),
                )
                self.conn.execute(
                    """INSERT OR IGNORE INTO blocklist (kind, value, added_at)
                       SELECT 'src', source || ':' || external_id, ? FROM lead_sources WHERE lead_id = ?""",
                    (ts, lead_id),
                )

    # --- чтение ---

    def get(self, lead_id: int) -> Lead | None:
        row = self.conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return self._to_lead(row) if row else None

    def list(
        self, status: str | None = None, niche: str | None = None, text: str | None = None, limit: int = 200
    ) -> list[Lead]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if niche:
            where.append("niche = ?")
            params.append(niche)
        if text:
            where.append("(name LIKE ? OR description LIKE ?)")
            params += [f"%{text}%", f"%{text}%"]
        sql = "SELECT * FROM leads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [self._to_lead(r, with_sources=False) for r in self.conn.execute(sql, params)]

    def ids_without_offer(self) -> list[int]:
        return [r["id"] for r in self.conn.execute("SELECT id FROM leads WHERE status = 'new' AND offer_text = ''")]

    def counts_by_status(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}

    def sent_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute("SELECT COUNT(*) AS n FROM events WHERE type = 'sent' AND at >= ?", (today,)).fetchone()
        return row["n"]

    def _to_lead(self, row: sqlite3.Row, with_sources: bool = True) -> Lead:
        sources = []
        first_source, first_ext = "", ""
        if with_sources:
            sources = [
                dict(r) for r in self.conn.execute(
                    "SELECT source, external_id, url, query, first_seen, last_seen FROM lead_sources WHERE lead_id = ? ORDER BY first_seen",
                    (row["id"],),
                )
            ]
            if sources:
                first_source, first_ext = sources[0]["source"], sources[0]["external_id"]
        return Lead(
            id=row["id"], source=first_source, external_id=first_ext, kind=row["kind"], name=row["name"],
            description=row["description"], niche=row["niche"], city=row["city"], url=row["url"],
            contact_url=row["contact_url"], logo_url=row["logo_url"],
            contacts=Contacts.model_validate_json(row["contacts"]),
            prices=[PriceItem(**p) for p in json.loads(row["prices"])], extra=json.loads(row["extra"]),
            status=row["status"], offer_subject=row["offer_subject"], offer_text=row["offer_text"],
            offer_service=row["offer_service"], offer_source=row["offer_source"], mockup_path=row["mockup_path"],
            sources=sources, created_at=row["created_at"], updated_at=row["updated_at"],
        )
