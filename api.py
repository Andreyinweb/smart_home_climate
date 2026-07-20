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
work_log = logging.getLogger("climat_app.api")
api_log.info(f"-------------------------------------------------------------------------------------------------")
api_log.info(f"Сервер запускается, перезагрузка = {config.WEBSITE_RETURN_TIME} с.")

app = FastAPI(title="Smart Home Climate API")

db_nothing = {'id':1, 'timestamp': "НЕТ ДАННЫХ ИЗ БАЗЫ ДАННЫХ", 'street_temp': 0.0, 'basement_temp': 0.0, 'floor_temp': 0.0, 'difference_temp': 0.0,
                            'average_temp': 0.0, 'street_humi': 0.0, 'basement_humi': 0.0, 'floor_humi': 0.0, 'street_voltage': 0.0,
                            'basement_voltage': 0.0, 'floor_voltage': 0.0, 'gas_meter': 0, 'a_floor_humi': 0.0, 'dp_floor': 0.0,
                            'a_street_humi': 0.0, 'dp_street': 0.0, 'a_basement_humi': 0.0, 'dp_basement': 0.0, 'humidity_difference': 0.0,
                            'vent_status': True, 'vent_time_val': 0.0, 'sim_a_basement_humi': 0.0, 'sim_basement_humi': 0.0, 'sim_floor_humi': 0.0,
                            'heating_delta': 0.0, 'heat_status': True, 'floor_temp_heated': 0.0, 'basement_temp_heated': 0.0, 'basement_humi_heated': 0.0,                
                            'a_basement_humi_heated': 0.0, 'floor_humi_heated': 0.0, 'a_floor_humi_heated': 0.0
                            }

data_rendered = {} # TODO

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered # TODO

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
    latest_records = get_latest_climate_data('api_table')    
    if latest_records:
        db_data = latest_records[0]
    else:
        api_log.warning(f"На сервер не приходят значения из базы данных")               
        db_data = dict(db_nothing)

    if db_data['vent_status'] and db_data['vent_time_val']:
        db_data['msg_vent_status'] = "ДА"
        db_data['vent_reason'] = f"Время: {db_data['vent_time_val']} мин."
    elif not db_data['vent_status']:
        db_data['msg_vent_status'] = "НЕТ"
        db_data['vent_reason'] = "dАВ < 0.5"
    else:
        db_data['msg_vent_status'] = "НЕТ"
        db_data['vent_reason'] = "Тяги нет."

    db_data['vent_class'] = "bg-green-100 text-green-800" if db_data['vent_status'] == "ДА" else "bg-red-100 text-red-800"
    db_data['vent_display_class'] = "" 

    if db_data['heat_status']:
        db_data['msg_heat_status'] = "ДА"
    else:
        db_data['msg_heat_status'] = "НЕТ"

    db_data['heat_info'] = f"+{db_data['heating_delta']} °C" if db_data['heat_status'] else ""
    db_data['heat_class'] = "bg-amber-100 text-amber-800" if db_data['heat_status'] else "bg-gray-100 text-gray-700"
    db_data['heat_display_class'] = "" 

    # Чтение шаблона разметки
    html_path = os.path.join(config.PROJECT_DIR, 'index.html')
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)
    
    rendered_html = template.format(**(db_data | {"website_return_time":config.WEBSITE_RETURN_TIME, "max_rh":config.TARGET_RH}))
    return HTMLResponse(rendered_html)

# --- ПРОВЕТРИВАНИЕ ---####################################################################################################################################

@app.get("/ventilation", response_class=HTMLResponse)
async def get_ventilation_page():
    """Страница ручного управления проветриванием и сравнительной таблицы."""
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    latest_records = get_latest_climate_data('api_table')
    if latest_records:
        db_data = latest_records[0]
    else:
        api_log.warning(f"На сервер не приходят значения из базы данных")               
        db_data = dict(db_nothing)
        
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table['status_ventilation']:
            vent_before = get_latest_climate_data('api_table', status_ventilation_table['ventilation_start'], status_ventilation_table['ventilation_start'])[0]             
            vent_active = True
            vent_start_time = vent_before['timestamp'] 
            vent_now_time = db_data['timestamp']            
        else:
            vent_active = False
            vent_before = dict(db_data)
            vent_start_time = db_data['timestamp'] 
            vent_now_time = db_data['timestamp']
    else:
        # status_ventilation_table['status_ventilation'] = False      
        # status_ventilation_table['timestamp'] = db_data['timestamp']
        # status_ventilation_table['ventilation_start'] = 1
        # status_ventilation_table['stop_ventilation'] = 1
        vent_active = False
        vent_before = dict(db_data)
        vent_start_time = db_data['timestamp'] 
        vent_now_time = db_data['timestamp']


    # Вычисляем разницу
    diffs = {
        'diff_basement_temp': db_data['basement_temp'] - vent_before['basement_temp'],
        'diff_basement_humi': db_data['basement_humi'] - vent_before['basement_humi'],
        'diff_a_basement_humi': db_data['a_basement_humi']- vent_before['a_basement_humi'],
        'diff_floor_temp': db_data['floor_temp'] - vent_before['floor_temp'],
        'diff_floor_humi': db_data['floor_humi'] - vent_before['floor_humi'],
        'diff_a_floor_humi': db_data['a_floor_humi'] - vent_before['a_floor_humi'],
    }

    # Классы стилей для изменений (уменьшение влажности — зеленый, увеличение — красный)
    style_classes = {
        'diff_basement_temp_class': "text-blue-600 font-semibold" if abs(diffs['diff_basement_temp']) > 0.1 else "text-gray-500",
        "diff_basement_humi_class": "text-green-600 font-semibold" if diffs['diff_basement_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_basement_humi'] > 0.5 else "text-gray-500",
        "diff_a_basement_humi_class": "text-green-600 font-semibold" if diffs['diff_a_basement_humi'] < -0.1 else "text-red-600 font-semibold" if diffs['diff_a_basement_humi'] > 0.1 else "text-gray-500",
        "diff_floor_temp_class": "text-blue-600 font-semibold" if abs(diffs['diff_floor_temp']) > 0.1 else "text-gray-500",
        "diff_floor_humi_class": "text-green-600 font-semibold" if diffs['diff_floor_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_floor_humi'] > 0.5 else "text-gray-500",
        "diff_a_floor_humi_class": "text-green-600 font-semibold" if diffs['diff_a_floor_humi'] < -0.1 else "text-red-600 font-semibold" if diffs['diff_a_floor_humi'] > 0.1 else "text-gray-500",
    }

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "status_text": "АКТИВНО" if vent_active else "НЕАКТИВНО",
        "status_class": "bg-green-100 text-green-800 border-green-300" if vent_active else "bg-gray-100 text-gray-700 border-gray-300",
        "vent_start_time": vent_start_time[11:16] if vent_start_time else "Нет запущенных циклов",
        'vent_now_time': vent_now_time[11:16],
        
        "b_temp_before": vent_before.get('basement_temp', 0.0),
        "b_humi_before": vent_before.get('basement_humi', 0.0),
        "b_ahumi_before": vent_before.get('a_basement_humi', 0.0),
        "f_temp_before": vent_before.get('floor_temp', 0.0),
        "f_humi_before": vent_before.get('floor_humi', 0.0),
        "f_ahumi_before": vent_before.get('a_floor_humi', 0.0),

        "b_temp_now": db_data.get('basement_temp', 0.0),
        "b_humi_now": db_data.get('basement_humi', 0.0),
        "b_ahumi_now": db_data.get('a_basement_humi', 0.0),
        "f_temp_now": db_data.get('floor_temp', 0.0),
        "f_humi_now": db_data.get('floor_humi', 0.0),
        "f_ahumi_now": db_data.get('a_floor_humi', 0.0),
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
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if not status_ventilation_table['status_ventilation']: 
            latest_records = get_latest_climate_data('api_table')
            if latest_records:  
                api_on_db['status_ventilation'] = True       
                api_on_db['timestamp'] = latest_records[0]['timestamp']
                api_on_db['ventilation_start'] = latest_records[0]['id']
                api_on_db['stop_ventilation'] = 0
                write_climate_data('ventilation_table', api_on_db)
                api_log.info(f"[БД] Успешный старт проветривания: api_id={api_on_db['ventilation_start']}, timestamp={api_on_db['timestamp']}")
            else:
                api_log.warning(f"На сервер не приходят значения из базы данных")
        else:
            None
    else:
        latest_records = get_latest_climate_data('api_table')
        if latest_records: 
            api_on_db['status_ventilation'] = True      
            api_on_db['timestamp'] = latest_records[0]['timestamp']
            api_on_db['ventilation_start'] = latest_records[0]['id']
            api_on_db['stop_ventilation'] = 0
            write_climate_data('ventilation_table', api_on_db)
            api_log.info(f"[БД] Успешный старт проветривания: api_id={api_on_db['ventilation_start']}, timestamp={api_on_db['timestamp']}")
        else:
            api_log.warning(f"На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/ventilation", status_code=303)


@app.post("/api/ventilation/stop")
async def stop_ventilation():
    """Запись остановки проветривания в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table['status_ventilation']:
            latest_records = get_latest_climate_data('api_table')
            if latest_records:
                api_on_db['timestamp'] = status_ventilation_table['timestamp']
                api_on_db['status_ventilation'] = False
                api_on_db['ventilation_start'] = status_ventilation_table['ventilation_start']
                api_on_db['stop_ventilation'] = latest_records[0]['id']
                write_climate_data('ventilation_table', api_on_db, row_id=status_ventilation_table['id'])
                api_log.info(f"[БД] Успешный стоп проветривания: api_id={api_on_db['stop_ventilation']}")
            else:
                api_log.warning(f"На сервер не приходят значения из базы данных") 

        else: 
            None
    else:
        None
    return RedirectResponse(url="/ventilation", status_code=303)

# --- ОТОПЛЕНИЕ ----------------------------------------------------------------------------------------------->>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

@app.get("/heating", response_class=HTMLResponse)
async def get_heating_page():
    """Страница ручного управления отоплением и сравнительной таблицы."""
    heat_before = {}
    latest_heating_table = get_latest_climate_data("heating_table")
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table["stop_heating"]:            
            latest_records = get_latest_climate_data('api_table')
            if latest_records:
                db_data = latest_records[0]
            else:
                api_log.warning(f"На сервер не приходят значения из базы данных")               
                db_data = dict(db_nothing)

            heat_active = False
            heat_before = dict(db_data)
            heat_start_time = db_data['timestamp'] 
        else:
            latest_records = get_latest_climate_data('api_table')
            heat_before = get_latest_climate_data('api_table', status_heating_table["heating_start"], status_heating_table["heating_start"])[0]
            if latest_records:
                db_data = latest_records[0]
            else:
                api_log.warning(f"На сервер не приходят значения из базы данных")               
                db_data = dict(db_nothing)
                
            heat_active = True
            heat_start_time = heat_before['timestamp'] 
    else:
        latest_records = get_latest_climate_data('api_table')
        if latest_records:
            db_data = latest_records[0]
        else:
            api_log.warning(f"На сервер не приходят значения из базы данных")               
            db_data = dict(db_nothing)

    if not heat_before:
        heat_before = dict(db_data)
        heat_active = False
        heat_start_time = db_data['timestamp']

    diffs = {
        'diff_basement_temp': db_data.get('basement_temp', 0) - heat_before.get('basement_temp', 0),
        'diff_basement_humi': db_data.get('basement_humi', 0) - heat_before.get('basement_humi', 0),
        'diff_a_basement_humi': db_data.get('a_basement_humi', 0) - heat_before.get('a_basement_humi', 0),
        'diff_floor_temp': db_data.get('floor_temp', 0) - heat_before.get('floor_temp', 0),
        'diff_floor_humi': db_data.get('floor_humi', 0) - heat_before.get('floor_humi', 0),
        'diff_a_floor_humi': db_data.get('a_floor_humi', 0) - heat_before.get('a_floor_humi', 0),
    }

    # Классы стилей для отопления (увеличение температуры — зеленый, падение — красный)
    style_classes = {
        'diff_basement_temp_class': "text-green-600 font-semibold" if diffs['diff_basement_temp'] > 0.1 else "text-red-600 font-semibold" if diffs['diff_basement_temp'] < -0.1 else "text-gray-500",
        "diff_basement_humi_class": "text-green-600 font-semibold" if diffs['diff_basement_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_basement_humi'] > 0.5 else "text-gray-500",
        "diff_a_basement_humi_class": "text-gray-500",
        "diff_floor_temp_class": "text-green-600 font-semibold" if diffs['diff_floor_temp'] > 0.1 else "text-red-600 font-semibold" if diffs['diff_floor_temp'] < -0.1 else "text-gray-500",
        "diff_floor_humi_class": "text-green-600 font-semibold" if diffs['diff_floor_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_floor_humi'] > 0.5 else "text-gray-500",
        "diff_a_floor_humi_class": "text-gray-500",
    }

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "status_text": "АКТИВНО" if heat_active else "НЕАКТИВНО",
        "status_class": "bg-amber-100 text-amber-800 border-amber-300" if heat_active else "bg-gray-100 text-gray-700 border-gray-300",
        "heat_start_time": heat_start_time if heat_start_time else "Нет запущенных циклов",
        
        "b_temp_before": heat_before.get('basement_temp', 0.0),
        "b_humi_before": heat_before.get('basement_humi', 0.0),
        "b_ahumi_before": heat_before.get('a_basement_humi', 0.0),
        "f_temp_before": heat_before.get('floor_temp', 0.0),
        "f_humi_before": heat_before.get('floor_humi', 0.0),
        "f_ahumi_before": heat_before.get('a_floor_humi', 0.0),

        "b_temp_now": db_data.get('basement_temp', 0.0),
        "b_humi_now": db_data.get('basement_humi', 0.0),
        "b_ahumi_now": db_data.get('a_basement_humi', 0.0),
        "f_temp_now": db_data.get('floor_temp', 0.0),
        "f_humi_now": db_data.get('floor_humi', 0.0),
        "f_ahumi_now": db_data.get('a_floor_humi', 0.0),
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