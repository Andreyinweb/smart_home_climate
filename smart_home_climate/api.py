#  python3 api.py  # Сервер 

import os
import math
import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from settings import config
import operations
from models import get_latest_climate_data

# Логирование
api_log = logging.getLogger("api_app.api")
api_log.info(f"Сервер запускается, перезагрузка = {config.WEBSITE_RETURN_TIME} с.")

app = FastAPI(title="Smart Home Climate API")

def calculate_dew_point(temp: float, humi: float) -> float:
    """Расчет точки росы (°C) по формуле Магнуса."""
    if temp is None or humi is None or humi == 0:
        return 0.0
    a = 17.27
    b = 237.7
    alpha = ((a * temp) / (b + temp)) + math.log(humi / 100.0)
    dp = (b * alpha) / (a - alpha)
    return round(dp, 2)

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return shared_data

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
    # Получаем последнюю запись из базы данных
    latest_records = get_latest_climate_data(limit=1)
    
    if latest_records:
        db_data = latest_records[0]
        db_date = db_data["Date"]
    else:
        None

    # Расчет абсолютных влажностей
    for name in config.NAME_SENSOR:
        db_data["a_" + name[:-4].lower() + "_humi"] = operations.calculate_absolute_humidity(db_data[name[:-4].lower() + "_temp"], db_data[name[:-4].lower() + "_humi"])
        # Расчет точек росы
        db_data["dp_" + name[:-4].lower()] = operations.calculate_absolute_humidity(db_data[name[:-4].lower() + "_temp"], db_data[name[:-4].lower() + "_humi"])

    # Расчет проветривания с учетом абсолютной погрешности ABSOLUTE_HUMIDITY_TOLERANCE (0.5 г/м³)
    humidity_difference = round(db_data["a_basement_humi"] - db_data["a_street_humi"], 2)
    is_safe_ventilation = humidity_difference > config.ABSOLUTE_HUMIDITY_TOLERANCE
    has_draft = db_data["basement_temp"] > db_data["street_temp"]

    if is_safe_ventilation and has_draft:
        vent_status = "ДА"
        try:
            vent_time_val = round(10.4 / math.sqrt(db_data["basement_temp"] - db_data["street_temp"]))
            vent_reason = f"Время: {vent_time_val} мин."
        except (ZeroDivisionError, ValueError):
            vent_reason = "Время рассчитать не удалось."
    elif not is_safe_ventilation:
        vent_status = "НЕТ"
        vent_reason = "dАВ < 0.5"
    else:
        vent_status = "НЕТ"
        vent_reason = "Тяги нет."

    vent_class = "bg-green-100 text-green-800" if vent_status == "ДА" else "bg-red-100 text-red-800"

    # Моделирование замещения (Проветривание)
    sim_abasement_humi = db_data["a_street_humi"]
    sim_basement_humi = operations.calculate_relative_humidity(db_data["basement_temp"], sim_abasement_humi)
    sim_floor_humi = operations.calculate_relative_humidity(db_data["floor_temp"], sim_abasement_humi)

    # Расчет компенсационного нагрева (Отопление)
    heating_needed = db_data["street_humi"]> config.TARGET_RH
    heating_delta = 0.0

    if heating_needed:
        for delta in [x * 0.1 for x in range(1, 150)]:
            sim_floor_temp_heated = db_data["street_humi"] + delta
            rh_at_heated_floor = operations.calculate_relative_humidity(sim_floor_temp_heated, db_data["a_basement_humi"])
            if rh_at_heated_floor <= config.TARGET_RH:
                heating_delta = round(delta, 1)
                break

    heat_status = "ДА" if heating_needed else "НЕТ"
    heat_info = f"+{heating_delta} °C" if heating_needed else ""
    heat_class = "bg-amber-100 text-amber-800" if heating_needed else "bg-gray-100 text-gray-700"

    # Итоговые параметры после догрева
    if heating_needed:
        basement_temp_heated = round(db_data["basement_temp"] + heating_delta, 1)
        basement_humi_heated = operations.calculate_relative_humidity(basement_temp_heated, db_data["a_basement_humi"])
        floor_temp_heated = round(db_data["floor_temp"] + heating_delta, 1)
        floor_humi_heated = operations.calculate_relative_humidity(floor_temp_heated, db_data["a_basement_humi"])
    else:
        basement_temp_heated = db_data["basement_temp"]
        basement_humi_heated = db_data["basement_humi"]
        floor_temp_heated = db_data["floor_temp"]
        floor_humi_heated = db_data["floor_humi"]

    # Чтение шаблона разметки
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)
    
    data_rendered = db_data | {
        "vent_status":vent_status,
        "vent_reason":vent_reason,
        "vent_class":vent_class,
        "humidity_difference":humidity_difference,
        "sim_basement_humi":sim_basement_humi,
        "sim_floor_humi":sim_floor_humi,
        "sim_abasement_humi":sim_abasement_humi,
        "heat_status":heat_status,
        "heat_info":heat_info,
        "heat_class":heat_class,
        "basement_temp_heated":basement_temp_heated,
        "basement_humi_heated":basement_humi_heated,
        "floor_temp_heated":floor_temp_heated,
        "floor_humi_heated":floor_humi_heated,
        "website_return_time":config.WEBSITE_RETURN_TIME,
        "db_date":db_date,
        "max_rh":config.TARGET_RH
    }

    rendered_html = template.format(**data_rendered)

    return HTMLResponse(rendered_html)