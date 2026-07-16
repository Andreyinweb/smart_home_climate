import os
import logging
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from settings import config
from models import get_latest_climate_data, write_climate_data, get_db_connection

# Логирование
api_log = logging.getLogger("api_app.api")
api_log.info(f"-------------------------------------------------------------------------------------------------")
api_log.info(f"Сервер запускается, перезагрузка = {config.WEBSITE_RETURN_TIME} с.")

app = FastAPI(title="Smart Home Climate API")

data_rendered = {} # TODO

def get_system_status_and_before_data(table_name: str, start_col: str):
    """
    Получает текущий статус системы (активна/неактивна), время ее запуска
    и показатели датчиков из api_table непосредственно ДО момента запуска.
    Использует ID записи из api_table для точного сопоставления.
    """
    status = False
    before_data = None
    start_time = None
    stop_col = "stop_ventilation" if table_name == "ventilation_table" else "stop_heating"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Находим последнюю запись управления сессией
            cursor.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                r_dict = dict(row)
                start_val = r_dict.get(start_col, 0)
                stop_val = r_dict.get(stop_col, 0)
                start_time = r_dict.get("timestamp")
                
                # Сессия активна, если кнопка "старт" была нажата (содержит ID > 0), а "стоп" еще нет (0)
                status = bool(start_val and start_val > 0 and (stop_val == 0 or stop_val is None))
                
                if start_val and start_val > 0:
                    # Извлекаем запись из api_table, которая была строго ДО старта этой сессии
                    cursor.execute(
                        "SELECT * FROM api_table WHERE id < ? ORDER BY id DESC LIMIT 1",
                        (start_val,)
                    )
                    before_row = cursor.fetchone()
                    if before_row:
                        before_data = dict(before_row)
    except Exception as e:
        api_log.error(f"Ошибка при получении статуса из {table_name}: {e}")
        
    return status, before_data, start_time

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered # TODO

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
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

    if db_data["vent_status"] and db_data["vent_time_val"]:
        db_data["msg_vent_status"] = "ДА"
        db_data["vent_reason"] = f"Время: {db_data['vent_time_val']} мин."
    elif not db_data["vent_status"]:
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "dАВ < 0.5"
    else:
        db_data["msg_vent_status"] = "НЕТ"
        db_data["vent_reason"] = "Тяги нет."

    db_data["vent_class"] = "bg-green-100 text-green-800" if db_data["vent_status"] == "ДА" else "bg-red-100 text-red-800"
    db_data["vent_display_class"] = "" 

    if db_data["heat_status"]:
        db_data["msg_heat_status"] = "ДА"
    else:
        db_data["msg_heat_status"] = "НЕТ"

    db_data["heat_info"] = f"+{db_data['heating_delta']} °C" if db_data["heat_status"] else ""
    db_data["heat_class"] = "bg-amber-100 text-amber-800" if db_data["heat_status"] else "bg-gray-100 text-gray-700"
    db_data["heat_display_class"] = "" 

    # Чтение шаблона разметки
    html_path = os.path.join(config.PROJECT_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)
    
    rendered_html = template.format(**(db_data | {"website_return_time":config.WEBSITE_RETURN_TIME, "max_rh":config.TARGET_RH}))
    return HTMLResponse(rendered_html)

# --- ПРОВЕТРИВАНИЕ ---

@app.get("/ventilation", response_class=HTMLResponse)
async def get_ventilation_page():
    """Страница ручного управления проветриванием и сравнительной таблицы."""
    vent_active, vent_before, vent_start_time = get_system_status_and_before_data("ventilation_table", "ventilation_start")
    
    latest_records = get_latest_climate_data("api_table", limit=1)
    db_data = latest_records[0] if latest_records else {}

    # Если бэкап-данных нет (первый запуск), берем текущие, чтобы разница была нулевой
    if not vent_before:
        vent_before = db_data

    # Вычисляем разницу
    diffs = {
        "diff_basement_temp": db_data.get("basement_temp", 0) - vent_before.get("basement_temp", 0),
        "diff_basement_humi": db_data.get("basement_humi", 0) - vent_before.get("basement_humi", 0),
        "diff_a_basement_humi": db_data.get("a_basement_humi", 0) - vent_before.get("a_basement_humi", 0),
        "diff_floor_temp": db_data.get("floor_temp", 0) - vent_before.get("floor_temp", 0),
        "diff_floor_humi": db_data.get("floor_humi", 0) - vent_before.get("floor_humi", 0),
        "diff_a_floor_humi": db_data.get("a_floor_humi", 0) - vent_before.get("a_floor_humi", 0),
    }

    # Классы стилей для изменений (уменьшение влажности — зеленый, увеличение — красный)
    style_classes = {
        "diff_basement_temp_class": "text-blue-600 font-semibold" if abs(diffs["diff_basement_temp"]) > 0.1 else "text-gray-500",
        "diff_basement_humi_class": "text-green-600 font-semibold" if diffs["diff_basement_humi"] < -0.5 else "text-red-600 font-semibold" if diffs["diff_basement_humi"] > 0.5 else "text-gray-500",
        "diff_a_basement_humi_class": "text-green-600 font-semibold" if diffs["diff_a_basement_humi"] < -0.1 else "text-red-600 font-semibold" if diffs["diff_a_basement_humi"] > 0.1 else "text-gray-500",
        "diff_floor_temp_class": "text-blue-600 font-semibold" if abs(diffs["diff_floor_temp"]) > 0.1 else "text-gray-500",
        "diff_floor_humi_class": "text-green-600 font-semibold" if diffs["diff_floor_humi"] < -0.5 else "text-red-600 font-semibold" if diffs["diff_floor_humi"] > 0.5 else "text-gray-500",
        "diff_a_floor_humi_class": "text-green-600 font-semibold" if diffs["diff_a_floor_humi"] < -0.1 else "text-red-600 font-semibold" if diffs["diff_a_floor_humi"] > 0.1 else "text-gray-500",
    }

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "status_text": "АКТИВНО" if vent_active else "НЕАКТИВНО",
        "status_class": "bg-green-100 text-green-800 border-green-300" if vent_active else "bg-gray-100 text-gray-700 border-gray-300",
        "vent_start_time": vent_start_time if vent_start_time else "Нет запущенных циклов",
        
        "b_temp_before": vent_before.get("basement_temp", 0.0),
        "b_humi_before": vent_before.get("basement_humi", 0.0),
        "b_ahumi_before": vent_before.get("a_basement_humi", 0.0),
        "f_temp_before": vent_before.get("floor_temp", 0.0),
        "f_humi_before": vent_before.get("floor_humi", 0.0),
        "f_ahumi_before": vent_before.get("a_floor_humi", 0.0),

        "b_temp_now": db_data.get("basement_temp", 0.0),
        "b_humi_now": db_data.get("basement_humi", 0.0),
        "b_ahumi_now": db_data.get("a_basement_humi", 0.0),
        "f_temp_now": db_data.get("floor_temp", 0.0),
        "f_humi_now": db_data.get("floor_humi", 0.0),
        "f_ahumi_now": db_data.get("a_floor_humi", 0.0),
    }

    html_path = os.path.join(config.PROJECT_DIR, "ventilation.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона ventilation.html не найден.", status_code=500)

    rendered_html = template.format(**(page_data | diffs | style_classes))
    return HTMLResponse(rendered_html)

@app.post("/api/ventilation/start")
async def start_ventilation():
    """Запись старта проветривания в БД с привязкой ID и timestamp из api_table."""
    api_id = None
    api_timestamp = None
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp FROM api_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                api_id = row[0]       # Гарантированно берем id по индексу
                api_timestamp = row[1] # Гарантированно берем timestamp по индексу
    except Exception as e:
        api_log.error(f"[БД] Не удалось прочитать api_table напрямую при старте вентиляции: {e}")

    # Резервный вариант, если база пуста
    if api_id is None:
        api_id = 1
        api_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        api_log.warning("[БД] Используем дефолтные значения для старта проветривания")

    query = "INSERT INTO ventilation_table (timestamp, ventilation_start, stop_ventilation) VALUES (?, ?, 0)"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (api_timestamp, api_id))
            conn.commit()
        api_log.info(f"[БД] Успешный старт проветривания: api_id={api_id}, timestamp={api_timestamp}")
    except Exception as e:
        api_log.error(f"[БД] Ошибка записи старта проветривания: {e}")
    return RedirectResponse(url="/ventilation", status_code=303)

@app.post("/api/ventilation/stop")
async def stop_ventilation():
    """Запись остановки проветривания в БД с фиксацией ID текущей записи из api_table."""
    api_id = None
    api_timestamp = None
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp FROM api_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                api_id = row[0]
                api_timestamp = row[1]
    except Exception as e:
        api_log.error(f"[БД] Не удалось прочитать api_table напрямую при остановке вентиляции: {e}")

    if api_id is None:
        api_id = 1
        api_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Ищем ID последней сессии в ventilation_table
            cursor.execute("SELECT id FROM ventilation_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                vent_row_id = row[0] # ИД записи в ventilation_table
                cursor.execute("UPDATE ventilation_table SET stop_ventilation = ? WHERE id = ?", (api_id, vent_row_id))
                conn.commit()
            else:
                cursor.execute("INSERT INTO ventilation_table (timestamp, ventilation_start, stop_ventilation) VALUES (?, 0, ?)", (api_timestamp, api_id))
                conn.commit()
        api_log.info(f"[БД] Успешный стоп проветривания: api_id={api_id}")
    except Exception as e:
        api_log.error(f"[БД] Ошибка записи остановки проветривания: {e}")
    return RedirectResponse(url="/ventilation", status_code=303)

# --- ОТОПЛЕНИЕ ---

@app.get("/heating", response_class=HTMLResponse)
async def get_heating_page():
    """Страница ручного управления отоплением и сравнительной таблицы."""
    heat_active, heat_before, heat_start_time = get_system_status_and_before_data("heating_table", "heating_start")
    
    latest_records = get_latest_climate_data("api_table", limit=1)
    db_data = latest_records[0] if latest_records else {}

    if not heat_before:
        heat_before = db_data

    diffs = {
        "diff_basement_temp": db_data.get("basement_temp", 0) - heat_before.get("basement_temp", 0),
        "diff_basement_humi": db_data.get("basement_humi", 0) - heat_before.get("basement_humi", 0),
        "diff_a_basement_humi": db_data.get("a_basement_humi", 0) - heat_before.get("a_basement_humi", 0),
        "diff_floor_temp": db_data.get("floor_temp", 0) - heat_before.get("floor_temp", 0),
        "diff_floor_humi": db_data.get("floor_humi", 0) - heat_before.get("floor_humi", 0),
        "diff_a_floor_humi": db_data.get("a_floor_humi", 0) - heat_before.get("a_floor_humi", 0),
    }

    # Классы стилей для отопления (увеличение температуры — зеленый, падение — красный)
    style_classes = {
        "diff_basement_temp_class": "text-green-600 font-semibold" if diffs["diff_basement_temp"] > 0.1 else "text-red-600 font-semibold" if diffs["diff_basement_temp"] < -0.1 else "text-gray-500",
        "diff_basement_humi_class": "text-green-600 font-semibold" if diffs["diff_basement_humi"] < -0.5 else "text-red-600 font-semibold" if diffs["diff_basement_humi"] > 0.5 else "text-gray-500",
        "diff_a_basement_humi_class": "text-gray-500",
        "diff_floor_temp_class": "text-green-600 font-semibold" if diffs["diff_floor_temp"] > 0.1 else "text-red-600 font-semibold" if diffs["diff_floor_temp"] < -0.1 else "text-gray-500",
        "diff_floor_humi_class": "text-green-600 font-semibold" if diffs["diff_floor_humi"] < -0.5 else "text-red-600 font-semibold" if diffs["diff_floor_humi"] > 0.5 else "text-gray-500",
        "diff_a_floor_humi_class": "text-gray-500",
    }

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "status_text": "АКТИВНО" if heat_active else "НЕАКТИВНО",
        "status_class": "bg-amber-100 text-amber-800 border-amber-300" if heat_active else "bg-gray-100 text-gray-700 border-gray-300",
        "heat_start_time": heat_start_time if heat_start_time else "Нет запущенных циклов",
        
        "b_temp_before": heat_before.get("basement_temp", 0.0),
        "b_humi_before": heat_before.get("basement_humi", 0.0),
        "b_ahumi_before": heat_before.get("a_basement_humi", 0.0),
        "f_temp_before": heat_before.get("floor_temp", 0.0),
        "f_humi_before": heat_before.get("floor_humi", 0.0),
        "f_ahumi_before": heat_before.get("a_floor_humi", 0.0),

        "b_temp_now": db_data.get("basement_temp", 0.0),
        "b_humi_now": db_data.get("basement_humi", 0.0),
        "b_ahumi_now": db_data.get("a_basement_humi", 0.0),
        "f_temp_now": db_data.get("floor_temp", 0.0),
        "f_humi_now": db_data.get("floor_humi", 0.0),
        "f_ahumi_now": db_data.get("a_floor_humi", 0.0),
    }

    html_path = os.path.join(config.PROJECT_DIR, "heating.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона heating.html не найден.", status_code=500)

    rendered_html = template.format(**(page_data | diffs | style_classes))
    return HTMLResponse(rendered_html)

@app.post("/api/heating/start")
async def start_heating():
    """Запись старта отопления в БД с привязкой ID и timestamp из api_table."""
    api_id = None
    api_timestamp = None
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp FROM api_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                api_id = row[0]
                api_timestamp = row[1]
    except Exception as e:
        api_log.error(f"[БД] Не удалось прочитать api_table напрямую при старте отопления: {e}")

    if api_id is None:
        api_id = 1
        api_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    query = "INSERT INTO heating_table (timestamp, heating_start, stop_heating) VALUES (?, ?, 0)"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (api_timestamp, api_id))
            conn.commit()
        api_log.info(f"[БД] Успешный старт отопления: api_id={api_id}, timestamp={api_timestamp}")
    except Exception as e:
        api_log.error(f"[БД] Ошибка записи старта отопления: {e}")
    return RedirectResponse(url="/heating", status_code=303)

@app.post("/api/heating/stop")
async def stop_heating():
    """Запись остановки отопления в БД с фиксацией ID текущей записи из api_table."""
    api_id = None
    api_timestamp = None
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, timestamp FROM api_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                api_id = row[0]
                api_timestamp = row[1]
    except Exception as e:
        api_log.error(f"[БД] Не удалось прочитать api_table напрямую при остановке отопления: {e}")

    if api_id is None:
        api_id = 1
        api_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM heating_table ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                heat_row_id = row[0]
                cursor.execute("UPDATE heating_table SET stop_heating = ? WHERE id = ?", (api_id, heat_row_id))
                conn.commit()
            else:
                cursor.execute("INSERT INTO heating_table (timestamp, heating_start, stop_heating) VALUES (?, 0, ?)", (api_timestamp, api_id))
                conn.commit()
        api_log.info(f"[БД] Успешный стоп отопления: api_id={api_id}")
    except Exception as e:
        api_log.error(f"[БД] Ошибка записи остановки отопления: {e}")
    return RedirectResponse(url="/heating", status_code=303)