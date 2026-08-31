import logging
import os
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import operations
from models import get_db_connection, get_latest_climate_data, write_climate_data, get_interval_average
from settings import config

api_log = logging.getLogger("api_app.api")
work_log = logging.getLogger("climat_app.api")
api_log.info("-" * 97)

app = FastAPI(title="Smart Home Climate API")
data_rendered = {}

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(config.PROJECT_DIR, "static")),
    name="static",
)
templates = Jinja2Templates(
    directory=os.path.join(config.PROJECT_DIR, "templates")
)

def safe_diff(val1, val2) -> float:
    """Безопасное вычисление разницы между двумя числовыми значениями."""
    if val1 is not None and val2 is not None:
        return float(val1) - float(val2)
    return 0.0

def get_no_data_response(request: Request) -> HTMLResponse:
    """Возвращает страницу ожидания данных, если в БД пусто."""
    WEBSITE_RETURN_TIME = operations.settings_in_db()[3]
    html_path = os.path.join(config.PROJECT_DIR, "templates", "no_data.html")

    if os.path.exists(html_path):
        return templates.TemplateResponse(
            request=request,
            name="no_data.html",
            context={"website_return_time": WEBSITE_RETURN_TIME},
            status_code=503,
        )

    return HTMLResponse(
        "<h1 style='font-family:sans-serif; text-align:center; margin-top:50px; color:#ef4444;'>"
        "Ошибка: База данных пуста, и шаблон no_data.html не найден в папке templates.</h1>",
        status_code=500,
    )

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Сборка дашборда на основе данных из БД и Jinja2 шаблона."""
    # Загрузка переменных из базы данных
    (DATE_SETINGS, MODE, INTERVAL_SECONDS, WEBSITE_RETURN_TIME,
    MAX_RETRIES, T_FLOOR_MAC_DIFF, ABSOLUTE_HUMIDITY_TOLERANCE, 
    MINIMUM_HUMIDITY, TARGET_RH, DANGEROUS_HUMIDITY, PRICE_GAS,HOT_WATER_PER_HOUR) = operations.settings_in_db()

    latest_records_api = get_latest_climate_data("api_table")
    latest_records_sensor = get_latest_climate_data("table_sensor_data")

    if not latest_records_api or not latest_records_sensor:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
    
    del latest_records_api[0]["timestamp"]
    db_data = latest_records_sensor[0] | latest_records_api[0]

    # --- Обработка статусов и описания проветривания ---
    if db_data.get("vent_status") and db_data.get("vent_time_val"):
        db_data["msg_vent_status"] = "ДА"
        db_data["vent_reason"] = f"Время: {db_data['vent_time_val']} мин."
    elif not db_data.get("vent_status"):
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "dАВ < 0.5"
    else:
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "Тяги нет."

    if db_data.get("vent_status"):
        db_data["vent_class"] = "badge-green"
        db_data["vent_display_class"] = ""
    else:
        db_data["vent_class"] = "badge-red"
        db_data["vent_display_class"] = "d-none"
    

    # --- Обработка статусов и описания отопления ---
    heating_delta = db_data.get("heating_delta", 0.0)
    if db_data.get("heat_status"):
        db_data["msg_heat_status"] = "ДА"
        db_data["heat_info"] = f"+{heating_delta} °C"
        db_data["heat_class"] = "badge-amber"
        db_data["heat_display_class"] = ""
    else:
        db_data["msg_heat_status"] = "НЕТ"
        db_data["heat_info"] = ""
        db_data["heat_class"] = "badge-gray" 
        db_data["heat_display_class"] = "d-none"  

    # --- Определение текущего активного режима ---
    active_modes = []

    # Проверка проветривания
    latest_vent = get_latest_climate_data("ventilation_table")
    if latest_vent and latest_vent[0].get("status_ventilation"):
        active_modes.append("Проветривание")

    # Проверка отопления 
    latest_heat = get_latest_climate_data("heating_table")
    if latest_heat and latest_heat[0]["status_heating"]:
        active_modes.append("Отопление")

    db_data["active_mode"] = ", ".join(active_modes) if active_modes else ""

    # Принудительно показывает таблицы проветривания и отопления на главной странице, даже если они неактивны
    # db_data["vent_display_class"] = "" # TODO Удали
    # db_data["heat_display_class"] = ""# TODO Удали

    context = {
        "website_return_time": WEBSITE_RETURN_TIME,
        "max_rh": TARGET_RH,
        **db_data,
    }

    return templates.TemplateResponse(
        request=request, name="index.html", context=context
    )

@app.get("/ventilation", response_class=HTMLResponse)
async def get_ventilation_page(request: Request):
    """Страница ручного управления проветриванием и сравнительной таблицы."""
    WEBSITE_RETURN_TIME = operations.settings_in_db()[3]
    latest_records_api = get_latest_climate_data("api_table")
    latest_records_sensor = get_latest_climate_data("table_sensor_data")

    if not latest_records_api or not latest_records_sensor:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
    del latest_records_api[0]["timestamp"]
    db_data = latest_records_sensor[0] | latest_records_api[0]
    latest_ventilation_table = get_latest_climate_data("ventilation_table")

    if latest_ventilation_table and latest_ventilation_table[0].get(
        "status_ventilation"
    ):
        status_ventilation_table = latest_ventilation_table[0]
        vent_start_id = status_ventilation_table.get("ventilation_start")
        before_records = (
            get_latest_climate_data("api_table", vent_start_id, vent_start_id)[0] | 
            get_latest_climate_data("table_sensor_data", vent_start_id, vent_start_id)[0]
            if vent_start_id
            else []
        )
        vent_before = before_records if before_records else dict(db_data)
        vent_active = True
        vent_start_time = vent_before.get(
            "timestamp", db_data.get("timestamp", "—")
        )
        vent_now_time = db_data.get("timestamp", "—")
        vent_difference_time = operations.get_time_difference_str(vent_start_time[11:16], vent_now_time[11:16])
    else:
        vent_active = False
        vent_before = dict(db_data)
        vent_start_time = db_data.get("timestamp", "—")
        vent_now_time = db_data.get("timestamp", "—")
        vent_difference_time = operations.get_time_difference_str(vent_start_time[11:16], vent_now_time[11:16])

    diffs = {
        "diff_basement_temp": safe_diff(
            db_data.get("basement_temp"), vent_before.get("basement_temp")
        ),
        "diff_basement_humi": safe_diff(
            db_data.get("basement_humi"), vent_before.get("basement_humi")
        ),
        "diff_a_basement_humi": safe_diff(
            db_data.get("a_basement_humi"), vent_before.get("a_basement_humi")
        ),
        "diff_floor_temp": safe_diff(
            db_data.get("floor_temp"), vent_before.get("floor_temp")
        ),
        "diff_floor_humi": safe_diff(
            db_data.get("floor_humi"), vent_before.get("floor_humi")
        ),
        "diff_a_floor_humi": safe_diff(
            db_data.get("a_floor_humi"), vent_before.get("a_floor_humi")
        ),
    }

    style_classes = {
        "diff_basement_temp_class": (
            "text-blue"
            if abs(diffs["diff_basement_temp"]) > 0.1
            else "text-gray"
        ),
        "diff_basement_humi_class": (
            "text-green"
            if diffs["diff_basement_humi"] < -0.5
            else "text-red"
            if diffs["diff_basement_humi"] > 0.5
            else "text-gray"
        ),
        "diff_a_basement_humi_class": (
            "text-green"
            if diffs["diff_a_basement_humi"] < -0.1
            else "text-red"
            if diffs["diff_a_basement_humi"] > 0.1
            else "text-gray"
        ),
        "diff_floor_temp_class": (
            "text-blue" if abs(diffs["diff_floor_temp"]) > 0.1 else "text-gray"
        ),
        "diff_floor_humi_class": (
            "text-green"
            if diffs["diff_floor_humi"] < -0.5
            else "text-red"
            if diffs["diff_floor_humi"] > 0.5
            else "text-gray"
        ),
        "diff_a_floor_humi_class": (
            "text-green"
            if diffs["diff_a_floor_humi"] < -0.1
            else "text-red"
            if diffs["diff_a_floor_humi"] > 0.1
            else "text-gray"
        ),
    }

    if vent_active:
        btn_start_class = "btn-disabled"
        btn_stop_class = "btn-stop"
        btn_start_disabled = "disabled"
        btn_stop_disabled = ""
    else:
        btn_start_class = "btn-start"
        btn_stop_class = "btn-disabled"
        btn_start_disabled = ""
        btn_stop_disabled = "disabled"

    before_data = {f"before_{k}": v for k, v in vent_before.items()}

    vent_start_str = (
        vent_start_time[11:16]
        if len(str(vent_start_time)) >= 16
        else str(vent_start_time)
    )
    vent_now_str = (
        vent_now_time[11:16]
        if len(str(vent_now_time)) >= 16
        else str(vent_now_time)
    )

    context = {
        "website_return_time": WEBSITE_RETURN_TIME,
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
        request=request, name="ventilation.html", context=context
    )

@app.post("/api/ventilation/start")
async def start_ventilation():
    """Запись старта проветривания в БД с привязкой ID и timestamp из api_table."""
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data("ventilation_table")

    can_start = True
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table.get("status_ventilation"):
            can_start = False

    if can_start:
        latest_records_api = get_latest_climate_data("api_table")
        latest_records_sensor = get_latest_climate_data("table_sensor_data")
        if latest_records_api and latest_records_sensor:
            del latest_records_api[0]["timestamp"]
            latest_records = latest_records_sensor[0] | latest_records_api[0]
            api_on_db["status_ventilation"] = True
            api_on_db["timestamp"] = latest_records["timestamp"]
            api_on_db["ventilation_start"] = latest_records["id"]
            api_on_db["stop_ventilation"] = 0
            write_climate_data("ventilation_table", api_on_db)
            api_log.info(
                f"[БД] Успешный старт проветривания: "
                f"api_id={api_on_db['ventilation_start']}, timestamp={api_on_db['timestamp']}"
            )
        else:
            api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/ventilation", status_code=303)

@app.post("/api/ventilation/stop")
async def stop_ventilation():
    """Запись остановки проветривания в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data("ventilation_table")

    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table.get("status_ventilation"):
            latest_records = get_latest_climate_data("api_table")
            if latest_records:
                api_on_db["timestamp"] = status_ventilation_table.get(
                    "timestamp"
                )
                api_on_db["status_ventilation"] = False
                api_on_db["ventilation_start"] = status_ventilation_table.get(
                    "ventilation_start"
                )
                api_on_db["stop_ventilation"] = latest_records[0]["id"]
                write_climate_data(
                    "ventilation_table",
                    api_on_db,
                    row_id=status_ventilation_table.get("id"),
                )
                api_log.info(
                    f"[БД] Успешный стоп проветривания: api_id={api_on_db['stop_ventilation']}"
                )
            else:
                api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/ventilation", status_code=303)

@app.get("/heating", response_class=HTMLResponse)
async def get_heating_page(request: Request):
    """Страница ручного управления отоплением и сравнительной таблицы."""
    WEBSITE_RETURN_TIME = operations.settings_in_db()[3]
    latest_records_api = get_latest_climate_data("api_table")
    latest_records_sensor = get_latest_climate_data("table_sensor_data")

    if not latest_records_api or not latest_records_sensor:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
    del latest_records_api[0]["timestamp"]
    db_data = latest_records_sensor[0] | latest_records_api[0]
    latest_heating_table = get_latest_climate_data("heating_table")

    if latest_heating_table and latest_heating_table[0].get("stop_heating") == 0:
        status_heating_table = latest_heating_table[0]
        heat_start_id = status_heating_table.get("heating_start")
        before_records = (
            get_latest_climate_data("api_table", heat_start_id, heat_start_id)[0] |
            get_latest_climate_data("table_sensor_data", heat_start_id, heat_start_id)[0]
            if heat_start_id
            else []
        )
        heat_before = before_records if before_records else dict(db_data)
        heat_active = True
        heat_start_time = heat_before.get(
            "timestamp", db_data.get("timestamp", "—")
        )
        heat_now_time = db_data.get("timestamp", "—")
        heat_difference_time = operations.get_time_difference_str(heat_start_time[11:16], heat_now_time[11:16])
    else:
        heat_active = False
        heat_before = dict(db_data)
        heat_start_time = db_data.get("timestamp", "—")
        heat_now_time = db_data.get("timestamp", "—")
        heat_difference_time = operations.get_time_difference_str(heat_start_time[11:16], heat_now_time[11:16])

    diffs = {
        "diff_basement_temp": safe_diff(
            db_data.get("basement_temp"), heat_before.get("basement_temp")
        ),
        "diff_basement_humi": safe_diff(
            db_data.get("basement_humi"), heat_before.get("basement_humi")
        ),
        "diff_floor_temp": safe_diff(
            db_data.get("floor_temp"), heat_before.get("floor_temp")
        ),
        "diff_floor_humi": safe_diff(
            db_data.get("floor_humi"), heat_before.get("floor_humi")
        ),
    }

    style_classes = {
        "diff_basement_temp_class": (
            "text-green"
            if diffs["diff_basement_temp"] > 0.1
            else "text-red"
            if diffs["diff_basement_temp"] < -0.1
            else "text-gray"
        ),
        "diff_basement_humi_class": (
            "text-green"
            if diffs["diff_basement_humi"] < -0.5
            else "text-red"
            if diffs["diff_basement_humi"] > 0.5
            else "text-gray"
        ),
        "diff_floor_temp_class": (
            "text-green"
            if diffs["diff_floor_temp"] > 0.1
            else "text-red"
            if diffs["diff_floor_temp"] < -0.1
            else "text-gray"
        ),
        "diff_floor_humi_class": (
            "text-green"
            if diffs["diff_floor_humi"] < -0.5
            else "text-red"
            if diffs["diff_floor_humi"] > 0.5
            else "text-gray"
        ),
    }

    if heat_active:
        btn_start_class = "btn-disabled"
        btn_stop_class = "btn-stop"
        btn_start_disabled = "disabled"
        btn_stop_disabled = ""
    else:
        btn_start_class = "btn-start"
        btn_stop_class = "btn-disabled"
        btn_start_disabled = ""
        btn_stop_disabled = "disabled"

    before_data = {f"before_{k}": v for k, v in heat_before.items()}

    heat_start_str = (
        heat_start_time[11:16]
        if len(str(heat_start_time)) >= 16
        else str(heat_start_time)
    )
    heat_now_str = (
        heat_now_time[11:16]
        if len(str(heat_now_time)) >= 16
        else str(heat_now_time)
    )

    context = {
        "website_return_time": WEBSITE_RETURN_TIME,
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
        request=request, name="heating.html", context=context
    )

@app.post("/api/heating/start")
async def start_heating():
    """Запись старта отопления в БД с привязкой ID и timestamp из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data("heating_table")

    can_start = True
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table["status_heating"]:
            can_start = False

    if can_start:
        latest_records = get_latest_climate_data("api_table")
        if latest_records:
            api_on_db["timestamp"] = latest_records[0]["timestamp"]
            api_on_db["status_heating"] = True
            api_on_db["heating_start"] = latest_records[0]["id"]
            api_on_db["stop_heating"] = 0
            write_climate_data("heating_table", api_on_db)
            api_log.info(
                f"[БД] Успешный старт отопления: "
                f"api_id={api_on_db['heating_start']}, timestamp={api_on_db['timestamp']}"
            )
        else:
            api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/heating", status_code=303)

@app.post("/api/heating/stop")
async def stop_heating():
    """Запись остановки отопления в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data("heating_table")
    
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table["status_heating"]:
            latest_records = get_latest_climate_data("api_table")
            if latest_records:
                api_on_db["timestamp"] = status_heating_table["timestamp"]
                api_on_db["status_heating"] = False
                api_on_db["heating_start"] = status_heating_table["heating_start"]
                api_on_db["stop_heating"] = latest_records[0]["id"]
                write_climate_data(
                    "heating_table",
                    api_on_db,
                    row_id=status_heating_table.get("id"),
                )
                api_log.info(
                    f"[БД] Успешный стоп отопления: api_id={api_on_db['stop_heating']}"
                )
            else:
                api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/heating", status_code=303)


@app.get("/gas", response_class=HTMLResponse)
async def get_gas_page(request: Request):
    """Страница ввода и отображения показаний счетчика газа."""
    WEBSITE_RETURN_TIME = operations.settings_in_db()[3]
    latest_records = get_latest_climate_data("gas_table")

    if not latest_records:
        gas_val = None
        start_gas_val = config.START_OF_MONTH_GAS_METER
        gas_display = "Не установлено"
        start_gas_display = f"{start_gas_val:.3f} м³" if start_gas_val is not None else "0.000 м³"
        gas_input_val = ""
        start_gas_input_val = f"{start_gas_val:.3f}" if start_gas_val is not None else ""
        timestamp_val = "Первое число текущего месяца"
        gas_diff_display = "0.000 м³"
        cost_display = "0.00"
    else:
        db_data = latest_records[0]
        gas_val = db_data.get("gas_meter")
        start_gas_val = db_data.get("start_of_month_gas_meter")
        
        if start_gas_val is None:
            start_gas_val = config.START_OF_MONTH_GAS_METER

        gas_display = f"{gas_val:.3f} м³" if gas_val is not None else "Не установлено"
        start_gas_display = f"{start_gas_val:.3f} м³" if start_gas_val is not None else "0.000 м³"
        
        gas_input_val = f"{gas_val:.3f}" if gas_val is not None else ""
        start_gas_input_val = f"{start_gas_val:.3f}" if start_gas_val is not None else ""
        timestamp_val = db_data.get("timestamp", "—")

        # Расчет или получение разницы с начала месяца
        gas_diff = db_data.get("gas_difference")
        if gas_diff is None and gas_val is not None and start_gas_val is not None:
            gas_diff = round(gas_val - start_gas_val, 3)
        
        gas_diff_display = f"{gas_diff:.3f} м³" if gas_diff is not None else "0.000 м³"

        # Расчет или получение стоимости на данный момент
        cost_val = db_data.get("cost_of_gas")
        if cost_val is None and gas_diff is not None:
            try:
                price_gas = operations.settings_in_db()[10]
                cost_val = round(gas_diff * price_gas, 2)
            except Exception:
                cost_val = 0.0

        cost_display = f"{cost_val:.2f}" if cost_val is not None else "0.00"

    context = {
        "website_return_time": WEBSITE_RETURN_TIME,
        "current_gas": gas_display,
        "start_of_month_gas": start_gas_display,
        "gas_input_value": gas_input_val,
        "start_gas_input_value": start_gas_input_val,
        "gas_difference": gas_diff_display,
        "cost_of_gas": cost_display,
        "timestamp": timestamp_val
    }

    return templates.TemplateResponse(
        request=request, name="gas.html", context=context
    )


@app.post("/api/gas/update")
async def update_gas_meter(request: Request):
    """Обновление показаний счетчика газа в таблицах api_table и table_sensor_data."""
    body = await request.body()
    parsed_data = parse_qs(body.decode("utf-8"))
    
    gas_meter_val = parsed_data.get("gas_meter")
    start_of_month_val = parsed_data.get("start_of_month_gas_meter")

    if not gas_meter_val:
        api_log.warning("В запросе отсутствует поле gas_meter")
        return RedirectResponse(url="/gas", status_code=303)

    try:
        gas_meter = float(gas_meter_val[0])
    except ValueError:
        api_log.warning(
            "Не удалось преобразовать значение gas_meter в число с плавающей точкой"
        )
        return RedirectResponse(url="/gas", status_code=303)
    
    # Обновление показаний счетчика газа в таблице gas_table
    if gas_meter:
        gas_out_db = operations.calc_gas_meter(gas_meter)
        # Записываем в БД, если изменилось текущее значение, значение начала месяца или id записи
        if gas_out_db:
            write_climate_data("gas_table", gas_out_db, row_id=gas_out_db["id"])
            api_log.info(f"Успешно обновлен счетчик газа в gas_table (id={gas_out_db["id"]}): {gas_meter}")

    # Обработка введенного показания на начало месяца (если указано)
    start_of_month_gas = None
    if start_of_month_val and start_of_month_val[0].strip():
        try:
            start_of_month_gas = float(start_of_month_val[0])
        except ValueError:
            api_log.warning(
                "Не удалось преобразовать значение start_of_month_gas_meter в число"
            )
        if start_of_month_gas:
            db_month_gas = operations.calc_of_month_gas(start_of_month_gas)
            if db_month_gas:
                api_log.info(f"Успешно обновлен счетчик газа на начало месяца: {start_of_month_gas}")
            else:
                api_log.warning(f"Не удалось обновит счетчик газа на начало месяца: {start_of_month_gas}")

    return RedirectResponse(url="/gas", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    """Страница просмотра и редактирования настроек программы."""
    latest_settings = get_latest_climate_data("settings_table")

    if not latest_settings:
        settings_dict = {
            "mode": config.MODE,
            "interval_seconds": config.INTERVAL_SECONDS,
            "max_retries": config.MAX_RETRIES,
            "website_return_time": config.WEBSITE_RETURN_TIME,
            "t_floor_mac_diff": config.T_FLOOR_MAC_DIFF,
            "absolute_humidity_tolerance": config.ABSOLUTE_HUMIDITY_TOLERANCE,
            "minimum_humidity": config.MINIMUM_HUMIDITY,
            "target_rh": config.TARGET_RH,
            "dangerous_humidity": config.DANGEROUS_HUMIDITY,
            "price_gas": config.PRICE_GAS,
            "hot_water_per_hour": config.HOT_WATER_PER_HOUR,
        }
    else:
        settings_dict = latest_settings[0]

    latest_sensor = get_latest_climate_data("table_sensor_data")
    average_temp = "—"
    if latest_sensor and latest_sensor[0].get("average_temp") is not None:
        average_temp = latest_sensor[0]["average_temp"]

    context = {
        "website_return_time": settings_dict.get(
            "website_return_time", config.WEBSITE_RETURN_TIME
        ),
        "average_temp": average_temp,
        **settings_dict,
    }

    return templates.TemplateResponse(
        request=request, name="settings.html", context=context
    )


@app.post("/api/settings/update")
async def update_settings(request: Request):
    """Обновление настроек в таблице settings_table."""
    body = await request.body()
    parsed_data = parse_qs(body.decode("utf-8"))

    def parse_field(key, default, type_func):
        val_list = parsed_data.get(key)
        if val_list and val_list[0]:
            try:
                return type_func(val_list[0])
            except ValueError:
                pass
        return default
    latest_sensor = get_latest_climate_data("table_sensor_data")
    if latest_sensor:
        last_sensor_timestamp = latest_sensor[0]["timestamp"]
    else:
        last_sensor_timestamp = "—"
    settings_to_write = {
        "timestamp": last_sensor_timestamp,
        "mode": parse_field("mode", config.MODE, str),
        "interval_seconds": parse_field(
            "interval_seconds", config.INTERVAL_SECONDS, int
        ),
        "max_retries": parse_field("max_retries", config.MAX_RETRIES, int),
        "website_return_time": parse_field(
            "website_return_time", config.WEBSITE_RETURN_TIME, int
        ),
        "t_floor_mac_diff": parse_field(
            "t_floor_mac_diff", config.T_FLOOR_MAC_DIFF, float
        ),
        "absolute_humidity_tolerance": parse_field(
            "absolute_humidity_tolerance",
            config.ABSOLUTE_HUMIDITY_TOLERANCE,
            float,
        ),
        "minimum_humidity": parse_field(
            "minimum_humidity", config.MINIMUM_HUMIDITY, float
        ),
        "target_rh": parse_field("target_rh", config.TARGET_RH, float),
        "dangerous_humidity": parse_field(
            "dangerous_humidity", config.DANGEROUS_HUMIDITY, float
        ),
        "price_gas": parse_field("price_gas", config.PRICE_GAS, float),
        "hot_water_per_hour": parse_field("hot_water_per_hour", config.HOT_WATER_PER_HOUR, float),
    }

    success = write_climate_data("settings_table", settings_to_write, row_id=1)
    if success:
        api_log.info(
            f"[БД] Настройки успешно обновлены в settings_table: {settings_to_write}"
        )
    else:
        api_log.error("[БД] Ошибка при записи новых настроек в settings_table")

    return RedirectResponse(url="/settings", status_code=303)
