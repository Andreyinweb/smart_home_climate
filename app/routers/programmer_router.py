# app/routers/programmer_router.py

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.db.repository import BaseRepository
from app.dependencies import (
    get_programmer,
    get_repository,
    get_template_path,
    get_templates,
)
from app.services.programmer_service import Programmer

api_log = logging.getLogger("api_app.routers.programmer")

router = APIRouter(
    tags=["Programmer"],
)

DAYS_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
TEMPORARILY_MODES = ("PROGRAMMER_TEMPORARILY_CONST", "PROGRAMMER_TEMPORARILY_WEEK")
CONST_MODES = ("PROGRAMMER_CONST", "PROGRAMMER_TEMPORARILY_CONST")
WEEK_MODES = ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK")


def _parse_float(val: Optional[str]) -> Optional[float]:
    """Безопасное преобразование строки из HTML-формы в float."""
    if val is None:
        return None
    val_str = val.strip()
    if not val_str:
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def _valid_week_mode(mode: Optional[str]) -> str:
    """Возвращает режим дней недели, если он допустим, иначе 'week'."""
    return mode if mode in settings.days_week_mode else "week"


def _parse_sensor_time(latest_sensor: Optional[Dict[str, Any]]) -> tuple:
    """Возвращает (день недели, время HH:MM, температура подвала) из последней записи датчиков."""
    if not latest_sensor or not latest_sensor.get("timestamp"):
        return "—", "—", None

    ts_str = str(latest_sensor["timestamp"])
    current_dow, current_time = "—", "—"
    try:
        dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        current_dow = DAYS_SHORT[dt.weekday()]
        current_time = dt.strftime("%H:%M")
    except ValueError:
        if len(ts_str) >= 16:
            current_time = ts_str[11:16]

    return current_dow, current_time, latest_sensor.get("basement_temp")


@router.get("/programmer", response_class=HTMLResponse, summary="Страница программатора")
async def get_programmer_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Страница настройки программатора. Только чтение данных и рендер HTML."""
    sys_settings = await repo.get_settings_db(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)
    programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

    try:
        latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из table_sensor_data: {e}")
        latest_sensor = None
    current_dow, current_time, basement_temp = _parse_sensor_time(latest_sensor)

    try:
        latest_temp = await repo.get_record_by_id("programmer_temporarily", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из programmer_temporarily: {e}")
        latest_temp = None

    temporarily_temp = 20.0
    temporarily_time = ""
    if latest_temp and latest_temp.get("temporarily") is not None:
        temporarily_temp = latest_temp["temporarily"]
    if latest_temp and latest_temp.get("temporarily_time"):
        temporarily_time = str(latest_temp["temporarily_time"])[11:16]

    try:
        latest_const = await repo.get_record_by_id("programmer_const", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из programmer_const: {e}")
        latest_const = None

    const_min, const_max = 18.0, 24.0
    if latest_const and latest_const.get("const_max") is not None:
        const_min = latest_const.get("const_min", 18.0)
        const_max = latest_const["const_max"]

    try:
        week_sys_row = await repo.get_record_by_id("programmer_week", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения системной строки из programmer_week: {e}")
        week_sys_row = None

    active_row_id = week_sys_row.get("now_id") if week_sys_row else None
    week_mode = _valid_week_mode(week_sys_row.get("week_mode") if week_sys_row else None)
    allowed_days = settings.days_week_mode.get(week_mode, ["Mo_Su"])

    all_week_records = await repo.fetch_range(
        table_name="programmer_week",
        filter_col="week_mode",
        start_val=week_mode,
        stop_val=week_mode,
    )
    week_records = [rec for rec in all_week_records if rec.get("id") != 1]

    def record_sort_key(rec):
        day = rec.get("week_day", "")
        day_idx = allowed_days.index(day) if day in allowed_days else len(allowed_days)
        return (day_idx, str(rec.get("week_time", "")))

    week_records.sort(key=record_sort_key)

    grouped_records = [
        {"day": d, "records": [r for r in week_records if r.get("week_day") == d]}
        for d in allowed_days
    ]
    other_recs = [r for r in week_records if r.get("week_day") not in allowed_days]
    if other_recs:
        grouped_records.append({"day": "Другие", "records": other_recs})

    context = {
        "website_return_time": website_return_time,
        "current_dow": current_dow,
        "current_time": current_time,
        "basement_temp": basement_temp,
        "temporarily_temp": temporarily_temp,
        "temporarily_time": temporarily_time,
        "const_min": const_min,
        "const_max": const_max,
        "flag_temporarily": programmer_mode in TEMPORARILY_MODES,
        "flag_const": programmer_mode in CONST_MODES,
        "flag_week": programmer_mode in WEEK_MODES,
        "programmer_mode": programmer_mode,
        "week_mode": week_mode,
        "week_records": week_records,
        "grouped_records": grouped_records,
        "allowed_days": allowed_days,
        "week_modes_list": list(settings.days_week_mode.keys()),
        "week_days_list": allowed_days,
        "active_row_id": active_row_id,
    }

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("programmer.html", request),
        context=context,
    )


@router.post("/api/programmer/update")
async def update_programmer(
    const_min: Optional[str] = Form(None),
    const_max: Optional[str] = Form(None),
    flag_const: Optional[str] = Form(None),
    temporarily_temp: Optional[str] = Form(None),
    temporarily_time: Optional[str] = Form(None),
    flag_temporarily: Optional[str] = Form(None),
    flag_week: Optional[str] = Form(None),
    week_ids: List[int] = Form([]),
    week_days: List[str] = Form([]),
    week_times: List[str] = Form([]),
    week_temps: List[str] = Form([]),
    programmer: Programmer = Depends(get_programmer),
    repo: BaseRepository = Depends(get_repository),
):
    """Сохранение уставок, флагов режима и строк расписания. Режим дней недели здесь не меняется."""
    is_flag_temporarily = bool(flag_temporarily)
    is_flag_const = bool(flag_const)
    is_flag_week = bool(flag_week)

    c_min = _parse_float(const_min)
    c_max = _parse_float(const_max)
    t_temp = _parse_float(temporarily_temp)
    t_time = temporarily_time.strip() if temporarily_time else ""

    if is_flag_temporarily and is_flag_const:
        if not t_time or t_time in ("00:00", "0"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для временного режима с постоянным время не должно быть нулевым или пустым.",
            )

    if is_flag_const:
        if c_min is None or c_max is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Поля минимальной и максимальной температуры должны быть заполнены.",
            )
        if c_min >= c_max:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Минимальная температура должна быть строго меньше максимальной.",
            )

    if c_min is not None and c_max is not None:
        await programmer.save_programmer_const(c_min, c_max)

    if week_ids:
        parsed_temps = [_parse_float(t) for t in week_temps]

        # Отправленные строки принадлежат ТЕКУЩЕМУ режиму из системной строки id=1,
        # а не тому, что выбран в селекте. Проверяем дни по режиму самих строк.
        sys_row = await repo.get_record_by_id("programmer_week", 1)
        rows_mode = _valid_week_mode(sys_row.get("week_mode") if sys_row else None)
        allowed = settings.days_week_mode.get(rows_mode, ["Mo_Su"])

        if rows_mode == "week":
            sanitized_days = ["Mo_Su"] * len(week_ids)
        else:
            sanitized_days = [d if d in allowed else allowed[0] for d in week_days]

        await programmer.save_programmer_week(
            week_ids=week_ids,
            week_days=sanitized_days,
            week_times=week_times,
            week_temps=parsed_temps,
        )

    await programmer.update_programmer_mode(
        flag_temporarily=is_flag_temporarily,
        flag_const=is_flag_const,
        flag_week=is_flag_week,
    )

    if t_temp is not None:
        await programmer.save_programmer_temporarily(
            temporarily=t_temp,
            temporarily_time=t_time,
        )

    await programmer.evaluate()

    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/programmer/week/mode")
async def switch_week_mode(
    week_mode: Optional[str] = Form(None),
    programmer: Programmer = Depends(get_programmer),
):
    """
    Переключение режима дней недели. Записи расписания и уставки не сохраняются.
    После смены системной строки сразу пересчитываем применяемые пороги отопления.
    """
    await programmer.update_week_mode(_valid_week_mode(week_mode))
    await programmer.evaluate()
    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/programmer/week/add")
async def add_programmer_week_row(
    programmer: Programmer = Depends(get_programmer),
    repo: BaseRepository = Depends(get_repository),
):
    """Добавление новой строки в расписание programmer_week. Режим берётся из системной строки id=1."""
    sys_row = await repo.get_record_by_id("programmer_week", 1)
    mode = _valid_week_mode(sys_row.get("week_mode") if sys_row else None)
    day = settings.days_week_mode.get(mode, ["Mo_Su"])[0]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_record = {
        "week_mode": mode,
        "week_day": day,
        "week_time": "23:59",
        "week_temperature": 20.0,
        "updated_at": now_str,
    }

    await programmer.add_programmer_week_row(new_record)
    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/programmer/week/delete/{row_id}")
async def delete_programmer_week_row(
    row_id: int,
    programmer: Programmer = Depends(get_programmer),
):
    """Удаление строки из расписания programmer_week. Системная строка id=1 не удаляется."""
    if row_id > 1:
        await programmer.delete_programmer_week_row(row_id)

    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)




# # app/routers/programmer_router.py

# from datetime import datetime
# import logging
# from typing import Any, Dict, List, Optional

# from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
# from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates

# from app.core.config import settings
# from app.db.repository import BaseRepository
# from app.dependencies import (
#     get_programmer,
#     get_repository,
#     get_template_path,
#     get_templates,
# )
# from app.services.programmer_service import Programmer

# api_log = logging.getLogger("api_app.routers.programmer")

# router = APIRouter(
#     tags=["Programmer"],
# )

# DAYS_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
# TEMPORARILY_MODES = ("PROGRAMMER_TEMPORARILY_CONST", "PROGRAMMER_TEMPORARILY_WEEK")
# CONST_MODES = ("PROGRAMMER_CONST", "PROGRAMMER_TEMPORARILY_CONST")
# WEEK_MODES = ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK")


# def _parse_float(val: Optional[str]) -> Optional[float]:
#     """Безопасное преобразование строки из HTML-формы в float."""
#     if val is None:
#         return None
#     val_str = val.strip()
#     if not val_str:
#         return None
#     try:
#         return float(val_str)
#     except ValueError:
#         return None


# def _valid_week_mode(mode: Optional[str]) -> str:
#     """Возвращает режим дней недели, если он допустим, иначе 'week'."""
#     return mode if mode in settings.days_week_mode else "week"


# def _parse_sensor_time(latest_sensor: Optional[Dict[str, Any]]) -> tuple:
#     """Возвращает (день недели, время HH:MM, температура подвала) из последней записи датчиков."""
#     if not latest_sensor or not latest_sensor.get("timestamp"):
#         return "—", "—", None

#     ts_str = str(latest_sensor["timestamp"])
#     current_dow, current_time = "—", "—"
#     try:
#         dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
#         current_dow = DAYS_SHORT[dt.weekday()]
#         current_time = dt.strftime("%H:%M")
#     except ValueError:
#         if len(ts_str) >= 16:
#             current_time = ts_str[11:16]

#     return current_dow, current_time, latest_sensor.get("basement_temp")


# @router.get("/programmer", response_class=HTMLResponse, summary="Страница программатора")
# async def get_programmer_page(
#     request: Request,
#     templates: Jinja2Templates = Depends(get_templates),
#     repo: BaseRepository = Depends(get_repository),
# ) -> Any:
#     """Страница настройки программатора. Только чтение данных и рендер HTML."""
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     website_return_time = getattr(sys_settings, "website_return_time", 60)
#     programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

#     try:
#         latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из table_sensor_data: {e}")
#         latest_sensor = None
#     current_dow, current_time, basement_temp = _parse_sensor_time(latest_sensor)

#     try:
#         latest_temp = await repo.get_record_by_id("programmer_temporarily", 1)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из programmer_temporarily: {e}")
#         latest_temp = None

#     temporarily_temp = 20.0
#     temporarily_time = ""
#     if latest_temp and latest_temp.get("temporarily") is not None:
#         temporarily_temp = latest_temp["temporarily"]
#     if latest_temp and latest_temp.get("temporarily_time"):
#         temporarily_time = str(latest_temp["temporarily_time"])[11:16]

#     try:
#         latest_const = await repo.get_record_by_id("programmer_const", 1)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из programmer_const: {e}")
#         latest_const = None

#     const_min, const_max = 18.0, 24.0
#     if latest_const and latest_const.get("const_max") is not None:
#         const_min = latest_const.get("const_min", 18.0)
#         const_max = latest_const["const_max"]

#     try:
#         week_sys_row = await repo.get_record_by_id("programmer_week", 1)
#     except Exception as e:
#         api_log.error(f"Ошибка получения системной строки из programmer_week: {e}")
#         week_sys_row = None

#     active_row_id = week_sys_row.get("now_id") if week_sys_row else None
#     week_mode = _valid_week_mode(week_sys_row.get("week_mode") if week_sys_row else None)
#     allowed_days = settings.days_week_mode.get(week_mode, ["Mo_Su"])

#     all_week_records = await repo.fetch_range(
#         table_name="programmer_week",
#         filter_col="week_mode",
#         start_val=week_mode,
#         stop_val=week_mode,
#     )
#     week_records = [rec for rec in all_week_records if rec.get("id") != 1]

#     def record_sort_key(rec):
#         day = rec.get("week_day", "")
#         day_idx = allowed_days.index(day) if day in allowed_days else len(allowed_days)
#         return (day_idx, str(rec.get("week_time", "")))

#     week_records.sort(key=record_sort_key)

#     grouped_records = [
#         {"day": d, "records": [r for r in week_records if r.get("week_day") == d]}
#         for d in allowed_days
#     ]
#     other_recs = [r for r in week_records if r.get("week_day") not in allowed_days]
#     if other_recs:
#         grouped_records.append({"day": "Другие", "records": other_recs})

#     context = {
#         "website_return_time": website_return_time,
#         "current_dow": current_dow,
#         "current_time": current_time,
#         "basement_temp": basement_temp,
#         "temporarily_temp": temporarily_temp,
#         "temporarily_time": temporarily_time,
#         "const_min": const_min,
#         "const_max": const_max,
#         "flag_temporarily": programmer_mode in TEMPORARILY_MODES,
#         "flag_const": programmer_mode in CONST_MODES,
#         "flag_week": programmer_mode in WEEK_MODES,
#         "programmer_mode": programmer_mode,
#         "week_mode": week_mode,
#         "week_records": week_records,
#         "grouped_records": grouped_records,
#         "allowed_days": allowed_days,
#         "week_modes_list": list(settings.days_week_mode.keys()),
#         "week_days_list": allowed_days,
#         "active_row_id": active_row_id,
#     }

#     return templates.TemplateResponse(
#         request=request,
#         name=get_template_path("programmer.html", request),
#         context=context,
#     )


# @router.post("/api/programmer/update")
# async def update_programmer(
#     const_min: Optional[str] = Form(None),
#     const_max: Optional[str] = Form(None),
#     flag_const: Optional[str] = Form(None),
#     temporarily_temp: Optional[str] = Form(None),
#     temporarily_time: Optional[str] = Form(None),
#     flag_temporarily: Optional[str] = Form(None),
#     flag_week: Optional[str] = Form(None),
#     week_mode: Optional[str] = Form(None),
#     week_ids: List[int] = Form([]),
#     week_days: List[str] = Form([]),
#     week_times: List[str] = Form([]),
#     week_temps: List[str] = Form([]),
#     programmer: Programmer = Depends(get_programmer),
#     repo: BaseRepository = Depends(get_repository),
# ):
#     is_flag_temporarily = bool(flag_temporarily)
#     is_flag_const = bool(flag_const)
#     is_flag_week = bool(flag_week)

#     c_min = _parse_float(const_min)
#     c_max = _parse_float(const_max)
#     t_temp = _parse_float(temporarily_temp)
#     t_time = temporarily_time.strip() if temporarily_time else ""

#     if is_flag_temporarily and is_flag_const:
#         if not t_time or t_time in ("00:00", "0"):
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Для временного режима с постоянным время не должно быть нулевым или пустым.",
#             )

#     if is_flag_const:
#         if c_min is None or c_max is None:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Поля минимальной и максимальной температуры должны быть заполнены.",
#             )
#         if c_min >= c_max:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Минимальная температура должна быть строго меньше максимальной.",
#             )

#     if c_min is not None and c_max is not None:
#         await programmer.save_programmer_const(c_min, c_max)

#     if week_ids:
#         parsed_temps = [_parse_float(t) for t in week_temps]

#         # Отправленные строки принадлежат ТЕКУЩЕМУ режиму из системной строки id=1,
#         # а не тому, что выбран в селекте. Проверяем дни по режиму самих строк.
#         sys_row = await repo.get_record_by_id("programmer_week", 1)
#         rows_mode = _valid_week_mode(sys_row.get("week_mode") if sys_row else None)
#         allowed = settings.days_week_mode.get(rows_mode, ["Mo_Su"])

#         if rows_mode == "week":
#             sanitized_days = ["Mo_Su"] * len(week_ids)
#         else:
#             sanitized_days = [d if d in allowed else allowed[0] for d in week_days]

#         await programmer.save_programmer_week(
#             week_ids=week_ids,
#             week_days=sanitized_days,
#             week_times=week_times,
#             week_temps=parsed_temps,
#         )

#     # Переключение на новый режим происходит уже после сохранения строк старого
#     if week_mode:
#         await programmer.update_week_mode(_valid_week_mode(week_mode))

#     await programmer.update_programmer_mode(
#         flag_temporarily=is_flag_temporarily,
#         flag_const=is_flag_const,
#         flag_week=is_flag_week,
#     )

#     if t_temp is not None:
#         await programmer.save_programmer_temporarily(
#             temporarily=t_temp,
#             temporarily_time=t_time,
#         )

#     await programmer.evaluate()

#     return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


# @router.post("/api/programmer/week/add")
# async def add_programmer_week_row(
#     week_mode: Optional[str] = Form("week"),
#     programmer: Programmer = Depends(get_programmer),
# ):
#     """Добавление новой строки в расписание programmer_week."""
#     mode = _valid_week_mode(week_mode)
#     day = settings.days_week_mode.get(mode, ["Mo_Su"])[0]
#     now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#     new_record = {
#         "week_mode": mode,
#         "week_day": day,
#         "week_time": "23:59",
#         "week_temperature": 20.0,
#         "updated_at": now_str,
#     }

#     await programmer.add_programmer_week_row(new_record)
#     return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


# @router.post("/api/programmer/week/delete/{row_id}")
# async def delete_programmer_week_row(
#     row_id: int,
#     programmer: Programmer = Depends(get_programmer),
# ):
#     """Удаление строки из расписания programmer_week. Системная строка id=1 не удаляется."""
#     if row_id > 1:
#         await programmer.delete_programmer_week_row(row_id)

#     return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)