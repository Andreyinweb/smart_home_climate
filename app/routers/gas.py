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
    """Обновление показаний счетчика газа со строгой валидацией и каскадным пересчетом за месяц."""
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
    target_month = timestamp_str[:7]

    # 1. Валидация текущих показаний: gas_meter >= последнего записанного gas_meter
    latest_gas = await db.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
    if latest_gas and latest_gas.get("gas_meter") is not None:
        last_gas_meter = latest_gas["gas_meter"]
        if gas_meter < last_gas_meter:
            api_log.warning(
                f"Отмена записи: введенное значение gas_meter ({gas_meter}) "
                f"меньше последнего записанного ({last_gas_meter})"
            )
            return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    # 2. Выборка всех записей текущего месяца для проверки и массового пересчета
    records_this_month = await db.fetch_by_date(
        "gas_table", target_date=target_month, interval_type="month", order_asc=True, log_to_api=False
    )

    # 3. Определение показания на начало месяца
    start_of_month_gas = None
    if start_of_month_val is not None and str(start_of_month_val).strip():
        try:
            start_of_month_gas = float(start_of_month_val)
        except ValueError:
            pass

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

    # 4. Валидация значения на начало месяца: start_gas <= первого показания gas_meter в этом месяце
    if records_this_month:
        first_record_month = records_this_month[0]
        first_gas_meter = first_record_month.get("gas_meter")
        if first_gas_meter is not None and start_gas > first_gas_meter:
            api_log.warning(
                f"Отмена записи: значение на начало месяца ({start_gas}) "
                f"превышает первое записанное показание месяца ({first_gas_meter})"
            )
            return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    sys_settings = await db.get_or_create_settings(log_to_api=False)
    price_gas = getattr(sys_settings, "price_gas", 0.0)
    hot_water_per_hour = getattr(sys_settings, "hot_water_per_hour", 0.0)

    # 5. Каскадное обновление всех предыдущих строк месяца при изменении start_of_month_gas
    if start_of_month_gas is not None and records_this_month:
        for rec in records_this_month:
            rec_id = rec["id"]
            rec_ts = rec["timestamp"]
            rec_gas_meter = rec.get("gas_meter", 0.0)
            rec_month = rec_ts[:7]

            rec_avg_street = await db.get_aggregate(
                "table_sensor_data", "street_temp", function="AVG", interval_type="month", target_time=rec_month
            )
            rec_avg_basement = await db.get_aggregate(
                "table_sensor_data", "basement_temp", function="AVG", interval_type="month", target_time=rec_month
            )

            updated_rec = GasEngine.calculate_full_record(
                record_id=rec_id,
                timestamp_str=rec_ts,
                gas_meter=rec_gas_meter,
                start_of_month_gas_meter=start_gas,
                price_gas=price_gas,
                hot_water_per_hour=hot_water_per_hour,
                avg_street_temp=rec_avg_street,
                avg_basement_temp=rec_avg_basement,
            )
            await db.upsert_record("gas_table", updated_rec, pk_col="id", log_to_api=False)

    # 6. Расчет и сохранение текущей новой записи
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