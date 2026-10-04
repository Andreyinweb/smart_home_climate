# app/routers/programmer_router.py

from datetime import datetime
import logging
from typing import Any

from app.dependencies import get_programmer
from app.services.heating_service import Programmer
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.repository import BaseRepository
from app.dependencies import (
    get_repository,
    get_template_path,
    get_templates,
)

api_log = logging.getLogger("api_app.routers.programmer")

router = APIRouter(
    tags=["Programmer"],
)


@router.get("/programmer", response_class=HTMLResponse, summary="Страница программатора")
async def get_programmer_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Точка входа для отображения страницы настройки программатора."""
    sys_settings = await repo.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)
    programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

    latest_sensor = None
    try:
        latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из table_sensor_data: {e}")

    current_dow = "—"
    current_time = "—"
    basement_temp = None

    if latest_sensor and latest_sensor.get("timestamp"):
        ts_str = str(latest_sensor["timestamp"])
        try:
            dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
            current_dow = days[dt.weekday()]
            current_time = dt.strftime("%H:%M")
        except Exception:
            if len(ts_str) >= 16:
                current_time = ts_str[11:16]
        
        basement_temp = latest_sensor.get("basement_temp")

    latest_const = None
    try:
        latest_const = await repo.get_latest_record("programmer_const", order_by_col="id", log_to_api=False)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из programmer_const: {e}")

    const_min = latest_const.get("const_min", 18.0) if latest_const and latest_const.get("const_min") is not None else 18.0
    const_max = latest_const.get("const_max", 24.0) if latest_const and latest_const.get("const_max") is not None else 24.0

    flag_const = (programmer_mode == "PROGRAMMER_CONST")

    context = {
        "website_return_time": website_return_time,
        "current_dow": current_dow,
        "current_time": current_time,
        "basement_temp": basement_temp,
        "const_min": const_min,
        "const_max": const_max,
        "flag_const": flag_const,
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("programmer.html", request),
        context=context,
    )

@router.post("/api/programmer/update")
async def update_programmer_const(
    const_min: float = Form(...),
    const_max: float = Form(...),
    flag_const: Optional[str] = Form(None),
    programmer: Programmer = Depends(get_programmer),
):
    if const_min >= const_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Минимальная температура должна быть строго меньше максимальной.",
        )

    await programmer.save_programmer_const(const_min, const_max)
    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)