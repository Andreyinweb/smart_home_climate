#  python3 api.py  # Сервер 

import os
import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from settings import config
from models import get_latest_climate_data, write_climate_data

# Логирование
api_log = logging.getLogger("api_app.api")
api_log.info(f"-------------------------------------------------------------------------------------------------")
api_log.info(f"Сервер запускается, перезагрузка = {config.WEBSITE_RETURN_TIME} с.")

app = FastAPI(title="Smart Home Climate API")

data_rendered ={} # TODO

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered # TODO

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
    # Получаем последнюю запись из базы данных
    latest_records = get_latest_climate_data("api_table", limit=1)
    
    if latest_records:
        db_data = latest_records[0]
    else:
        api_log.warning(f"На сервер не приходят значения из базы данных")               
        db_data = {'street_temp': 0.0, 'basement_temp': 0.0, 'floor_temp': 0.0, 'difference_temp': 0.0,
                    'average_temp': 0.0, 'street_humi': 0.0, 'basement_humi': 0.0, 'floor_humi': 0.0, 'street_voltage': 0.0,
                    'basement_voltage': 0.0, 'floor_voltage': 0.0, 'gas_meter': 0, 'a_floor_humi': 0.0, 'dp_floor': 0.0,
                    'a_street_humi': 0.0, 'dp_street': 0.0, 'a_basement_humi': 0.0, 'dp_basement': 0.0, 'humidity_difference': 0.0,
                    'vent_status': True, 'vent_time_val': 0.0, 'sim_a_basement_humi': 0.0, 'sim_basement_humi': 0.0, 'sim_floor_humi': 0.0,
                    'heating_delta': 0.0, 'heat_status': True, 'floor_temp_heated': 0.0, 'basement_temp_heated': 0.0, 'basement_humi_heated': 0.0,                
                    'a_basement_humi_heated': 0.0, 'floor_humi_heated': 0.0, 'a_floor_humi_heated': 0.0
                    }
        db_data["timestamp"] = "НЕТ ДАННЫХ ИЗ БАЗЫ ДАННЫХ"

    if db_data["vent_status"] and  db_data["vent_time_val"]:

        db_data["msg_vent_status"] = "ДА"
        db_data["vent_reason"] = f"Время: {db_data["vent_time_val"]} мин."

    elif not db_data["vent_status"]:
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "dАВ < 0.5"
    else:
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "Тяги нет."

    db_data["vent_class"] = "bg-green-100 text-green-800" if db_data["vent_status"] == "ДА" else "bg-red-100 text-red-800"

    # Класс видимости для таблицы проветривания (скрываем, если "НЕТ")
    db_data["vent_display_class"] = "" # if db_data["vent_status"] else "hidden" #TODO Розкоментируй

    if db_data["heat_status"]:
        db_data["msg_heat_status"] = "ДА"
    else:
        db_data["msg_heat_status"] = "НЕТ"

    db_data["heat_info"] = f"+{db_data["heating_delta"]} °C" if db_data["heat_status"] else ""
    db_data["heat_class"] = "bg-amber-100 text-amber-800" if db_data["heat_status"] else "bg-gray-100 text-gray-700"

    # Класс видимости для таблицы отопления (скрываем, если "НЕТ")
    db_data["heat_display_class"] = "" # if db_data["heat_status"] else "hidden" #TODO Розкоментируй

    # Чтение шаблона разметки
    html_path = os.path.join(config.PROJECT_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)
    
    rendered_html = template.format(**(db_data | {"website_return_time":config.WEBSITE_RETURN_TIME, "max_rh":config.TARGET_RH}))

    return HTMLResponse(rendered_html)