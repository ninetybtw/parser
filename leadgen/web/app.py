"""Веб-интерфейс: список лидов, карточка с предложением, ручная отправка.

Приложение локальное и однопользовательское (слушает 127.0.0.1). Кнопка
«Скопировать и открыть» только копирует текст и открывает диалог на площадке —
само сообщение человек отправляет из своего аккаунта и отмечает это здесь.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from .. import mockup, niches, pipeline
from ..config import Settings, load_settings
from ..db import Store
from ..models import STATUSES
from ..offer import OfferGenerator
from ..sources import available_sources, build_sources

HERE = Path(__file__).parent

STATUS_LABELS = {
    "new": "новый",
    "ready": "готов к отправке",
    "sent": "отправлено",
    "replied": "ответили",
    "skipped": "пропущен",
    "do_not_contact": "не писать",
}


def safe_url(url: str | None) -> str:
    """В href попадают только http(s)-ссылки: данные пришли из внешних источников."""
    if url and urlsplit(url).scheme in ("http", "https"):
        return url
    return ""


class SameOriginPost(BaseHTTPMiddleware):
    """Простая защита от CSRF: POST принимаем только со своей же страницы."""

    async def dispatch(self, request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("cross-origin POST запрещён", status_code=403)
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()

    app = FastAPI(title="leadgen")
    app.add_middleware(SameOriginPost)
    # Наружу отдаём только макеты — не всю папку data (там база и Telegram-сессия).
    app.mount("/mockups", StaticFiles(directory=settings.mockups_dir), name="mockups")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["safe_url"] = safe_url
    templates.env.globals.update(STATUS_LABELS=STATUS_LABELS, NICHES=niches.PROFILES)

    jobs: dict[str, dict] = {}
    jobs_lock = threading.Lock()

    def store() -> Store:
        return Store(settings.db_path)

    def mockup_url(path: str | None) -> str | None:
        if not path:
            return None
        rel = Path(path).resolve().relative_to(settings.mockups_dir.resolve())
        return "/mockups/" + rel.as_posix()

    def run_job(job_id: str, niche: str, source_names: list[str], limit: int, expand: bool) -> None:
        s = store()
        try:
            sources, errors = build_sources(settings, source_names)
            stats = pipeline.run_search(s, sources, niche, limit=limit, expand=expand)
            stats.errors = errors + stats.errors
            for src in sources:
                src.close()
            with jobs_lock:
                jobs[job_id].update(state="preparing", summary=stats.summary())
            prepared = pipeline.prepare_pending(s, OfferGenerator(settings), mockup.MockupBuilder(settings),
                                                ids=stats.new_ids)
            with jobs_lock:
                jobs[job_id].update(state="done", summary=f"{stats.summary()}; подготовлено карточек: {prepared}")
        except Exception as e:
            with jobs_lock:
                jobs[job_id].update(state="error", summary=str(e))
        finally:
            s.close()

    @app.get("/")
    def index(request: Request, status: str = "", niche: str = "", q: str = ""):
        s = store()
        try:
            leads = s.list(status=status or None, niche=niche or None, text=q or None)
            counts = s.counts_by_status()
            sent_today = s.sent_today()
        finally:
            s.close()
        with jobs_lock:
            recent_jobs = sorted(jobs.values(), key=lambda j: j["started"], reverse=True)[:5]
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "leads": leads, "counts": counts, "status": status, "niche": niche, "q": q,
                "sources": available_sources(settings), "jobs": recent_jobs,
                "sent_today": sent_today, "limit": settings.daily_send_limit,
            },
        )

    @app.post("/search")
    def search(
        background: BackgroundTasks,
        niche: str = Form(...),
        sources: list[str] = Form(default=[]),
        limit: int = Form(30),
        expand: bool = Form(False),
    ):
        job_id = uuid.uuid4().hex[:8]
        with jobs_lock:
            jobs[job_id] = {
                "id": job_id, "niche": niche, "sources": sources, "state": "searching", "summary": "",
                "started": datetime.now().strftime("%H:%M:%S"),
            }
        background.add_task(run_job, job_id, niche, sources, max(1, min(limit, 200)), expand)
        return RedirectResponse("/", status_code=303)

    @app.get("/leads/{lead_id}")
    def lead_page(request: Request, lead_id: int):
        s = store()
        try:
            lead = s.get(lead_id)
            sent_today = s.sent_today()
        finally:
            s.close()
        if lead is None:
            raise HTTPException(404)
        preview = mockup.preview_png(lead.mockup_path)
        return templates.TemplateResponse(
            request,
            "lead.html",
            {
                "lead": lead, "profile": niches.get(lead.niche), "statuses": STATUSES,
                "mockup_url": mockup_url(lead.mockup_path),
                "preview_url": mockup_url(str(preview)) if preview else None,
                "sent_today": sent_today, "limit": settings.daily_send_limit,
            },
        )

    @app.post("/leads/{lead_id}/offer")
    def save_offer(lead_id: int, subject: str = Form(""), text: str = Form(...)):
        s = store()
        try:
            s.update_offer_text(lead_id, subject, text)
        finally:
            s.close()
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.post("/leads/{lead_id}/regenerate")
    def regenerate(lead_id: int):
        s = store()
        try:
            pipeline.prepare_lead(s, lead_id, OfferGenerator(settings), mockup.MockupBuilder(settings))
        finally:
            s.close()
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.post("/leads/{lead_id}/status")
    def set_status(lead_id: int, status: str = Form(...)):
        if status not in STATUSES:
            raise HTTPException(400, "неизвестный статус")
        s = store()
        try:
            s.set_status(lead_id, status)
        finally:
            s.close()
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    return app
