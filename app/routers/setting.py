# app/routers/setting.py

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.repository import BaseRepository
from app.dependencies import get_repository, get_template_path, get_templates

api_log = logging.getLogger("api_app.routers.settings")

router = APIRouter(
    tags=["Settings"],
)


@router.get("/settings", response_class=HTMLResponse, summary="Страница настроек")
async def get_settings_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """HTML-страница просмотра и редактирования настроек системы."""
    api_log.info("GET /settings -> открытие страницы настроек")

    sys_settings = await repo.get_or_create_settings(log_to_api=False)
    latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)

    average_temp = "—"
    if latest_sensor and latest_sensor.get("average_temp") is not None:
        average_temp = latest_sensor["average_temp"]

    settings_dict = sys_settings.model_dump() if hasattr(sys_settings, "model_dump") else dict(sys_settings)

    context = {
        "website_return_time": getattr(sys_settings, "website_return_time", 60),
        "average_temp": average_temp,
        **settings_dict,
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("settings.html", request),
        context=context,
    )


@router.post("/api/settings/update")
async def update_settings(
    request: Request,
    repo: BaseRepository = Depends(get_repository),
):
    """Обработка формы обновления настроек с последующим редиректом на /settings."""
    form_data = await request.form()

    def parse_field(key: str, default: Any, type_func: type) -> Any:
        val = form_data.get(key)
        if val is not None and str(val).strip():
            try:
                return type_func(val)
            except ValueError:
                pass
        return default

    current_settings = await repo.get_or_create_settings(log_to_api=False)
    latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)

    last_sensor_timestamp = latest_sensor.get("timestamp", "—") if latest_sensor else "—"

    settings_to_write = {
        "id": 1,
        "timestamp": last_sensor_timestamp,
        "mode": parse_field("mode", getattr(current_settings, "mode", "BASEMENT_STREET_FLOOR"), str),
        "interval_seconds": parse_field("interval_seconds", getattr(current_settings, "interval_seconds", 60), int),
        "max_retries": parse_field("max_retries", getattr(current_settings, "max_retries", 3), int),
        "website_return_time": parse_field("website_return_time", getattr(current_settings, "website_return_time", 60), int),
        "t_floor_mac_diff": parse_field("t_floor_mac_diff", getattr(current_settings, "t_floor_mac_diff", 0.0), float),
        "absolute_humidity_tolerance": parse_field("absolute_humidity_tolerance", getattr(current_settings, "absolute_humidity_tolerance", 0.5), float),
        "minimum_humidity": parse_field("minimum_humidity", getattr(current_settings, "minimum_humidity", 30.0), float),
        "target_rh": parse_field("target_rh", getattr(current_settings, "target_rh", 60.0), float),
        "dangerous_humidity": parse_field("dangerous_humidity", getattr(current_settings, "dangerous_humidity", 80.0), float),
        "price_gas": parse_field("price_gas", getattr(current_settings, "price_gas", 0.0), float),
        "hot_water_per_hour": parse_field("hot_water_per_hour", getattr(current_settings, "hot_water_per_hour", 0.0), float),
    }

    success = await repo.upsert_record("settings_table", settings_to_write, pk_col="id", log_to_api=False)
    if success:
        api_log.info(f"Настройки успешно обновлены в settings_table: {settings_to_write}")
    else:
        api_log.error("Ошибка при записи новых настроек в settings_table")

    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)