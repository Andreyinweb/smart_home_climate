# app/error_handlers.py

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_templates, get_template_path

log = logging.getLogger("climat_app.errors")

ERROR_TEXTS = {
    400: "Некорректный запрос",
    403: "Доступ запрещён",
    404: "Страница не найдена",
    405: "Метод не разрешён",
    422: "Неверные параметры запроса",
    500: "Внутренняя ошибка сервера",
}


def _render(request: Request, status_code: int, message: str | None = None):
    title = ERROR_TEXTS.get(status_code, "Ошибка")
    context = {
        "status_code": status_code,
        "title": title,
        "message": message,
    }
    try:
        return get_templates().TemplateResponse(
            request,
            get_template_path("error.html", request),
            context,
            status_code=status_code,
        )
    except Exception:
        # Если сам шаблон/base.html сломан, отдаём минимальный HTML
        log.exception("Не удалось отрисовать error.html")
        return HTMLResponse(
            f"<h1>{status_code}</h1><p>{title}</p><a href='/'>На главную</a>",
            status_code=status_code,
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        # detail показываем только если это не стандартный текст Starlette
        return _render(request, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request: Request, exc: RequestValidationError):
        log.warning(f"422 {request.method} {request.url.path}: {exc.errors()}")
        return _render(request, 422)

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request: Request, exc: Exception):
        log.error(f"500 {request.method} {request.url.path}: {exc}", exc_info=True)
        return _render(request, 500)
    