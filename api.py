import os
import logging
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
data_rendered = {} # TODO

def get_no_data_response():
    """Возвращает красивую страницу ожидания данных, если в БД пусто."""
    html_path = os.path.join(config.PROJECT_DIR, 'templates', 'no_data.html')
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
        rendered_html = template.format(website_return_time=config.WEBSITE_RETURN_TIME)
        return HTMLResponse(rendered_html, status_code=503)
    return HTMLResponse(
        "<h1 style='font-family:sans-serif; text-align:center; margin-top:50px; color:#ef4444;'>"
        "Ошибка: База данных пуста, и шаблон no_data.html не найден в папке templates.</h1>", 
        status_code=500
    )

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered # TODO

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе данных из БД, физических расчетов и шаблона HTML."""
    latest_records = get_latest_climate_data('api_table')    
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response()
        
    db_data = latest_records[0]

    if db_data.get('vent_status') and db_data.get('vent_time_val'):
        db_data['msg_vent_status'] = "ДА"
        db_data['vent_reason'] = f"Время: {db_data['vent_time_val']} мин."
    elif not db_data.get('vent_status'):
        db_data['msg_vent_status'] = "НЕТ"
        db_data['vent_reason'] = "dАВ < 0.5"
    else:
        db_data['msg_vent_status'] = "НЕТ"
        db_data['vent_reason'] = "Тяги нет."

    db_data['vent_class'] = "bg-green-100 text-green-800" if db_data.get('vent_status') == "ДА" else "bg-red-100 text-red-800"
    db_data['vent_display_class'] = "" 

    if db_data.get('heat_status'):
        db_data['msg_heat_status'] = "ДА"
    else:
        db_data['msg_heat_status'] = "НЕТ"

    db_data['heat_info'] = f"+{db_data.get('heating_delta', 0.0)} °C" if db_data.get('heat_status') else ""
    db_data['heat_class'] = "bg-amber-100 text-amber-800" if db_data.get('heat_status') else "bg-gray-100 text-gray-700"
    db_data['heat_display_class'] = "" 

    # Чтение шаблона разметки
    html_path = os.path.join(config.PROJECT_DIR, 'templates', 'index.html')
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден в папке templates.", status_code=500)
    
    rendered_html = template.format(**(db_data | {"website_return_time":config.WEBSITE_RETURN_TIME, "max_rh":config.TARGET_RH}))
    return HTMLResponse(rendered_html)

# --- ПРОВЕТРИВАНИЕ ---####################################################################################################################################

@app.get("/ventilation", response_class=HTMLResponse)
async def get_ventilation_page():
    """Страница ручного управления проветриванием и сравнительной таблицы."""
    latest_records = get_latest_climate_data('api_table')
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response()
        
    db_data = latest_records[0]
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    
    if latest_ventilation_table and latest_ventilation_table[0]['status_ventilation']:
        status_ventilation_table = latest_ventilation_table[0]
        vent_before = get_latest_climate_data('api_table', status_ventilation_table['ventilation_start'], status_ventilation_table['ventilation_start'])[0]             
        vent_active = True
        vent_start_time = vent_before['timestamp'] 
        vent_now_time = db_data['timestamp']            
    else:
        vent_active = False
        vent_before = dict(db_data)
        vent_start_time = db_data['timestamp'] 
        vent_now_time = db_data['timestamp']

    # Вычисляем разницу показателей
    diffs = {
        'diff_basement_temp': db_data['basement_temp'] - vent_before['basement_temp'],
        'diff_basement_humi': db_data['basement_humi'] - vent_before['basement_humi'],
        'diff_a_basement_humi': db_data['a_basement_humi'] - vent_before['a_basement_humi'],
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

    # Динамическая настройка кнопок
    if vent_active:
        btn_start_class = "bg-gray-300 text-gray-500 cursor-not-allowed"
        btn_stop_class = "bg-red-600 text-white hover:bg-red-700 shadow-md"
        btn_start_disabled = "disabled"
        btn_stop_disabled = ""
    else:
        btn_start_class = "bg-green-600 text-white hover:bg-green-700 shadow-md"
        btn_stop_class = "bg-gray-300 text-gray-500 cursor-not-allowed"
        btn_start_disabled = ""
        btn_stop_disabled = "disabled"

    # Превращаем все ключи исторического среза в переменные с префиксом before_ для HTML шаблона
    before_data = {f"before_{k}": v for k, v in vent_before.items()}

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "vent_start_time": vent_start_time[11:16] if vent_start_time else "Нет запущенных циклов",
        'vent_now_time': vent_now_time[11:16],
    }

    html_path = os.path.join(config.PROJECT_DIR, "templates", "ventilation.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона ventilation.html не найден в папке templates.", status_code=500)

    # db_data предоставляет текущие значения без суффикса (floor_temp, floor_humi и т.д.)
    rendered_html = template.format(**(db_data | before_data | diffs | style_classes | page_data))
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

    return RedirectResponse(url="/ventilation", status_code=303)

# --- ОТОПЛЕНИЕ ----------------------------------------------------------------------------------------------->>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

@app.get("/heating", response_class=HTMLResponse)
async def get_heating_page():
    """Страница ручного управления отоплением и сравнительной таблицы."""
    latest_records = get_latest_climate_data('api_table')
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response()
        
    db_data = latest_records[0]
    latest_heating_table = get_latest_climate_data("heating_table")
    
    if latest_heating_table and latest_heating_table[0]["stop_heating"] == 0:
        status_heating_table = latest_heating_table[0]
        heat_before = get_latest_climate_data('api_table', status_heating_table["heating_start"], status_heating_table["heating_start"])[0]
        heat_active = True
        heat_start_time = heat_before['timestamp'] 
    else:
        heat_active = False
        heat_before = dict(db_data)
        heat_start_time = db_data['timestamp']

    # Вычисляем разницу для отопления (только температура и влажность подвала/пола)
    diffs = {
        'diff_basement_temp': db_data['basement_temp'] - heat_before['basement_temp'],
        'diff_basement_humi': db_data['basement_humi'] - heat_before['basement_humi'],
        'diff_floor_temp': db_data['floor_temp'] - heat_before['floor_temp'],
        'diff_floor_humi': db_data['floor_humi'] - heat_before['floor_humi'],
    }

    # Классы стилей для отопления (увеличение температуры — зеленый, падение — красный)
    style_classes = {
        'diff_basement_temp_class': "text-green-600 font-semibold" if diffs['diff_basement_temp'] > 0.1 else "text-red-600 font-semibold" if diffs['diff_basement_temp'] < -0.1 else "text-gray-500",
        "diff_basement_humi_class": "text-green-600 font-semibold" if diffs['diff_basement_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_basement_humi'] > 0.5 else "text-gray-500",
        "diff_floor_temp_class": "text-green-600 font-semibold" if diffs['diff_floor_temp'] > 0.1 else "text-red-600 font-semibold" if diffs['diff_floor_temp'] < -0.1 else "text-gray-500",
        "diff_floor_humi_class": "text-green-600 font-semibold" if diffs['diff_floor_humi'] < -0.5 else "text-red-600 font-semibold" if diffs['diff_floor_humi'] > 0.5 else "text-gray-500",
    }

    # Динамическая настройка кнопок отопления
    if heat_active:
        btn_start_class = "bg-gray-300 text-gray-500 cursor-not-allowed"
        btn_stop_class = "bg-red-600 text-white hover:bg-red-700 shadow-md"
        btn_start_disabled = "disabled"
        btn_stop_disabled = ""
    else:
        btn_start_class = "bg-amber-500 text-white hover:bg-amber-600 shadow-md"
        btn_stop_class = "bg-gray-300 text-gray-500 cursor-not-allowed"
        btn_start_disabled = ""
        btn_stop_disabled = "disabled"

    # Превращаем все ключи исторического среза в переменные с префиксом before_ для HTML шаблона
    before_data = {f"before_{k}": v for k, v in heat_before.items()}

    page_data = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "heat_start_time": heat_start_time[11:16] if heat_start_time else "Нет запущенных циклов",
    }

    html_path = os.path.join(config.PROJECT_DIR, "templates", "heating.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона heating.html не найден в папке templates.", status_code=500)

    # Передаем объединенный словарь, где текущие показатели берутся без суффиксов прямо из db_data
    rendered_html = template.format(**(db_data | before_data | diffs | style_classes | page_data))
    return HTMLResponse(rendered_html)

@app.post("/api/heating/start")
async def start_heating():
    """Запись старта отопления в БД с привязкой ID и timestamp из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data('heating_table')
    is_heating_active = False
    
    # Проверяем, запущено ли уже отопление
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table['stop_heating'] == 0:
            is_heating_active = True
            
    if not is_heating_active:
        latest_records = get_latest_climate_data('api_table')
        if latest_records: 
            api_on_db['timestamp'] = latest_records[0]['timestamp']
            api_on_db['heating_start'] = latest_records[0]['id']
            api_on_db['stop_heating'] = 0
            write_climate_data('heating_table', api_on_db)
            api_log.info(f"[БД] Успешный старт отопления: api_id={api_on_db['heating_start']}, timestamp={api_on_db['timestamp']}")
        else:
            api_log.warning(f"На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/heating", status_code=303)

@app.post("/api/heating/stop")
async def stop_heating():
    """Запись остановки отопления в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data('heating_table')
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        # Если отопление в данный момент запущено (stop_heating == 0)
        if status_heating_table['stop_heating'] == 0:
            latest_records = get_latest_climate_data('api_table')
            if latest_records:
                api_on_db['timestamp'] = status_heating_table['timestamp']
                api_on_db['heating_start'] = status_heating_table['heating_start']
                api_on_db['stop_heating'] = latest_records[0]['id']
                write_climate_data('heating_table', api_on_db, row_id=status_heating_table['id'])
                api_log.info(f"[БД] Успешный стоп отопления: api_id={api_on_db['stop_heating']}")
            else:
                api_log.warning(f"На сервер не приходят значения из базы данных") 
                
    return RedirectResponse(url="/heating", status_code=303)