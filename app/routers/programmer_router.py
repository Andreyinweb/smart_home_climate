# app/routers/programmer_router.py

from datetime import datetime
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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


@router.get("/programmer", response_class=HTMLResponse, summary="Страница программатора")
async def get_programmer_page(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    repo: BaseRepository = Depends(get_repository),
) -> Any:
    """Точка входа для отображения страницы настройки программатора."""
    sys_settings = await repo.get_settings_db(log_to_api=False)
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

    latest_temp = None
    try:
        latest_temp = await repo.get_record_by_id("programmer_temporarily", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из programmer_temporarily: {e}")

    temporarily_temp = latest_temp.get("temporarily", 20.0) if latest_temp and latest_temp.get("temporarily") is not None else 20.0
    temporarily_time = latest_temp.get("temporarily_time", "") if latest_temp and latest_temp.get("temporarily_time") is not None else ""

    latest_const = None
    try:
        latest_const = await repo.get_record_by_id("programmer_const", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения данных из programmer_const: {e}")

    const_min = latest_const.get("const_min", 18.0) if latest_const and latest_const.get("const_min") is not None else 18.0
    const_max = latest_const.get("const_max", 24.0) if latest_const and latest_const.get("const_max") is not None else 24.0

    week_sys_row = None
    try:
        week_sys_row = await repo.get_record_by_id("programmer_week", 1)
    except Exception as e:
        api_log.error(f"Ошибка получения системной строки из programmer_week: {e}")

    week_mode = week_sys_row.get("week_mode", "week") if week_sys_row and week_sys_row.get("week_mode") else "week"

    all_week_records = await repo.fetch_range(
        table_name="programmer_week",
        filter_col="week_mode",
        start_val=week_mode,
        stop_val=week_mode,
    )

    week_records = [rec for rec in all_week_records if rec.get("id") != 1]
    week_records.sort(key=lambda x: str(x.get("week_time", "")))

    flag_temporarily = (programmer_mode in ("PROGRAMMER_TEMPORARILY_CONST", "PROGRAMMER_TEMPORARILY_WEEK"))
    flag_const = (programmer_mode in ("PROGRAMMER_CONST", "PROGRAMMER_TEMPORARILY_CONST"))
    flag_week = (programmer_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK"))

    context = {
        "website_return_time": website_return_time,
        "current_dow": current_dow,
        "current_time": current_time,
        "basement_temp": basement_temp,
        "temporarily_temp": temporarily_temp,
        "temporarily_time": temporarily_time,
        "const_min": const_min,
        "const_max": const_max,
        "flag_temporarily": flag_temporarily,
        "flag_const": flag_const,
        "flag_week": flag_week,
        "programmer_mode": programmer_mode,
        "week_mode": week_mode,
        "week_records": week_records,
        "week_modes_list": ["day", "weekdays", "weekdays_weekend", "week"],
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
    week_mode: Optional[str] = Form(None),
    programmer: Programmer = Depends(get_programmer),
    repo: BaseRepository = Depends(get_repository),
):
    sys_settings = await repo.get_settings_db(log_to_api=False)
    current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

    is_flag_temporarily = bool(flag_temporarily)
    is_flag_const = bool(flag_const)
    is_flag_week = bool(flag_week)

    c_min = _parse_float(const_min)
    c_max = _parse_float(const_max)
    t_temp = _parse_float(temporarily_temp)
    t_time = temporarily_time.strip() if temporarily_time else ""

    if is_flag_temporarily:
        if current_mode in ("PROGRAMMER_CONST", "PROGRAMMER_TEMPORARILY_CONST", "PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK"):
            if not t_time or t_time in ("00:00", "0"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Для временного режима время не должно быть нулевым или пустым.",
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

    if t_temp is not None:
        await programmer.save_programmer_temporarily(
            temporarily=t_temp,
            temporarily_time=t_time,
        )

    if week_mode:
        await repo.update_record("programmer_week", 1, {"week_mode": week_mode})

    if hasattr(programmer, "update_programmer_mode"):
        try:
            await programmer.update_programmer_mode(
                flag_temporarily=is_flag_temporarily,
                flag_const=is_flag_const,
                flag_week=is_flag_week,
            )
        except TypeError:
            await programmer.update_programmer_mode(
                flag_temporarily=is_flag_temporarily,
                flag_const=is_flag_const,
            )

    await programmer.evaluate()

    return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)


# # app/routers/programmer_router.py

# from datetime import datetime
# import logging
# from typing import Any, Optional

# from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
# from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates

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


# @router.get("/programmer", response_class=HTMLResponse, summary="Страница программатора")
# async def get_programmer_page(
#     request: Request,
#     templates: Jinja2Templates = Depends(get_templates),
#     repo: BaseRepository = Depends(get_repository),
# ) -> Any:
#     """Точка входа для отображения страницы настройки программатора."""
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     website_return_time = getattr(sys_settings, "website_return_time", 60)
#     programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

#     latest_sensor = None
#     try:
#         latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из table_sensor_data: {e}")

#     current_dow = "—"
#     current_time = "—"
#     basement_temp = None

#     if latest_sensor and latest_sensor.get("timestamp"):
#         ts_str = str(latest_sensor["timestamp"])
#         try:
#             dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
#             days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
#             current_dow = days[dt.weekday()]
#             current_time = dt.strftime("%H:%M")
#         except Exception:
#             if len(ts_str) >= 16:
#                 current_time = ts_str[11:16]

#         basement_temp = latest_sensor.get("basement_temp")

#     latest_temp = None
#     try:
#         latest_temp = await repo.get_record_by_id("programmer_temporarily", 1)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из programmer_temporarily: {e}")

#     temporarily_temp = latest_temp.get("temporarily", 20.0) if latest_temp and latest_temp.get("temporarily") is not None else 20.0
#     temporarily_time = latest_temp.get("temporarily_time", "") if latest_temp and latest_temp.get("temporarily_time") is not None else ""

#     latest_const = None
#     try:
#         latest_const = await repo.get_record_by_id("programmer_const", 1)
#     except Exception as e:
#         api_log.error(f"Ошибка получения данных из programmer_const: {e}")

#     const_min = latest_const.get("const_min", 18.0) if latest_const and latest_const.get("const_min") is not None else 18.0
#     const_max = latest_const.get("const_max", 24.0) if latest_const and latest_const.get("const_max") is not None else 24.0

#     flag_temporarily = (programmer_mode in ("PROGRAMMER_TEMPORARILY_CONST", "PROGRAMMER_TEMPORARILY_WEEK"))
#     flag_const = (programmer_mode == "PROGRAMMER_CONST")

#     context = {
#         "website_return_time": website_return_time,
#         "current_dow": current_dow,
#         "current_time": current_time,
#         "basement_temp": basement_temp,
#         "temporarily_temp": temporarily_temp,
#         "temporarily_time": temporarily_time,
#         "const_min": const_min,
#         "const_max": const_max,
#         "flag_temporarily": flag_temporarily,
#         "flag_const": flag_const,
#         "programmer_mode": programmer_mode,
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
#     programmer: Programmer = Depends(get_programmer),
#     repo: BaseRepository = Depends(get_repository),
# ):
#     sys_settings = await repo.get_settings_db(log_to_api=False)
#     current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

#     is_flag_temporarily = bool(flag_temporarily)
#     is_flag_const = bool(flag_const)

#     c_min = _parse_float(const_min)
#     c_max = _parse_float(const_max)
#     t_temp = _parse_float(temporarily_temp)
#     t_time = temporarily_time.strip() if temporarily_time else ""

#     if is_flag_temporarily:
#         if current_mode in ("PROGRAMMER_CONST", "PROGRAMMER_TEMPORARILY_CONST"):
#             if not t_time or t_time in ("00:00", "0"):
#                 raise HTTPException(
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                     detail="Для временного режима при постоянном базовом режиме время не должно быть нулевым или пустым.",
#                 )

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

#     if t_temp is not None:
#         await programmer.save_programmer_temporarily(
#             temporarily=t_temp,
#             temporarily_time=t_time,
#         )

#     await programmer.update_programmer_mode(
#         flag_temporarily=is_flag_temporarily,
#         flag_const=is_flag_const,
#     )

#     await programmer.evaluate()

#     return RedirectResponse(url="/programmer", status_code=status.HTTP_303_SEE_OTHER)

