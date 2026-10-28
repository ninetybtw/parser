"""Макет-превью сайта из логотипа и прайса.

Подход — шаблон + подстановка данных: предсказуемо, быстро, бесплатно и без
«галлюцинаций» в вёрстке. Персонализация идёт через палитру из логотипа,
секции и тексты профиля ниши и реальный прайс. Результат — один HTML-файл
(логотип рядом) и, если установлен Playwright, PNG-скриншот для вложения.
"""

from __future__ import annotations

import io
import logging
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from ..config import Settings
from ..http import make_client, polite_get
from ..models import Lead, PriceItem
from ..niches import NicheProfile
from ..ratelimit import RateLimiter
from .palette import palette_from_logo
from .prices import parse_prices

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"
MAX_LOGO_BYTES = 5 * 1024 * 1024


def should_build(lead: Lead, service: str) -> bool:
    return lead.kind == "business" and "site" in service and bool(lead.logo_url or lead.prices or parse_prices(lead.description))


class MockupBuilder:
    def __init__(self, settings: Settings, client=None, screenshots: bool = True):
        self.settings = settings
        self.client = client
        self.limiter = RateLimiter(min_interval=1.0, jitter=1.0)
        self.screenshots = screenshots
        self.env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))

    def build(self, lead: Lead, profile: NicheProfile) -> Path:
        out = self.settings.mockups_dir / str(lead.id)
        out.mkdir(parents=True, exist_ok=True)
        logo = self._fetch_logo(lead.logo_url, out / "logo.png")
        prices = lead.prices or parse_prices(lead.description)
        html = self.env.get_template("landing.html.j2").render(
            lead=lead,
            profile=profile,
            palette=palette_from_logo(logo).as_dict(),
            logo="logo.png" if logo else None,
            prices=prices[:9],
            services=[PriceItem(title=f) for f in profile.site_features] if not prices else [],
            phone=_format_phone(lead.contacts.phones[0]) if lead.contacts.phones else None,
            email=lead.contacts.emails[0] if lead.contacts.emails else None,
        )
        index = out / "index.html"
        index.write_text(html, encoding="utf-8")
        if self.screenshots:
            self._screenshot(index, out / "preview.png")
        return index

    def _fetch_logo(self, url: str | None, dest: Path) -> Path | None:
        """Скачиваем и перекодируем в PNG: в макет попадает только проверенная картинка."""
        if not url:
            return None
        try:
            if url.startswith("file://"):
                data = Path(unquote(urlsplit(url).path)).read_bytes()
            else:
                if self.client is None:
                    self.client = make_client()
                data = polite_get(self.client, url, self.limiter).content
            if len(data) > MAX_LOGO_BYTES:
                return None
            with Image.open(io.BytesIO(data)) as img:
                img.convert("RGBA").save(dest, "PNG")
            return dest
        except Exception as e:
            log.info("логотип %s не загружен: %s", url, e)
            return None

    @staticmethod
    def _screenshot(index: Path, dest: Path) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(index.resolve().as_uri())
                page.screenshot(path=str(dest), full_page=True)
                browser.close()
        except Exception as e:
            log.info("скриншот макета не снят: %s", e)


def preview_png(index_path: str | None) -> Path | None:
    if not index_path:
        return None
    png = Path(index_path).with_name("preview.png")
    return png if png.exists() else None


def remove(index_path: str | None) -> None:
    if index_path:
        shutil.rmtree(Path(index_path).parent, ignore_errors=True)


def _format_phone(p: str) -> str:
    return f"+7 ({p[1:4]}) {p[4:7]}-{p[7:9]}-{p[9:11]}" if len(p) == 11 else p
