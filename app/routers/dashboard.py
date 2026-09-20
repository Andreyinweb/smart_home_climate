# app/routers/dashboard.py

from datetime import datetime
import logging
import os
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import app.db.repository as db

api_log = logging.getLogger("api_app.routers.dashboard")
templates = Jinja2Templates(directory="templates")


def get_template_path(template_name: str, request: Request) -> str:
    """Определяет путь к шаблону в зависимости от типа устройства."""
    user_agent = request.headers.get("user-agent", "").lower()
    legacy_keywords = [
        "smart-tv", "smarttv", "opera tv", "netcast",
        "viera", "tizen/2", "tizen/3", "web0s/1", "web0s/2"
    ]
    is_legacy_device = any(keyword in user_agent for keyword in legacy_keywords)
    web_template_file = os.path.join("templates", "web", template_name)

    if not is_legacy_device and os.path.exists(web_template_file):
        return f"web/{template_name}"

    return f"legacy/{template_name}"


def safe_diff(val1: Any, val2: Any) -> float:
    """Безопасное вычисление разницы между двумя значениями."""
    if val1 is not None and val2 is not None:
        try:
            return round(float(val1) - float(val2), 2)
        except (ValueError, TypeError):
            pass
    return 0.0


def get_time_difference_str(start_str: str, now_str: str) -> str:
    """Расчет текстовой разницы времени между двумя строками формата HH:MM."""
    try:
        t1 = datetime.strptime(start_str, "%H:%M")
        t2 = datetime.strptime(now_str, "%H:%M")
        diff = int((t2 - t1).total_seconds() // 60)
        if diff < 0:
            diff += 1440
        hours = diff // 60
        minutes = diff % 60
        return f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
    except Exception:
        return "—"


router = APIRouter(
    tags=["Dashboard & Web UI"],
)


@router.get("/", response_class=HTMLResponse, summary="Главная страница дашборда")
async def get_index(request: Request) -> Any:
    """Главная страница климат-контроля со сводкой показателей."""
    api_log.info("GET / -> открытие главной страницы дашборда")

    try:
        sys_settings = await db.get_or_create_settings(log_to_api=True)
        website_return_time = getattr(sys_settings, "website_return_time", 60)
        target_rh = getattr(sys_settings, "target_rh", 60.0)
        abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)

        latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=True)
        latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=True)

        if not latest_sensor or not latest_api:
            api_log.warning("На сервер не приходят значения из базы данных")
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

        vent_status = db_data.get("vent_status")
        vent_time_val = db_data.get("vent_time_val")

        if vent_status and vent_time_val:
            msg_vent_status = "ДА"
            vent_reason = f"Время: {vent_time_val} мин."
        elif not vent_status:
            msg_vent_status = "НЕТ"
            vent_reason = f"dАВ < {abs_tolerance}"
        else:
            msg_vent_status = "НЕТ"
            vent_reason = "Тяги нет."

        if vent_status:
            vent_class = "badge-green"
            vent_display_class = ""
        else:
            vent_class = "badge-red"
            vent_display_class = "d-none"

        heat_status = db_data.get("heat_status")
        heating_delta = db_data.get("heating_delta", 0.0)

        if heat_status:
            msg_heat_status = "ДА"
            heat_info = f"+{heating_delta} °C"
            heat_class = "badge-amber"
            heat_display_class = ""
        else:
            msg_heat_status = "НЕТ"
            heat_info = ""
            heat_class = "badge-gray"
            heat_display_class = "d-none"

        active_modes = []
        latest_vent = await db.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
        if latest_vent and latest_vent.get("status_ventilation"):
            active_modes.append("Проветривание")

        latest_heat = await db.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        if latest_heat and latest_heat.get("status_heating"):
            active_modes.append("Отопление")

        active_mode = ", ".join(active_modes) if active_modes else ""

        context = {
            "website_return_time": website_return_time,
            "max_rh": target_rh,
            "msg_vent_status": msg_vent_status,
            "vent_reason": vent_reason,
            "vent_class": vent_class,
            "vent_display_class": vent_display_class,
            "msg_heat_status": msg_heat_status,
            "heat_info": heat_info,
            "heat_class": heat_class,
            "heat_display_class": heat_display_class,
            "active_mode": active_mode,
            **db_data,
        }

        return templates.TemplateResponse(
            request=request,
            name=get_template_path("index.html", request),
            context=context,
        )

    except Exception as e:
        api_log.error(f"Ошибка при формировании главной страницы: {e}", exc_info=True)
        return_time = getattr(sys_settings, "website_return_time", 60) if 'sys_settings' in locals() and sys_settings else 60
        return templates.TemplateResponse(
            request=request,
            name=get_template_path("no_data.html", request),
            context={"website_return_time": return_time},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/ventilation", response_class=HTMLResponse, summary="Страница проветривания")
async def get_ventilation_page(request: Request) -> Any:
    """Страница ручного управления проветриванием и таблицы сравнения."""
    sys_settings = await db.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)

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

    latest_vent = await db.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)

    if latest_vent and latest_vent.get("status_ventilation"):
        vent_start_id = latest_vent.get("ventilation_start")
        sensor_before = await db.get_record_by_id("table_sensor_data", vent_start_id, log_to_api=False) if vent_start_id else None
        api_before = await db.get_record_by_id("api_table", vent_start_id, log_to_api=False) if vent_start_id else None

        if sensor_before and api_before:
            vent_before = dict(sensor_before)
            a_before = dict(api_before)
            if "timestamp" in a_before:
                del a_before["timestamp"]
            vent_before.update(a_before)
        else:
            vent_before = dict(db_data)

        vent_active = True
    else:
        vent_active = False
        vent_before = dict(db_data)

    vent_start_time = vent_before.get("timestamp", db_data.get("timestamp", "—"))
    vent_now_time = db_data.get("timestamp", "—")
    vent_difference_time = get_time_difference_str(vent_start_time[11:16], vent_now_time[11:16])

    diffs = {
        "diff_basement_temp": safe_diff(db_data.get("basement_temp"), vent_before.get("basement_temp")),
        "diff_basement_humi": safe_diff(db_data.get("basement_humi"), vent_before.get("basement_humi")),
        "diff_a_basement_humi": safe_diff(db_data.get("a_basement_humi"), vent_before.get("a_basement_humi")),
        "diff_floor_temp": safe_diff(db_data.get("floor_temp"), vent_before.get("floor_temp")),
        "diff_floor_humi": safe_diff(db_data.get("floor_humi"), vent_before.get("floor_humi")),
        "diff_a_floor_humi": safe_diff(db_data.get("a_floor_humi"), vent_before.get("a_floor_humi")),
    }

    style_classes = {
        "diff_basement_temp_class": "text-blue" if abs(diffs["diff_basement_temp"]) > 0.1 else "text-gray",
        "diff_basement_humi_class": "text-green" if diffs["diff_basement_humi"] < -0.5 else "text-red" if diffs["diff_basement_humi"] > 0.5 else "text-gray",
        "diff_a_basement_humi_class": "text-green" if diffs["diff_a_basement_humi"] < -0.1 else "text-red" if diffs["diff_a_basement_humi"] > 0.1 else "text-gray",
        "diff_floor_temp_class": "text-blue" if abs(diffs["diff_floor_temp"]) > 0.1 else "text-gray",
        "diff_floor_humi_class": "text-green" if diffs["diff_floor_humi"] < -0.5 else "text-red" if diffs["diff_floor_humi"] > 0.5 else "text-gray",
        "diff_a_floor_humi_class": "text-green" if diffs["diff_a_floor_humi"] < -0.1 else "text-red" if diffs["diff_a_floor_humi"] > 0.1 else "text-gray",
    }

    if vent_active:
        btn_start_class, btn_stop_class = "btn-disabled", "btn-stop"
        btn_start_disabled, btn_stop_disabled = "disabled", ""
    else:
        btn_start_class, btn_stop_class = "btn-start", "btn-disabled"
        btn_start_disabled, btn_stop_disabled = "", "disabled"

    before_data = {f"before_{k}": v for k, v in vent_before.items()}
    vent_start_str = vent_start_time[11:16] if len(str(vent_start_time)) >= 16 else str(vent_start_time)
    vent_now_str = vent_now_time[11:16] if len(str(vent_now_time)) >= 16 else str(vent_now_time)

    context = {
        "website_return_time": website_return_time,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "vent_start_time": vent_start_str,
        "vent_now_time": vent_now_str,
        "vent_difference_time": vent_difference_time,
        **db_data,
        **before_data,
        **diffs,
        **style_classes,
    }

    return templates.TemplateResponse(
        request=request, name=get_template_path("ventilation.html", request), context=context
    )


@router.post("/api/ventilation/start")
async def start_ventilation():
    """Запуск проветривания."""
    latest_vent = await db.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
    can_start = True
    if latest_vent and latest_vent.get("status_ventilation"):
        can_start = False

    if can_start:
        latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)
        if latest_api:
            data_to_write = {
                "timestamp": latest_api["timestamp"],
                "status_ventilation": True,
                "ventilation_start": latest_api["id"],
                "stop_ventilation": 0,
            }
            await db.upsert_record("ventilation_table", data_to_write, log_to_api=False)
            api_log.info(f" Успешный старт проветривания: api_id={latest_api['id']}")

    return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/ventilation/stop")
async def stop_ventilation():
    """Остановка проветривания."""
    latest_vent = await db.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
    if latest_vent and latest_vent.get("status_ventilation"):
        latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)
        if latest_api:
            data_to_write = {
                "id": latest_vent["id"],
                "timestamp": latest_vent["timestamp"],
                "status_ventilation": False,
                "ventilation_start": latest_vent.get("ventilation_start"),
                "stop_ventilation": latest_api["id"],
            }
            await db.upsert_record("ventilation_table", data_to_write, pk_col="id", log_to_api=False)
            api_log.info(f" Успешный стоп проветривания: api_id={latest_api['id']}")

    return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/heating", response_class=HTMLResponse, summary="Страница отопления")
async def get_heating_page(request: Request) -> Any:
    """Страница ручного управления отоплением и сравнительного анализа."""
    sys_settings = await db.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)

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

    latest_heat = await db.get_latest_record("heating_table", order_by_col="id", log_to_api=False)

    if latest_heat and latest_heat.get("stop_heating") == 0:
        heat_start_id = latest_heat.get("heating_start")
        sensor_before = await db.get_record_by_id("table_sensor_data", heat_start_id, log_to_api=False) if heat_start_id else None
        api_before = await db.get_record_by_id("api_table", heat_start_id, log_to_api=False) if heat_start_id else None

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
    heat_difference_time = get_time_difference_str(heat_start_time[11:16], heat_now_time[11:16])

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
    heat_start_str = heat_start_time[11:16] if len(str(heat_start_time)) >= 16 else str(heat_start_time)
    heat_now_str = heat_now_time[11:16] if len(str(heat_now_time)) >= 16 else str(heat_now_time)

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
async def start_heating():
    """Запуск отопления."""
    latest_heat = await db.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    can_start = True
    if latest_heat and latest_heat.get("status_heating"):
        can_start = False

    if can_start:
        latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)
        if latest_api:
            data_to_write = {
                "timestamp": latest_api["timestamp"],
                "status_heating": True,
                "heating_start": latest_api["id"],
                "stop_heating": 0,
            }
            await db.upsert_record("heating_table", data_to_write, log_to_api=False)
            api_log.info(f" Успешный старт отопления: api_id={latest_api['id']}")

    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/heating/stop")
async def stop_heating():
    """Остановка отопления."""
    latest_heat = await db.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    if latest_heat and latest_heat.get("status_heating"):
        latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)
        if latest_api:
            data_to_write = {
                "id": latest_heat["id"],
                "timestamp": latest_heat["timestamp"],
                "status_heating": False,
                "heating_start": latest_heat.get("heating_start"),
                "stop_heating": latest_api["id"],
            }
            await db.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
            api_log.info(f" Успешный стоп отопления: api_id={latest_api['id']}")

    return RedirectResponse(url="/heating", status_code=status.HTTP_303_SEE_OTHER)

