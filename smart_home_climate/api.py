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

data_rendered ={}

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
    # Получаем последнюю запись из базы данных
    latest_records = get_latest_climate_data(limit=1)
    
    if latest_records:
        db_data = latest_records[0]
        db_data["db_date"] = db_data["Date"]
    else:
        api_log.error(f"На сервер не приходят значения из базы данных")        
        db_data = {'street_temp': 0.0, 'basement_temp': 0.0, 'floor_temp': 0.0, 'difference_temp': 0.0,
          'average_temp': 0.0, 'street_humi': 0.0, 'basement_humi': 0.0, 'floor_humi': 0.0, 'street_voltage': 0.0, 
          'basement_voltage': 0.0, 'floor_voltage': 0.0, 'a_floor_humi': 0.0, 'dp_floor': 0.0, 
          'a_street_humi': 0.0, 'dp_street': 0.0, 'a_basement_humi': 0.0, 'dp_basement': 0.0, 'humidity_difference': 0.0, 
          'vent_status': 'ДА', 'vent_time_val': 0, 'sim_a_basement_humi': 0.0, 'sim_basement_humi': 0.0, 'sim_floor_humi': 0.0, 
          'heating_delta': 0.0, 'floor_temp_heated': 0.0, 'heat_status': 'ДА', 'basement_temp_heated': 0.0, 'basement_humi_heated': 0.0, 
          'floor_humi_heated': 0.0}
        db_data["db_date"] = "НЕТ ДАННЫХ ИЗ БАЗЫ ДАННЫХ"
############################################################### TODO Переделать под майн и базу данных        #############################################   
    for name in config.sensor_name:
        # Расчет абсолютных влажностей
        db_data["a_" + name + "_humi"] = operations.calculate_absolute_humidity(db_data[name + "_temp"], db_data[name + "_humi"])
        # Расчет точек росы
        db_data["dp_" + name] = operations.calculate_dew_point(db_data[name + "_temp"], db_data[name + "_humi"])

    # Расчет проветривания с учетом абсолютной погрешности ABSOLUTE_HUMIDITY_TOLERANCE (0.5 г/м³)
    db_data["humidity_difference"] = round(db_data["a_basement_humi"] - db_data["a_street_humi"], 2)

    if db_data["humidity_difference"] >= config.ABSOLUTE_HUMIDITY_TOLERANCE:        
        db_data["vent_status"] = "ДА"
        if abs(db_data["basement_temp"] - db_data["street_temp"]):
            db_data["vent_time_val"] = round(10.4 / math.sqrt(abs(db_data["basement_temp"] - db_data["street_temp"])))
        else:
            db_data["vent_time_val"] = 0
    else:
        db_data["vent_status"] = "НЕТ"
        db_data["vent_time_val"] = 0
     
    # Моделирование замещения (Проветривание)
    db_data["sim_a_basement_humi"] = db_data["a_street_humi"]
    db_data["sim_basement_humi"] = operations.calculate_relative_humidity(db_data["basement_temp"], db_data["sim_a_basement_humi"])
    db_data["sim_floor_humi"] = operations.calculate_relative_humidity(db_data["floor_temp"], db_data["sim_a_basement_humi"])

    # Расчет компенсационного нагрева (Отопление)
    heating_needed = db_data["floor_humi"] > config.TARGET_RH
    db_data["heating_delta"] = 0.0

    db_data["floor_temp_heated"], db_data["heating_delta"] = operations.calculating_temperature_from_humidity(db_data["floor_temp"], db_data["a_floor_humi"])

    db_data["heat_status"] = "ДА" if heating_needed else "НЕТ"

    # Итоговые параметры после догрева
    if heating_needed:
        db_data["basement_temp_heated"] = round(db_data["basement_temp"] + db_data["heating_delta"], 1)
        db_data["basement_humi_heated"] = operations.calculate_relative_humidity(db_data["basement_temp_heated"], db_data["a_basement_humi"])
        db_data["floor_humi_heated"] = operations.calculate_relative_humidity(db_data["floor_temp_heated"], db_data["a_floor_humi"])
    else:
        db_data["basement_temp_heated"] = db_data["basement_temp"]
        db_data["basement_humi_heated"] = db_data["basement_humi"]
        db_data["floor_temp_heated"] = db_data["floor_temp"]
        db_data["floor_humi_heated"] = db_data["floor_humi"]

################################################## TODO Переделать под майн и базу данных ####################################################################

    if db_data["vent_status"] == "ДА" and  db_data["vent_time_val"]:
        db_data["vent_reason"] = f"Время: {db_data["vent_time_val"]} мин."

    elif db_data["vent_status"] == "НЕТ":
        db_data["vent_reason"] = "dАВ < 0.5"
    else:
        db_data["vent_reason"] = "Тяги нет."

    db_data["vent_class"] = "bg-green-100 text-green-800" if db_data["vent_status"] == "ДА" else "bg-red-100 text-red-800"

    # Класс видимости для таблицы проветривания (скрываем, если "НЕТ")
    db_data["vent_display_class"] = "" # if db_data["vent_status"] == "ДА" else "hidden" #TODO Розкоментируй

    db_data["heat_info"] = f"+{db_data["heating_delta"]} °C" if heating_needed else ""
    db_data["heat_class"] = "bg-amber-100 text-amber-800" if heating_needed else "bg-gray-100 text-gray-700"

    # Класс видимости для таблицы отопления (скрываем, если "НЕТ")
    db_data["heat_display_class"] = "" # if db_data["heat_status"] == "ДА" else "hidden" #TODO Розкоментируй

    # Чтение шаблона разметки
    html_path = os.path.join(config.PROJECT_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)
    
    rendered_html = template.format(**(db_data | {"website_return_time":config.WEBSITE_RETURN_TIME, "max_rh":config.TARGET_RH}))

    return HTMLResponse(rendered_html)