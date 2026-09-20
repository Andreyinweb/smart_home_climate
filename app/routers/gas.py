# app/routers/gas.py

import logging
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
import app.db.repository as db
from app.routers.dashboard import get_template_path
from app.services.gas_engine import GasEngine

api_log = logging.getLogger("api_app.routers.gas")
templates = Jinja2Templates(directory="templates")

router = APIRouter(
    tags=["Gas"],
)


@router.get("/gas", response_class=HTMLResponse, summary="Страница ввода показаний газа")
async def get_gas_page(request: Request) -> Any:
    """Страница ввода и просмотра текущих показаний счетчика газа."""
    sys_settings = await db.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)
    price_gas = getattr(sys_settings, "price_gas", 0.0)

    config_start_gas = getattr(settings, "START_OF_MONTH_GAS_METER", getattr(settings, "START_GAS", 0.0))

    latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)

    if not latest_gas:
        gas_display = "Не установлено"
        start_gas_val = config_start_gas
        start_gas_display = f"{start_gas_val:.3f} м³"
        gas_input_val = ""
        start_gas_input_val = f"{start_gas_val:.3f}"
        timestamp_val = "Первое число текущего месяца"
        gas_diff_display = "0.000 м³"
        cost_display = "0.00"
    else:
        gas_val = latest_gas.get("gas_meter")
        start_gas_val = latest_gas.get("start_of_month_gas_meter")
        
        if start_gas_val is None:
            start_gas_val = config_start_gas

        gas_display = f"{gas_val:.3f} м³" if gas_val is not None else "Не установлено"
        start_gas_display = f"{start_gas_val:.3f} м³" if start_gas_val is not None else "0.000 м³"
        gas_input_val = f"{gas_val:.3f}" if gas_val is not None else ""
        start_gas_input_val = f"{start_gas_val:.3f}" if start_gas_val is not None else ""
        timestamp_val = latest_gas.get("timestamp", "—")

        gas_diff = latest_gas.get("gas_difference")
        if gas_diff is None and gas_val is not None and start_gas_val is not None:
            gas_diff = round(gas_val - start_gas_val, 3)

        gas_diff_display = f"{gas_diff:.3f} м³" if gas_diff is not None else "0.000 м³"

        cost_val = latest_gas.get("cost_of_gas")
        if cost_val is None and gas_diff is not None:
            cost_val = round(gas_diff * price_gas, 2)

        cost_display = f"{cost_val:.2f}" if cost_val is not None else "0.00"

    context = {
        "website_return_time": website_return_time,
        "current_gas": gas_display,
        "start_of_month_gas": start_gas_display,
        "gas_input_value": gas_input_val,
        "start_gas_input_value": start_gas_input_val,
        "gas_difference": gas_diff_display,
        "cost_of_gas": cost_display,
        "timestamp": timestamp_val,
    }

    return templates.TemplateResponse(
        request=request, name=get_template_path("gas.html", request), context=context
    )


@router.post("/api/gas/update")
async def update_gas_meter(request: Request):
    """Обновление показаний счетчика газа со полным расчетом всех параметров."""
    form_data = await request.form()
    gas_meter_val = form_data.get("gas_meter")
    
    start_of_month_val = (
        form_data.get("start_of_month_gas_meter") 
        or form_data.get("start_of_month_gas") 
        or form_data.get("start_gas")
    )

    if not gas_meter_val:
        api_log.warning("В запросе отсутствует поле gas_meter")
        return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    try:
        gas_meter = float(gas_meter_val)
    except ValueError:
        api_log.warning("Не удалось преобразовать значение gas_meter в float")
        return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    if not latest_sensor or "id" not in latest_sensor or "timestamp" not in latest_sensor:
        api_log.warning("Таблица table_sensor_data пуста. Запись в gas_table не выполнена.")
        return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    sensor_id = latest_sensor["id"]
    timestamp_str = latest_sensor["timestamp"]

    start_of_month_gas = None
    if start_of_month_val is not None and str(start_of_month_val).strip():
        try:
            start_of_month_gas = float(start_of_month_val)
        except ValueError:
            pass

    latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
    table_start_gas = latest_gas.get("start_of_month_gas_meter") if latest_gas else None

    config_start_gas = getattr(
        settings, "start_of_month_gas_meter", 
        getattr(settings, "START_OF_MONTH_GAS_METER", 0.0)
    )

    if start_of_month_gas is not None:
        start_gas = start_of_month_gas
    elif table_start_gas is not None:
        start_gas = table_start_gas
    else:
        start_gas = config_start_gas

    sys_settings = await db.get_or_create_settings(log_to_api=False)
    price_gas = getattr(sys_settings, "price_gas", 0.0)
    hot_water_per_hour = getattr(sys_settings, "hot_water_per_hour", 0.0)

    target_month = timestamp_str[:7]
    avg_street_temp = await db.get_aggregate("table_sensor_data", "street_temp", function="AVG", interval_type="month", target_time=target_month)
    avg_basement_temp = await db.get_aggregate("table_sensor_data", "basement_temp", function="AVG", interval_type="month", target_time=target_month)

    record_to_write = GasEngine.calculate_full_record(
        record_id=sensor_id,
        timestamp_str=timestamp_str,
        gas_meter=gas_meter,
        start_of_month_gas_meter=start_gas,
        price_gas=price_gas,
        hot_water_per_hour=hot_water_per_hour,
        avg_street_temp=avg_street_temp,
        avg_basement_temp=avg_basement_temp,
    )

    await db.upsert_record("gas_table", record_to_write, pk_col="id", log_to_api=False)
    api_log.info(f"Успешно обновлен и рассчитан счетчик газа: {gas_meter} (id: {sensor_id})")

    return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/gas/table", response_class=HTMLResponse, summary="Таблица данных по газу")
async def get_gas_table_page(request: Request) -> Any:
    """Страница просмотра табличных данных по газу."""
    sys_settings = await db.get_or_create_settings(log_to_api=False)
    website_return_time = getattr(sys_settings, "website_return_time", 60)

    latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
    gas_data = dict(latest_gas) if latest_gas else {}

    context = {
        "website_return_time": website_return_time,
        "gas_data": gas_data,
    }

    return templates.TemplateResponse(
        request=request, name=get_template_path("gas_table.html", request), context=context
    )










 # app/routers/gas.py

# from typing import Any, Dict, Optional
# import logging

# from fastapi import APIRouter, Depends, Request, status
# from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates

# from app.core.config import settings
# import app.db.repository as db
# from app.routers.dashboard import get_template_path
# from app.db.repository import BaseRepository
# from app.services.gas_engine import GasEngine
# # from app.services.graph_service import GraphService

# api_log = logging.getLogger("api_app.routers.gas")
# templates = Jinja2Templates(directory="templates")

# router = APIRouter(
#     tags=["Gas"],
# )


# @router.get("/gas", response_class=HTMLResponse, summary="Страница ввода показаний газа")
# async def get_gas_page(request: Request) -> Any:
#     """Страница ввода и просмотра текущих показаний счетчика газа."""
#     sys_settings = await db.get_or_create_settings(log_to_api=False)
#     website_return_time = getattr(sys_settings, "website_return_time", 60)
#     price_gas = getattr(sys_settings, "price_gas", 0.0)

#     # Запасное значение на начало месяца из файла системной конфигурации app/core/config.py
#     config_start_gas = getattr(settings, "START_OF_MONTH_GAS_METER", getattr(settings, "START_GAS", 0.0))

#     latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)

#     if not latest_gas:
#         gas_display = "Не установлено"
#         start_gas_val = config_start_gas
#         start_gas_display = f"{start_gas_val:.3f} м³"
#         gas_input_val = ""
#         start_gas_input_val = f"{start_gas_val:.3f}"
#         timestamp_val = "Первое число текущего месяца"
#         gas_diff_display = "0.000 м³"
#         cost_display = "0.00"
#     else:
#         gas_val = latest_gas.get("gas_meter")
#         start_gas_val = latest_gas.get("start_of_month_gas_meter")
        
#         # Если данных на начало месяца нет в БД, подтягиваем из конфига
#         if start_gas_val is None:
#             start_gas_val = config_start_gas

#         gas_display = f"{gas_val:.3f} м³" if gas_val is not None else "Не установлено"
#         start_gas_display = f"{start_gas_val:.3f} м³" if start_gas_val is not None else "0.000 м³"
#         gas_input_val = f"{gas_val:.3f}" if gas_val is not None else ""
#         start_gas_input_val = f"{start_gas_val:.3f}" if start_gas_val is not None else ""
#         timestamp_val = latest_gas.get("timestamp", "—")

#         gas_diff = latest_gas.get("gas_difference")
#         if gas_diff is None and gas_val is not None and start_gas_val is not None:
#             gas_diff = round(gas_val - start_gas_val, 3)

#         gas_diff_display = f"{gas_diff:.3f} м³" if gas_diff is not None else "0.000 м³"

#         cost_val = latest_gas.get("cost_of_gas")
#         if cost_val is None and gas_diff is not None:
#             cost_val = round(gas_diff * price_gas, 2)

#         cost_display = f"{cost_val:.2f}" if cost_val is not None else "0.00"

#     context = {
#         "website_return_time": website_return_time,
#         "current_gas": gas_display,
#         "start_of_month_gas": start_gas_display,
#         "gas_input_value": gas_input_val,
#         "start_gas_input_value": start_gas_input_val,
#         "gas_difference": gas_diff_display,
#         "cost_of_gas": cost_display,
#         "timestamp": timestamp_val,
#     }

#     return templates.TemplateResponse(
#         request=request, name=get_template_path("gas.html", request), context=context
#     )

# @router.post("/api/gas/update")
# async def update_gas_meter(request: Request):
#     """Обновление показаний счетчика газа."""
#     form_data = await request.form()
#     gas_meter_val = form_data.get("gas_meter")
    
#     # Извлечение начального значения с поддержкой возможных имён полей формы
#     start_of_month_val = (
#         form_data.get("start_of_month_gas_meter") 
#         or form_data.get("start_of_month_gas") 
#         or form_data.get("start_gas")
#     )

#     if not gas_meter_val:
#         api_log.warning("В запросе отсутствует поле gas_meter")
#         return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

#     try:
#         gas_meter = float(gas_meter_val)
#     except ValueError:
#         api_log.warning("Не удалось преобразовать значение gas_meter в float")
#         return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

#     # 1. Проверка наличия записей в table_sensor_data. 
#     # Если таблица пуста — отменяем запись в gas_table.
#     latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#     if not latest_sensor or "id" not in latest_sensor or "timestamp" not in latest_sensor:
#         api_log.warning("Таблица table_sensor_data пуста. Запись в gas_table не выполнена.")
#         return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

#     sensor_id = latest_sensor["id"]
#     timestamp_str = latest_sensor["timestamp"]

#     # 2. Обработка значения показания на начало месяца
#     start_of_month_gas = None
#     if start_of_month_val is not None and str(start_of_month_val).strip():
#         try:
#             start_of_month_gas = float(start_of_month_val)
#         except ValueError:
#             pass

#     latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
#     table_start_gas = latest_gas.get("start_of_month_gas_meter") if latest_gas else None

#     # Чтение значения по умолчанию из конфигурации (учитываются регистры Pydantic Settings)
#     config_start_gas = getattr(
#         settings, "start_of_month_gas_meter", 
#         getattr(settings, "START_OF_MONTH_GAS_METER", 0.0)
#     )

#     # Приоритет: Переданное значение из формы -> Последнее значение из gas_table -> Конфиг
#     if start_of_month_gas is not None:
#         start_gas = start_of_month_gas
#     elif table_start_gas is not None:
#         start_gas = table_start_gas
#     else:
#         start_gas = config_start_gas

#     sys_settings = await db.get_or_create_settings(log_to_api=False)
#     price_gas = getattr(sys_settings, "price_gas", 0.0)

#     gas_diff = round(gas_meter - start_gas, 3)
#     cost_val = round(gas_diff * price_gas, 2)

#     # Гарантированная привязка id и timestamp к table_sensor_data
#     record_to_write = {
#         "id": sensor_id,
#         "timestamp": timestamp_str,
#         "gas_meter": gas_meter,
#         "start_of_month_gas_meter": start_gas,
#         "gas_difference": gas_diff,
#         "cost_of_gas": cost_val,
#         "price_gas": price_gas,
#     }

#     await db.upsert_record("gas_table", record_to_write, pk_col="id", log_to_api=False)
#     api_log.info(f"Успешно обновлен счетчик газа: {gas_meter} (id: {sensor_id}, start_gas: {start_gas})")

#     return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

# @router.get("/gas/table", response_class=HTMLResponse, summary="Таблица данных по газу")
# async def get_gas_table_page(request: Request) -> Any:
#     """Страница просмотра табличных данных по газу."""
#     sys_settings = await db.get_or_create_settings(log_to_api=False)
#     website_return_time = getattr(sys_settings, "website_return_time", 60)

#     latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
#     gas_data = dict(latest_gas) if latest_gas else {}

#     context = {
#         "website_return_time": website_return_time,
#         "gas_data": gas_data,
#     }

#     return templates.TemplateResponse(
#         request=request, name=get_template_path("gas_table.html", request), context=context
#     )