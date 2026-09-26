# app/routers/debug_router.py

from collections import deque
import logging
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import AppEnv, settings
from app.db.repository import BaseRepository
from app.dependencies import get_repository, get_template_path, get_templates

api_log = logging.getLogger("api_app.routers.debug_router")

router = APIRouter(
    prefix="/debug",
    tags=["Debug & Logs"],
)


def verify_development_mode() -> None:
    """Проверка работы приложения исключительно в режиме DEVELOPMENT."""
    if settings.app_env != AppEnv.DEVELOPMENT:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Страница не найдена",
        )


def read_last_lines(file_path: Path, max_lines: int = 300) -> List[str]:
    """Считывает последние N строк из файла лога."""
    if not file_path or not file_path.exists():
        return [f"Файл лога не найден по пути: {file_path}"]

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=max_lines))
    except Exception as e:
        return [f"Ошибка при чтении файла лога: {e}"]


@router.get("/work-log", response_class=HTMLResponse, dependencies=[Depends(verify_development_mode)], summary="Просмотр Work Log")
async def get_work_log(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Отображение последних 300 строк файла work_log.log."""
    api_log.info("GET /debug/work-log -> просмотр лога основной логики")

    sys_settings = await repo.get_or_create_settings(log_to_api=True)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    log_lines = read_last_lines(settings.work_log, max_lines=300)
    log_content = "".join(log_lines)

    context = {
        "website_return_time": website_return_time,
        "log_title": "Work Log (climat_app)",
        "log_file_name": settings.work_log.name if settings.work_log else "work_log.log",
        "log_content": log_content,
        "lines_count": len(log_lines),
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("work_log.html", request),
        context=context,
    )


@router.get("/api-log", response_class=HTMLResponse, dependencies=[Depends(verify_development_mode)], summary="Просмотр API Log")
async def get_api_log(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Отображение последних 300 строк файла api_log.log."""
    api_log.info("GET /debug/api-log -> просмотр лога веб-сервера")

    sys_settings = await repo.get_or_create_settings(log_to_api=True)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    log_lines = read_last_lines(settings.api_log, max_lines=300)
    log_content = "".join(log_lines)

    context = {
        "website_return_time": website_return_time,
        "log_title": "API Log (api_app)",
        "log_file_name": settings.api_log.name if settings.api_log else "api_log.log",
        "log_content": log_content,
        "lines_count": len(log_lines),
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("api_log.html", request),
        context=context,
    )