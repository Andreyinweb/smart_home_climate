# app/routers/dashboard_router.py

from datetime import datetime
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.db_settings import get_settings_db, update_settings
from app.db import crud as db
from app.dependencies import get_template_path, get_templates
from app.schemas.settings_schema import SystemSettingsUpdate

api_log = logging.getLogger("api_app.routers.dashboard_router")


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


def _hhmm(ts: Any) -> str:
    """Возвращает HH:MM из строки 'YYYY-MM-DD HH:MM:SS', иначе исходную строку."""
    s = str(ts)
    return s[11:16] if len(s) >= 16 else s


def _diff_or_none(after: Optional[dict], before: Optional[dict], key: str) -> Optional[float]:
    """Разница after - before или None, если данных для сравнения нет."""
    if not after or not before:
        return None
    a, b = after.get(key), before.get(key)
    if a is None or b is None:
        return None
    return safe_diff(a, b)


def _vent_class(val: Optional[float], kind: str) -> str:
    """CSS-класс дельты: temp — синий при изменении; rh/ah — зелёный при снижении влажности."""
    if val is None:
        return "text-gray"
    if kind == "temp":
        return "text-blue" if abs(val) > 0.1 else "text-gray"
    threshold = 0.5 if kind == "rh" else 0.1
    if val < -threshold:
        return "text-green"
    if val > threshold:
        return "text-red"
    return "text-gray"


# (поле, тип для раскраски)
_VENT_DIFF_FIELDS = (
    ("basement_temp", "temp"),
    ("basement_humi", "rh"),
    ("a_basement_humi", "ah"),
    ("floor_temp", "temp"),
    ("floor_humi", "rh"),
    ("a_floor_humi", "ah"),
)


router = APIRouter(
    tags=["Dashboard & Web UI"],
)


@router.get("/", response_class=HTMLResponse, summary="Главная страница дашборда")
async def get_index(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Главная страница климат-контроля со сводкой показателей."""
    api_log.info("GET / -> открытие главной страницы дашборда")
    sys_settings = None

    try:
        sys_settings = await get_settings_db()
        website_return_time = getattr(sys_settings, "website_return_time", 60)
        target_rh = getattr(sys_settings, "target_rh", 60.0)
        abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)
        app_env = settings.app_env.value

        latest_sensor_rows = await db.get("table_sensor_data", order_col="id", order_asc=False, limit=1, log_to_api=True)
        latest_api_rows = await db.get("api_table", order_col="id", order_asc=False, limit=1, log_to_api=True)
        latest_sensor = latest_sensor_rows[0] if latest_sensor_rows else None
        latest_api = latest_api_rows[0] if latest_api_rows else None

        if not latest_sensor or not latest_api:
            api_log.warning("На сервер не приходят значения из базы данных")
            return templates.TemplateResponse(
                request=request,
                name=get_template_path("no_data.html", request),
                context={"website_return_time": website_return_time},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        db_data = _merge_sensor_api(latest_sensor, latest_api)

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
        try:
            latest_vent_rows = await db.get("ventilation_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
            latest_vent = latest_vent_rows[0] if latest_vent_rows else None
            if latest_vent and latest_vent.get("status_ventilation"):
                active_modes.append("Проветривание")
        except Exception:
            pass

        try:
            latest_heat_rows = await db.get("heating_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
            latest_heat = latest_heat_rows[0] if latest_heat_rows else None
            if latest_heat and latest_heat.get("status_heating"):
                active_modes.append("Отопление")
        except Exception:
            pass

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
            "app_env": app_env,
            **db_data,
        }

        return templates.TemplateResponse(
            request=request,
            name=get_template_path("index.html", request),
            context=context,
        )

    except Exception as e:
        api_log.error(f"Ошибка при формировании главной страницы: {e}", exc_info=True)
        return_time = getattr(sys_settings, "website_return_time", 60) if sys_settings else 60
        return templates.TemplateResponse(
            request=request,
            name=get_template_path("no_data.html", request),
            context={"website_return_time": return_time},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/ventilation", response_class=HTMLResponse, summary="Страница проветривания")
async def get_ventilation_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Страница ручного управления проветриванием: текущий цикл или история последнего."""
    sys_settings = await get_settings_db()
    website_return_time = getattr(sys_settings, "website_return_time", 60)

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

    current_data = _merge_sensor_api(latest_sensor, latest_api)

    latest_vent = None
    try:
        latest_vent_rows = await db.get("ventilation_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
        latest_vent = latest_vent_rows[0] if latest_vent_rows else None
    except Exception:
        pass

    latest_vent_exists = latest_vent is not None
    vent_before: Optional[dict] = None
    vent_after: Optional[dict] = None

    if latest_vent and latest_vent.get("status_ventilation"):
        # Проветривание идёт: сравниваем момент пуска с текущими данными.
        vent_active = True
        vent_before = await _load_merged_by_id(latest_vent.get("id"))
        vent_after = current_data
        card_title = "📊 Сравнение показателей цикла"

    elif latest_vent:
        # Проветривание остановлено: показываем историю последнего цикла.
        vent_active = False
        start_id = latest_vent.get("id")
        stop_plus = latest_vent.get("stop_vent_plus") or 0
        stop_id = (start_id + stop_plus) if start_id is not None else None
        vent_before = await _load_merged_by_id(start_id)
        vent_after = await _load_merged_by_id(stop_id)
        start_label = (
            vent_before.get("timestamp") if vent_before else latest_vent.get("timestamp", "—")
        )
        card_title = f"История {start_label}, проветривания"

    else:
        # Проветривания ещё не было.
        vent_active = False
        vent_after = current_data
        card_title = "Проветривание не включалось"

    if vent_before and vent_after and vent_before.get("timestamp") and vent_after.get("timestamp"):
        vent_start_str = _hhmm(vent_before["timestamp"])
        vent_now_str = _hhmm(vent_after["timestamp"])
        vent_difference_time = get_time_difference_str(vent_start_str, vent_now_str)
    else:
        vent_start_str = _hhmm(vent_before["timestamp"]) if vent_before and vent_before.get("timestamp") else "—"
        vent_now_str = _hhmm(vent_after["timestamp"]) if vent_after and vent_after.get("timestamp") and latest_vent_exists else "—"
        vent_difference_time = "—"

    diffs = {
        f"diff_{field}": _diff_or_none(vent_after, vent_before, field)
        for field, _kind in _VENT_DIFF_FIELDS
    }
    style_classes = {
        f"diff_{field}_class": _vent_class(diffs[f"diff_{field}"], kind)
        for field, kind in _VENT_DIFF_FIELDS
    }

    if vent_active:
        btn_start_class, btn_stop_class = "btn-disabled", "btn-stop"
        btn_start_disabled, btn_stop_disabled = "disabled", ""
    else:
        btn_start_class, btn_stop_class = "btn-start", "btn-disabled"
        btn_start_disabled, btn_stop_disabled = "", "disabled"

    before_data = {f"before_{k}": v for k, v in (vent_before or {}).items()}

    context = {
        "website_return_time": website_return_time,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "vent_active": vent_active,
        "latest_vent_exists": latest_vent_exists,
        "card_title": card_title,
        "is_history_title": (not vent_active and latest_vent_exists),
        "vent_start_time": vent_start_str,
        "vent_now_time": vent_now_str,
        "vent_difference_time": vent_difference_time,
        **(vent_after or {}),
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
    sys_settings = await get_settings_db()
    latest_vent_rows = await db.get("ventilation_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
    latest_vent = latest_vent_rows[0] if latest_vent_rows else None

    can_start = True
    if latest_vent and latest_vent.get("status_ventilation"):
        can_start = False

    if can_start:
        latest_sensor_rows = await db.get("table_sensor_data", order_col="id", order_asc=False, limit=1, log_to_api=False)
        latest_sensor = latest_sensor_rows[0] if latest_sensor_rows else None
        if latest_sensor:
            data_to_write = {
                "id": latest_sensor["id"],
                "timestamp": latest_sensor["timestamp"],
                "status_ventilation": True,
                "stop_vent_plus": 0,
            }
            await db.upsert("ventilation_table", [data_to_write], pk_col="id", log_to_api=False)
            api_log.info(f"Успешный старт проветривания: sensor_id={latest_sensor['id']}")

        latest_api_rows = await db.get("api_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
        latest_api = latest_api_rows[0] if latest_api_rows else None
        if latest_api:
            vent_time_val = latest_api.get("vent_time_val") or 0
            reduced_interval_in_seconds = max(int(vent_time_val / 3 * 60), 60)
            dto = SystemSettingsUpdate(
                interval_seconds=reduced_interval_in_seconds,
                previous_interval_in_seconds=sys_settings.interval_seconds,
            )
            await update_settings(update_dto=dto)

    return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/ventilation/stop")
async def stop_ventilation():
    """Остановка проветривания."""
    sys_settings = await get_settings_db()
    latest_vent_rows = await db.get("ventilation_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
    latest_vent = latest_vent_rows[0] if latest_vent_rows else None
    if latest_vent and latest_vent.get("status_ventilation"):
        latest_sensor_rows = await db.get("table_sensor_data", order_col="id", order_asc=False, limit=1, log_to_api=False)
        latest_sensor = latest_sensor_rows[0] if latest_sensor_rows else None
        if latest_sensor:
            stop_vent_plus = latest_sensor["id"] - latest_vent["id"]

            if stop_vent_plus == 0:
                await db.delete("ventilation_table", pk=latest_vent["id"], pk_col="id", log_to_api=False)
                api_log.info(f"Удаление записи проветривания (stop_vent_plus=0): id={latest_vent['id']}")
            else:
                data_to_write = {
                    "id": latest_vent["id"],
                    "timestamp": latest_vent["timestamp"],
                    "status_ventilation": False,
                    "stop_vent_plus": stop_vent_plus,
                }
                await db.upsert("ventilation_table", [data_to_write], pk_col="id", log_to_api=False)
                api_log.info(
                    f"Успешный стоп проветривания: start_id={latest_vent['id']}, "
                    f"stop_id={latest_sensor['id']}, diff={stop_vent_plus}"
                )

            latest_api_rows = await db.get("api_table", order_col="id", order_asc=False, limit=1, log_to_api=False)
            latest_api = latest_api_rows[0] if latest_api_rows else None
            if latest_api:
                dto = SystemSettingsUpdate(interval_seconds=sys_settings.previous_interval_in_seconds)
                await update_settings(update_dto=dto)

    return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)





# # app/routers/dashboard_router.py

# from datetime import datetime
# import logging
# from typing import Any, Optional

# from fastapi import APIRouter, Depends, Request, status
# from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates

# from app.core.config import settings
# from app.db.repository import BaseRepository
# from app.dependencies import get_repository, get_template_path, get_templates
# from app.schemas.settings_schema import SystemSettingsUpdate

# api_log = logging.getLogger("api_app.routers.dashboard_router")


# def safe_diff(val1: Any, val2: Any) -> float:
#     """Безопасное вычисление разницы между двумя значениями."""
#     if val1 is not None and val2 is not None:
#         try:
#             return round(float(val1) - float(val2), 2)
#         except (ValueError, TypeError):
#             pass
#     return 0.0


# def get_time_difference_str(start_str: str, now_str: str) -> str:
#     """Расчет текстовой разницы времени между двумя строками формата HH:MM."""
#     try:
#         t1 = datetime.strptime(start_str, "%H:%M")
#         t2 = datetime.strptime(now_str, "%H:%M")
#         diff = int((t2 - t1).total_seconds() // 60)
#         if diff < 0:
#             diff += 1440
#         hours = diff // 60
#         minutes = diff % 60
#         return f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
#     except Exception:
#         return "—"


# def _merge_sensor_api(sensor: Any, api: Any) -> dict:
#     """Объединяет запись датчиков и запись api_table (timestamp берётся из датчиков)."""
#     data = dict(sensor)
#     api_data = dict(api)
#     api_data.pop("timestamp", None)
#     data.update(api_data)
#     return data


# async def _load_merged_by_id(repo: BaseRepository, record_id: Optional[int]) -> Optional[dict]:
#     """Собирает sensor + api по id. Если любой из записей нет — возвращает None."""
#     if record_id is None:
#         return None
#     sensor = await repo.get_record_by_id("table_sensor_data", record_id, log_to_api=False)
#     api = await repo.get_record_by_id("api_table", record_id, log_to_api=False)
#     if not sensor or not api:
#         return None
#     return _merge_sensor_api(sensor, api)


# def _hhmm(ts: Any) -> str:
#     """Возвращает HH:MM из строки 'YYYY-MM-DD HH:MM:SS', иначе исходную строку."""
#     s = str(ts)
#     return s[11:16] if len(s) >= 16 else s


# def _diff_or_none(after: Optional[dict], before: Optional[dict], key: str) -> Optional[float]:
#     """Разница after - before или None, если данных для сравнения нет."""
#     if not after or not before:
#         return None
#     a, b = after.get(key), before.get(key)
#     if a is None or b is None:
#         return None
#     return safe_diff(a, b)


# def _vent_class(val: Optional[float], kind: str) -> str:
#     """CSS-класс дельты: temp — синий при изменении; rh/ah — зелёный при снижении влажности."""
#     if val is None:
#         return "text-gray"
#     if kind == "temp":
#         return "text-blue" if abs(val) > 0.1 else "text-gray"
#     threshold = 0.5 if kind == "rh" else 0.1
#     if val < -threshold:
#         return "text-green"
#     if val > threshold:
#         return "text-red"
#     return "text-gray"


# # (поле, тип для раскраски)
# _VENT_DIFF_FIELDS = (
#     ("basement_temp", "temp"),
#     ("basement_humi", "rh"),
#     ("a_basement_humi", "ah"),
#     ("floor_temp", "temp"),
#     ("floor_humi", "rh"),
#     ("a_floor_humi", "ah"),
# )


# router = APIRouter(
#     tags=["Dashboard & Web UI"],
# )


# @router.get("/", response_class=HTMLResponse, summary="Главная страница дашборда")
# async def get_index(
#     request: Request,
#     templates: Jinja2Templates = Depends(get_templates),
#     repo: BaseRepository = Depends(get_repository),
# ) -> Any:
#     """Главная страница климат-контроля со сводкой показателей."""
#     api_log.info("GET / -> открытие главной страницы дашборда")

#     try:
#         sys_settings = await repo.get_settings_db(log_to_api=True)
#         website_return_time = getattr(sys_settings, "website_return_time", 60)
#         target_rh = getattr(sys_settings, "target_rh", 60.0)
#         abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)
#         app_env = settings.app_env.value

#         latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=True)
#         latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=True)

#         if not latest_sensor or not latest_api:
#             api_log.warning("На сервер не приходят значения из базы данных")
#             return templates.TemplateResponse(
#                 request=request,
#                 name=get_template_path("no_data.html", request),
#                 context={"website_return_time": website_return_time},
#                 status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#             )

#         db_data = _merge_sensor_api(latest_sensor, latest_api)

#         vent_status = db_data.get("vent_status")
#         vent_time_val = db_data.get("vent_time_val")

#         if vent_status and vent_time_val:
#             msg_vent_status = "ДА"
#             vent_reason = f"Время: {vent_time_val} мин."
#         elif not vent_status:
#             msg_vent_status = "НЕТ"
#             vent_reason = f"dАВ < {abs_tolerance}"
#         else:
#             msg_vent_status = "НЕТ"
#             vent_reason = "Тяги нет."

#         if vent_status:
#             vent_class = "badge-green"
#             vent_display_class = ""
#         else:
#             vent_class = "badge-red"
#             vent_display_class = "d-none"

#         heat_status = db_data.get("heat_status")
#         heating_delta = db_data.get("heating_delta", 0.0)

#         if heat_status:
#             msg_heat_status = "ДА"
#             heat_info = f"+{heating_delta} °C"
#             heat_class = "badge-amber"
#             heat_display_class = ""
#         else:
#             msg_heat_status = "НЕТ"
#             heat_info = ""
#             heat_class = "badge-gray"
#             heat_display_class = "d-none"

#         active_modes = []
#         try:
#             latest_vent = await repo.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
#             if latest_vent and latest_vent.get("status_ventilation"):
#                 active_modes.append("Проветривание")
#         except Exception:
#             pass

#         try:
#             latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
#             if latest_heat and latest_heat.get("status_heating"):
#                 active_modes.append("Отопление")
#         except Exception:
#             pass

#         active_mode = ", ".join(active_modes) if active_modes else ""

#         context = {
#             "website_return_time": website_return_time,
#             "max_rh": target_rh,
#             "msg_vent_status": msg_vent_status,
#             "vent_reason": vent_reason,
#             "vent_class": vent_class,
#             "vent_display_class": vent_display_class,
#             "msg_heat_status": msg_heat_status,
#             "heat_info": heat_info,
#             "heat_class": heat_class,
#             "heat_display_class": heat_display_class,
#             "active_mode": active_mode,
#             "app_env": app_env,
#             **db_data,
#         }

#         return templates.TemplateResponse(
#             request=request,
#             name=get_template_path("index.html", request),
#             context=context,
#         )

#     except Exception as e:
#         api_log.error(f"Ошибка при формировании главной страницы: {e}", exc_info=True)
#         return_time = getattr(sys_settings, "website_return_time", 60) if 'sys_settings' in locals() and sys_settings else 60
#         return templates.TemplateResponse(
#             request=request,
#             name=get_template_path("no_data.html", request),
#             context={"website_return_time": return_time},
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#         )


# @router.get("/ventilation", response_class=HTMLResponse, summary="Страница проветривания")
# async def get_ventilation_page(
#     request: Request,
#     templates: Jinja2Templates = Depends(get_templates),
#     repo: BaseRepository = Depends(get_repository),
# ) -> Any:
#     """Страница ручного управления проветриванием: текущий цикл или история последнего."""
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     website_return_time = getattr(sys_settings, "website_return_time", 60)

#     latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#     latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=False)

#     if not latest_sensor or not latest_api:
#         return templates.TemplateResponse(
#             request=request,
#             name=get_template_path("no_data.html", request),
#             context={"website_return_time": website_return_time},
#             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#         )

#     current_data = _merge_sensor_api(latest_sensor, latest_api)

#     latest_vent = None
#     try:
#         latest_vent = await repo.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
#     except Exception:
#         pass

#     latest_vent_exists = latest_vent is not None
#     vent_before: Optional[dict] = None
#     vent_after: Optional[dict] = None

#     if latest_vent and latest_vent.get("status_ventilation"):
#         # Проветривание идёт: сравниваем момент пуска с текущими данными.
#         vent_active = True
#         vent_before = await _load_merged_by_id(repo, latest_vent.get("id"))
#         vent_after = current_data
#         card_title = "📊 Сравнение показателей цикла"

#     elif latest_vent:
#         # Проветривание остановлено: показываем историю последнего цикла.
#         vent_active = False
#         start_id = latest_vent.get("id")
#         stop_plus = latest_vent.get("stop_vent_plus") or 0
#         stop_id = (start_id + stop_plus) if start_id is not None else None
#         vent_before = await _load_merged_by_id(repo, start_id)
#         vent_after = await _load_merged_by_id(repo, stop_id)
#         start_label = (
#             vent_before.get("timestamp") if vent_before else latest_vent.get("timestamp", "—")
#         )
#         card_title = f"История {start_label}, проветривания"

#     else:
#         # Проветривания ещё не было.
#         vent_active = False
#         vent_after = current_data
#         card_title = "Проветривание не включалось"

#     if vent_before and vent_after and vent_before.get("timestamp") and vent_after.get("timestamp"):
#         vent_start_str = _hhmm(vent_before["timestamp"])
#         vent_now_str = _hhmm(vent_after["timestamp"])
#         vent_difference_time = get_time_difference_str(vent_start_str, vent_now_str)
#     else:
#         vent_start_str = _hhmm(vent_before["timestamp"]) if vent_before and vent_before.get("timestamp") else "—"
#         vent_now_str = _hhmm(vent_after["timestamp"]) if vent_after and vent_after.get("timestamp") and latest_vent_exists else "—"
#         vent_difference_time = "—"

#     diffs = {
#         f"diff_{field}": _diff_or_none(vent_after, vent_before, field)
#         for field, _kind in _VENT_DIFF_FIELDS
#     }
#     style_classes = {
#         f"diff_{field}_class": _vent_class(diffs[f"diff_{field}"], kind)
#         for field, kind in _VENT_DIFF_FIELDS
#     }

#     if vent_active:
#         btn_start_class, btn_stop_class = "btn-disabled", "btn-stop"
#         btn_start_disabled, btn_stop_disabled = "disabled", ""
#     else:
#         btn_start_class, btn_stop_class = "btn-start", "btn-disabled"
#         btn_start_disabled, btn_stop_disabled = "", "disabled"

#     before_data = {f"before_{k}": v for k, v in (vent_before or {}).items()}

#     context = {
#         "website_return_time": website_return_time,
#         "btn_start_class": btn_start_class,
#         "btn_stop_class": btn_stop_class,
#         "btn_start_disabled": btn_start_disabled,
#         "btn_stop_disabled": btn_stop_disabled,
#         "vent_active": vent_active,
#         "latest_vent_exists": latest_vent_exists,
#         "card_title": card_title,
#         "is_history_title": (not vent_active and latest_vent_exists),
#         "vent_start_time": vent_start_str,
#         "vent_now_time": vent_now_str,
#         "vent_difference_time": vent_difference_time,
#         **(vent_after or {}),
#         **before_data,
#         **diffs,
#         **style_classes,
#     }

#     return templates.TemplateResponse(
#         request=request, name=get_template_path("ventilation.html", request), context=context
#     )


# @router.post("/api/ventilation/start")
# async def start_ventilation(repo: BaseRepository = Depends(get_repository)):
#     """Запуск проветривания."""
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     latest_vent = await repo.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)

#     can_start = True
#     if latest_vent and latest_vent.get("status_ventilation"):
#         can_start = False

#     if can_start:
#         latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#         if latest_sensor:
#             data_to_write = {
#                 "id": latest_sensor["id"],
#                 "timestamp": latest_sensor["timestamp"],
#                 "status_ventilation": True,
#                 "stop_vent_plus": 0,
#             }
#             await repo.upsert_record("ventilation_table", data_to_write, pk_col="id", log_to_api=False)
#             api_log.info(f"Успешный старт проветривания: sensor_id={latest_sensor['id']}")

#         latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=False)
#         if latest_api:
#             vent_time_val = latest_api.get("vent_time_val") or 0
#             reduced_interval_in_seconds = max(int(vent_time_val / 3 * 60), 60)
#             dto = SystemSettingsUpdate(
#                 interval_seconds=reduced_interval_in_seconds,
#                 previous_interval_in_seconds=sys_settings.interval_seconds,
#             )
#             await repo.update_settings(update_dto=dto)

#     return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)


# @router.post("/api/ventilation/stop")
# async def stop_ventilation(repo: BaseRepository = Depends(get_repository)):
#     """Остановка проветривания."""
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     latest_vent = await repo.get_latest_record("ventilation_table", order_by_col="id", log_to_api=False)
#     if latest_vent and latest_vent.get("status_ventilation"):
#         latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#         if latest_sensor:
#             stop_vent_plus = latest_sensor["id"] - latest_vent["id"]

#             if stop_vent_plus == 0:
#                 await repo.delete_record_by_id("ventilation_table", latest_vent["id"], pk_col="id", log_to_api=False)
#                 api_log.info(f"Удаление записи проветривания (stop_vent_plus=0): id={latest_vent['id']}")
#             else:
#                 data_to_write = {
#                     "id": latest_vent["id"],
#                     "timestamp": latest_vent["timestamp"],
#                     "status_ventilation": False,
#                     "stop_vent_plus": stop_vent_plus,
#                 }
#                 await repo.upsert_record("ventilation_table", data_to_write, pk_col="id", log_to_api=False)
#                 api_log.info(
#                     f"Успешный стоп проветривания: start_id={latest_vent['id']}, "
#                     f"stop_id={latest_sensor['id']}, diff={stop_vent_plus}"
#                 )

#             latest_api = await repo.get_latest_record("api_table", order_by_col="id", log_to_api=False)
#             if latest_api:
#                 dto = SystemSettingsUpdate(interval_seconds=sys_settings.previous_interval_in_seconds)
#                 await repo.update_settings(update_dto=dto)

#     return RedirectResponse(url="/ventilation", status_code=status.HTTP_303_SEE_OTHER)
