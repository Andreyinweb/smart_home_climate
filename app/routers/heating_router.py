# app/routers/heating_router.py

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.repository import BaseRepository
from app.dependencies import get_repository, get_template_path, get_templates
from app.routers.dashboard_router import (
    get_time_difference_str,
    safe_diff,
)

api_log = logging.getLogger("api_app.routers.heating")

router = APIRouter(
    tags=["Heating"],
)


@router.get("/heating", response_class=HTMLResponse, summary="Страница отопления")
async def get_heating_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Страница ручного управления отоплением и сравнительного анализа."""
    sys_settings = await repo.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=False)

    if not latest_sensor or not latest_api:
        return templates.TemplateResponse(
            request=request,
            name=get_template_path("no_data.html", request),
            context={"website_return_time": website_return_time},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    db_data = dict(latest_sensor)
    api_data = dict(latest_api)
    if "timestamp" in api_data:
        del api_data["timestamp"]
    db_data.update(api_data)

    latest_heat = None
    try:
        latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    except Exception:
        pass

    if latest_heat and latest_heat.get("status_heating"):
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
            heat_before = dict(db_data)

        heat_active = True
    else:
        heat_active = False
        heat_before = dict(db_data)

    heat_start_time = heat_before.get("timestamp", db_data.get("timestamp", "—"))
    heat_now_time = db_data.get("timestamp", "—")
    heat_difference_time = get_time_difference_str(str(heat_start_time)[11:16], str(heat_now_time)[11:16])

    diffs = {
        "diff_basement_temp": safe_diff(db_data.get("basement_temp"), heat_before.get("basement_temp")),
        "diff_basement_humi": safe_diff(db_data.get("basement_humi"), heat_before.get("basement_humi")),
        "diff_floor_temp": safe_diff(db_data.get("floor_temp"), heat_before.get("floor_temp")),
        "diff_floor_humi": safe_diff(db_data.get("floor_humi"), heat_before.get("floor_humi")),
    }

    style_classes = {
        "diff_basement_temp_class": "text-green" if diffs["diff_basement_temp"] > 0.1 else "text-red" if diffs["diff_basement_temp"] < -0.1 else "text-gray",
        "diff_basement_humi_class": "text-green" if diffs["diff_basement_humi"] < -0.5 else "text-red" if diffs["diff_basement_humi"] > 0.5 else "text-gray",
        "diff_floor_temp_class": "text-green" if diffs["diff_floor_temp"] > 0.1 else "text-red" if diffs["diff_floor_temp"] < -0.1 else "text-gray",
        "diff_floor_humi_class": "text-green" if diffs["diff_floor_humi"] < -0.5 else "text-red" if diffs["diff_floor_humi"] > 0.5 else "text-gray",
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
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
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
async def start_heating(repo: BaseRepository = Depends(get_repository)):
    """Запуск отопления."""
    latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    can_start = True
    if latest_heat and latest_heat.get("status_heating"):
        can_start = False

    if can_start:
        latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
        if latest_sensor:
            data_to_write = {
                "id": latest_sensor["id"],
                "timestamp": latest_sensor["timestamp"],
                "status_heating": True,
                "stop_heat__plus": 0,
                "heating_automation": False,
            }
            await repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
            api_log.info(f"Успешный старт отопления: sensor_id={latest_sensor['id']}")

    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/heating/stop")
async def stop_heating(repo: BaseRepository = Depends(get_repository)):
    """Остановка отопления."""
    latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    if latest_heat and latest_heat.get("status_heating"):
        latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
        if latest_sensor:
            stop_heat_plus = latest_sensor["id"] - latest_heat["id"]
            data_to_write = {
                "id": latest_heat["id"],
                "timestamp": latest_heat["timestamp"],
                "status_heating": False,
                "stop_heat__plus": stop_heat_plus,
                "heating_automation": latest_heat.get("heating_automation", False),
            }
            await repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
            api_log.info(f"Успешный стоп отопления: start_id={latest_heat['id']}, stop_id={latest_sensor['id']}, diff={stop_heat_plus}")

    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)