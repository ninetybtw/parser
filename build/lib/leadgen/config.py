"""Настройки из переменных окружения и (необязательно) файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Минимальный разбор .env: KEY=VALUE, без перезаписи уже заданных переменных."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_feeds(raw: str) -> dict[str, str]:
    feeds: dict[str, str] = {}
    for chunk in raw.split(";"):
        if "=" in chunk:
            name, url = chunk.split("=", 1)
            if name.strip() and url.strip():
                feeds[name.strip()] = url.strip()
    return feeds


@dataclass
class Settings:
    data_dir: Path = Path("./data")

    vk_token: str = ""
    vk_api_version: str = "5.199"
    vk_city_id: int | None = None
    vk_fetch_market: bool = True

    tg_api_id: int | None = None
    tg_api_hash: str = ""
    tg_session: str = "./data/telegram"

    rss_feeds: dict[str, str] = field(default_factory=dict)

    anthropic_api_key: str = ""
    model: str = "claude-opus-5-5"
    effort: str = "medium"

    me_name: str = ""
    me_services: str = "сайты и Telegram-боты"
    me_portfolio: str = ""
    me_contact: str = ""

    daily_send_limit: int = 20

    @property
    def db_path(self) -> Path:
        return self.data_dir / "leads.sqlite3"

    @property
    def mockups_dir(self) -> Path:
        return self.data_dir / "mockups"

    @property
    def logos_dir(self) -> Path:
        return self.data_dir / "logos"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.mockups_dir, self.logos_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: str | Path = ".env") -> Settings:
    _load_dotenv(Path(env_file))
    env = os.environ
    city = env.get("VK_CITY_ID", "").strip()
    tg_id = env.get("TG_API_ID", "").strip()
    return Settings(
        data_dir=Path(env.get("LEADGEN_DATA_DIR", "./data")),
        vk_token=env.get("VK_TOKEN", ""),
        vk_api_version=env.get("VK_API_VERSION", "5.199"),
        vk_city_id=int(city) if city else None,
        vk_fetch_market=env.get("VK_FETCH_MARKET", "1") == "1",
        tg_api_id=int(tg_id) if tg_id else None,
        tg_api_hash=env.get("TG_API_HASH", ""),
        tg_session=env.get("TG_SESSION", "./data/telegram"),
        rss_feeds=_parse_feeds(env.get("LEADGEN_RSS_FEEDS", "")),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
        model=env.get("LEADGEN_MODEL", "claude-opus-5-5"),
        effort=env.get("LEADGEN_EFFORT", "medium"),
        me_name=env.get("ME_NAME", ""),
        me_services=env.get("ME_SERVICES", "сайты и Telegram-боты"),
        me_portfolio=env.get("ME_PORTFOLIO", ""),
        me_contact=env.get("ME_CONTACT", ""),
        daily_send_limit=int(env.get("LEADGEN_DAILY_SEND_LIMIT", "20")),
    )
