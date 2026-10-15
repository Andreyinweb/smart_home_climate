# app/routers/heating_router.py

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.db_settings import get_settings_db
from app.db import crud as db
from app.dependencies import (
    get_heating_controller,
    get_template_path,
    get_templates,
)
from app.routers.dashboard_router import (
    get_time_difference_str,
    safe_diff,
)
from app.services.heating_service import HeatingController

api_log = logging.getLogger("api_app.routers.heating")

router = APIRouter(
    tags=["Heating"],
)


def get_diff_class(val: Optional[float], threshold: float, pos_green: bool = True) -> str:
    """Определяет CSS-класс стиля для отображения дельты."""
    if val is None:
        return "text-gray"
    if pos_green:
        if val > threshold:
            return "text-green"
        if val < -threshold:
            return "text-red"
    else:
        if val < -threshold:
            return "text-green"
        if val > threshold:
            return "text-red"
    return "text-gray"


def _merge_sensor_api(sensor: Any, api: Any) -> dict:
    """Объединяет запись датчиков и запись api_table (timestamp берётся из датчиков)."""
    data = dict(sensor)
    api_data = dict(api)
    api_data.pop("timestamp", None)
    data.update(api_data)
    return data


async def _load_merged_by_id(record_id: Optional[int]) -> Optional[dict]:
    """Собирает sensor + api по id. Если любой из записей нет — возвращает None."""
    if record_id is None:
        return None
    sensor_rows = await db.get("table_sensor_data", pk=record_id, pk_col="id", log_to_api=False)
    api_rows = await db.get("api_table", pk=record_id, pk_col="id", log_to_api=False)
    sensor = sensor_rows[0] if sensor_rows else None
    api = api_rows[0] if api_rows else None
    if not sensor or not api:
        return None
    return _merge_sensor_api(sensor, api)


@router.get("/heating", response_class=HTMLResponse, summary="Страница отопления")
async def get_heating_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Страница ручного управления отоплением и сравнительного анализа."""
    sys_settings = await get_settings_db()
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    latest_heating_table_rows = await db.get("heating_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
    latest_heating_table = latest_heating_table_rows[0] if latest_heating_table_rows else {}
    minimum_temperature = latest_heating_table.get("temperature_start")
    maximum_temperature = latest_heating_table.get("temperature_stop")

    latest_sensor_rows = await db.get("table_sensor_data", order_col="id", order_asc=False, limit=1, log_to_api=False)
    latest_api_rows = await db.get("api_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
    latest_sensor = latest_sensor_rows[0] if latest_sensor_rows else None
    latest_api = latest_api_rows[0] if latest_api_rows else None

    if not latest_sensor or not latest_api:
        return templates.TemplateResponse(
            request=request,
            name=get_template_path("no_data.html", request),
            context={"website_return_time": website_return_time},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    current_db_data = _merge_sensor_api(latest_sensor, latest_api)

    latest_heat = None
    try:
        latest_heat_rows = await db.get("history_of_heating", order_col="id", order_asc=False, limit=1, log_to_api=False)
        latest_heat = latest_heat_rows[0] if latest_heat_rows else None
    except Exception:
        pass

    latest_heat_exists = latest_heat is not None
    heat_before: Optional[dict] = None
    db_data: dict = {}

    if latest_heat and latest_heating_table.get("status_heating"):
        heat_active = True
        heat_start_id = latest_heat.get("id")
        heat_before = await _load_merged_by_id(heat_start_id)
        if not heat_before:
            heat_before = dict(current_db_data)

        db_data = dict(current_db_data)
        heat_start_time = heat_before.get("timestamp", db_data.get("timestamp", "—"))
        heat_now_time = db_data.get("timestamp", "—")
        card_title = "📊 Сравнение показателей отопления"

    elif latest_heat:
        heat_active = False
        heat_start_id = latest_heat.get("id")
        stop_heat_plus = latest_heat.get("stop_heat_plus", 0)
        heat_stop_id = (heat_start_id + stop_heat_plus) if heat_start_id is not None else None

        heat_before = await _load_merged_by_id(heat_start_id)
        if not heat_before:
            heat_before = dict(current_db_data)

        db_data = await _load_merged_by_id(heat_stop_id)
        if not db_data:
            db_data = dict(current_db_data)

        heat_start_time = heat_before.get("timestamp", latest_heat.get("timestamp", "—"))
        heat_now_time = db_data.get("timestamp", "—")
        card_title = f"История {heat_start_time}, отопления"

    else:
        heat_active = False
        heat_before = {}
        db_data = dict(current_db_data)
        heat_start_time = "—"
        heat_now_time = "—"
        card_title = "Отопление не включалось"

    if heat_start_time != "—" and heat_now_time != "—":
        heat_difference_time = get_time_difference_str(str(heat_start_time)[11:16], str(heat_now_time)[11:16])
    else:
        heat_difference_time = "—"

    diffs = {
        "diff_basement_temp": safe_diff(db_data.get("basement_temp"), heat_before.get("basement_temp")),
        "diff_basement_humi": safe_diff(db_data.get("basement_humi"), heat_before.get("basement_humi")),
        "diff_a_basement_humi": safe_diff(db_data.get("a_basement_humi"), heat_before.get("a_basement_humi")),
        "diff_floor_temp": safe_diff(db_data.get("floor_temp"), heat_before.get("floor_temp")),
        "diff_floor_humi": safe_diff(db_data.get("floor_humi"), heat_before.get("floor_humi")),
        "diff_a_floor_humi": safe_diff(db_data.get("a_floor_humi"), heat_before.get("a_floor_humi")),
    }

    style_classes = {
        "diff_basement_temp_class": get_diff_class(diffs["diff_basement_temp"], 0.1, pos_green=True),
        "diff_basement_humi_class": get_diff_class(diffs["diff_basement_humi"], 0.5, pos_green=False),
        "diff_a_basement_humi_class": get_diff_class(diffs["diff_a_basement_humi"], 0.1, pos_green=False),
        "diff_floor_temp_class": get_diff_class(diffs["diff_floor_temp"], 0.1, pos_green=True),
        "diff_floor_humi_class": get_diff_class(diffs["diff_floor_humi"], 0.5, pos_green=False),
        "diff_a_floor_humi_class": get_diff_class(diffs["diff_a_floor_humi"], 0.1, pos_green=False),
    }

    if heat_active:
        btn_start_class, btn_stop_class = "btn-disabled", "btn-stop"
        btn_start_disabled, btn_stop_disabled = "disabled", ""
    else:
        btn_start_class, btn_stop_class = "btn-start", "btn-disabled"
        btn_start_disabled, btn_stop_disabled = "", "disabled"

    before_data = {f"before_{k}": v for k, v in heat_before.items()}
    heat_start_str = str(heat_start_time)[11:16] if len(str(heat_start_time)) >= 16 else str(heat_start_time)
    heat_now_str = str(heat_now_time)[11:16] if len(str(heat_now_time)) >= 16 else str(heat_now_time)

    context = {
        "website_return_time": website_return_time,
        "minimum_temperature": minimum_temperature,
        "maximum_temperature": maximum_temperature,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "heat_active": heat_active,
        "latest_heat_exists": latest_heat_exists,
        "card_title": card_title,
        "is_history_title": (not heat_active and latest_heat_exists),
        "heat_start_time": heat_start_str,
        "heat_now_time": heat_now_str,
        "heat_difference_time": heat_difference_time,
        **db_data,
        **before_data,
        **diffs,
        **style_classes,
    }

    return templates.TemplateResponse(
        request=request, name=get_template_path("heating.html", request), context=context
    )


@router.post("/api/heating/start")
async def start_heating(
    heating_ctrl: HeatingController = Depends(get_heating_controller),
):
    """Запуск отопления через HeatingController."""
    await heating_ctrl.start(is_automation=False)
    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/heating/stop")
async def stop_heating(
    heating_ctrl: HeatingController = Depends(get_heating_controller),
):
    """Принудительная остановка отопления через HeatingController."""
    await heating_ctrl.stop(is_automation=False, stop_forcibly=1)
    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)