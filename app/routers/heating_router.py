# app/routers/heating_router.py

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.repository import BaseRepository
from app.dependencies import (
    get_heating_controller,
    get_repository,
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


@router.get("/heating", response_class=HTMLResponse, summary="Страница отопления")
async def get_heating_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Страница ручного управления отоплением и сравнительного анализа."""
    sys_settings = await repo.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    minimum_temperature = getattr(sys_settings, "minimum_temperature", None)
    target_temperature = getattr(sys_settings, "target_temperature", None)
    maximum_temperature = getattr(sys_settings, "maximum_temperature", None)

    latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=False)

    if not latest_sensor or not latest_api:
        return templates.TemplateResponse(
            request=request,
            name=get_template_path("no_data.html", request),
            context={"website_return_time": website_return_time},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    current_db_data = dict(latest_sensor)
    current_api_data = dict(latest_api)
    if "timestamp" in current_api_data:
        del current_api_data["timestamp"]
    current_db_data.update(current_api_data)

    latest_heat = None
    try:
        latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    except Exception:
        pass

    latest_heat_exists = latest_heat is not None

    if latest_heat and latest_heat.get("status_heating"):
        heat_active = True
        heat_start_id = latest_heat.get("id")
        sensor_before = await repo.get_record_by_id("table_sensor_data", heat_start_id, log_to_api=False) if heat_start_id else None
        api_before = await repo.get_record_by_id("api_table", heat_start_id, log_to_api=False) if heat_start_id else None

        if sensor_before and api_before:
            heat_before = dict(sensor_before)
            a_before = dict(api_before)
            if "timestamp" in a_before:
                del a_before["timestamp"]
            heat_before.update(a_before)
        else:
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

        sensor_before = await repo.get_record_by_id("table_sensor_data", heat_start_id, log_to_api=False) if heat_start_id else None
        api_before = await repo.get_record_by_id("api_table", heat_start_id, log_to_api=False) if heat_start_id else None

        if sensor_before and api_before:
            heat_before = dict(sensor_before)
            a_before = dict(api_before)
            if "timestamp" in a_before:
                del a_before["timestamp"]
            heat_before.update(a_before)
        else:
            heat_before = dict(current_db_data)

        sensor_after = await repo.get_record_by_id("table_sensor_data", heat_stop_id, log_to_api=False) if heat_stop_id else None
        api_after = await repo.get_record_by_id("api_table", heat_stop_id, log_to_api=False) if heat_stop_id else None

        if sensor_after and api_after:
            db_data = dict(sensor_after)
            a_after = dict(api_after)
            if "timestamp" in a_after:
                del a_after["timestamp"]
            db_data.update(a_after)
        else:
            db_data = dict(current_db_data)

        heat_start_time = heat_before.get("timestamp", latest_heat.get("timestamp", "—"))
        heat_now_time = db_data.get("timestamp", "—")
        card_title = f"История {heat_start_time}, последнего отопления"

    else:
        heat_active = False
        heat_before = {}
        db_data = dict(current_db_data)
        heat_start_time = "—"
        heat_now_time = "—"
        card_title = "Отопление не включалось"

    start_basement_temp = heat_before.get("basement_temp") if heat_before else db_data.get("basement_temp")
    target_heat_limit = target_temperature
    
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
        "target_temperature": target_temperature,
        "maximum_temperature": maximum_temperature,
        "target_heat_limit": target_heat_limit,
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
    """Остановка отопления через HeatingController."""
    await heating_ctrl.stop(is_automation=False)
    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)
