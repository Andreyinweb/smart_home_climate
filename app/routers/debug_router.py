# app/routers/debug_router.py

from collections import deque
import logging
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import AppEnv, settings
from app.core.db_settings import get_settings_db
from app.dependencies import get_template_path, get_templates

api_log = logging.getLogger("api_app.routers.debug_router")

router = APIRouter(
    prefix="/debug",
    tags=["Debug & Logs"],
)


def verify_development_mode() -> None:
    """Проверка работы приложения исключительно в режиме DEVELOPMENT."""
    if settings.app_env == AppEnv.PRODUCTION:
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


async def render_log_page(
    request: Request,
    templates: Jinja2Templates,
    *,
    log_path: Optional[Path],
    log_title: str,
    default_name: str,
    log_url: str,
) -> Any:
    """Общий рендер страницы лога: последние 100 строк файла в одном шаблоне logs.html."""
    sys_settings = await get_settings_db()
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    log_lines = read_last_lines(log_path, max_lines=100)

    context = {
        "website_return_time": website_return_time,
        "log_title": log_title,
        "log_file_name": log_path.name if log_path else default_name,
        "log_content": "".join(log_lines),
        "lines_count": len(log_lines),
        "log_url": log_url,
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("logs.html", request),
        context=context,
    )


@router.get(
    "/work-log",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_development_mode)],
    summary="Просмотр Work Log",
)
async def get_work_log(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Отображение последних 100 строк файла work_log.log."""
    api_log.info("GET /debug/work-log -> просмотр лога основной логики")
    return await render_log_page(
        request,
        templates,
        log_path=settings.work_log,
        log_title="Work Log (climat_app)",
        default_name="work_log.log",
        log_url="/debug/work-log",
    )


@router.get(
    "/api-log",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_development_mode)],
    summary="Просмотр API Log",
)
async def get_api_log(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Отображение последних 100 строк файла api_log.log."""
    api_log.info("GET /debug/api-log -> просмотр лога веб-сервера")
    return await render_log_page(
        request,
        templates,
        log_path=settings.api_log,
        log_title="API Log (api_app)",
        default_name="api_log.log",
        log_url="/debug/api-log",
    )