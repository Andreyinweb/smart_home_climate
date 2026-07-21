import os
import logging
from urllib.parse import parse_qs
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from settings import config
from models import get_latest_climate_data, write_climate_data, get_db_connection

api_log = logging.getLogger("api_app.api")
work_log = logging.getLogger("climat_app.api")
api_log.info("-------------------------------------------------------------------------------------------------")
api_log.info(f"Сервер запускается, перезагрузка = {config.WEBSITE_RETURN_TIME} с.")

app = FastAPI(title="Smart Home Climate API")
data_rendered = {}

app.mount("/static", StaticFiles(directory=os.path.join(config.PROJECT_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(config.PROJECT_DIR, "templates"))

def get_no_data_response(request: Request):
    """Возвращает страницу ожидания данных, если в БД пусто."""
    html_path = os.path.join(config.PROJECT_DIR, 'templates', 'no_data.html')
    if os.path.exists(html_path):
        return templates.TemplateResponse(
            request=request,
            name="no_data.html",
            context={"website_return_time": config.WEBSITE_RETURN_TIME},
            status_code=503
        )
    return HTMLResponse(
        "<h1 style='font-family:sans-serif; text-align:center; margin-top:50px; color:#ef4444;'>"
        "Ошибка: База данных пуста, и шаблон no_data.html не найден в папке templates.</h1>",
        status_code=500
    )

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return data_rendered

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Сборка дашборда на основе данных из БД и Jinja2 шаблона."""
    latest_records = get_latest_climate_data('api_table')    
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
        
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

    db_data['vent_class'] = "badge-green" if db_data.get('vent_status') == "ДА" else "badge-red"
    db_data['vent_display_class'] = "" 

    if db_data.get('heat_status'):
        db_data['msg_heat_status'] = "ДА"
    else:
        db_data['msg_heat_status'] = "НЕТ"

    db_data['heat_info'] = f"+{db_data.get('heating_delta', 0.0)} °C" if db_data.get('heat_status') else ""
    db_data['heat_class'] = "badge-amber" if db_data.get('heat_status') else "badge-gray"
    db_data['heat_display_class'] = "" 

    context = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "max_rh": config.TARGET_RH,
        **db_data
    }

    return templates.TemplateResponse(request=request, name="index.html", context=context)

@app.get("/ventilation", response_class=HTMLResponse)
async def get_ventilation_page(request: Request):
    """Страница ручного управления проветриванием и сравнительной таблицы."""
    latest_records = get_latest_climate_data('api_table')
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
        
    db_data = latest_records[0]
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    
    if latest_ventilation_table and latest_ventilation_table[0].get('status_ventilation'):
        status_ventilation_table = latest_ventilation_table[0]
        vent_start_id = status_ventilation_table.get('ventilation_start')
        before_records = get_latest_climate_data('api_table', vent_start_id, vent_start_id) if vent_start_id else []
        vent_before = before_records[0] if before_records else dict(db_data)
        vent_active = True
        vent_start_time = vent_before.get('timestamp', db_data.get('timestamp', '—')) 
        vent_now_time = db_data.get('timestamp', '—')            
    else:
        vent_active = False
        vent_before = dict(db_data)
        vent_start_time = db_data.get('timestamp', '—')
        vent_now_time = db_data.get('timestamp', '—')

    # Безопасное вычисление разницы показателей
    def safe_diff(val1, val2):
        if val1 is not None and val2 is not None:
            return float(val1) - float(val2)
        return 0.0

    diffs = {
        'diff_basement_temp': safe_diff(db_data.get('basement_temp'), vent_before.get('basement_temp')),
        'diff_basement_humi': safe_diff(db_data.get('basement_humi'), vent_before.get('basement_humi')),
        'diff_a_basement_humi': safe_diff(db_data.get('a_basement_humi'), vent_before.get('a_basement_humi')),
        'diff_floor_temp': safe_diff(db_data.get('floor_temp'), vent_before.get('floor_temp')),
        'diff_floor_humi': safe_diff(db_data.get('floor_humi'), vent_before.get('floor_humi')),
        'diff_a_floor_humi': safe_diff(db_data.get('a_floor_humi'), vent_before.get('a_floor_humi')),
    }

    # Классы стилей для изменений
    style_classes = {
        'diff_basement_temp_class': "text-blue" if abs(diffs['diff_basement_temp']) > 0.1 else "text-gray",
        "diff_basement_humi_class": "text-green" if diffs['diff_basement_humi'] < -0.5 else "text-red" if diffs['diff_basement_humi'] > 0.5 else "text-gray",
        "diff_a_basement_humi_class": "text-green" if diffs['diff_a_basement_humi'] < -0.1 else "text-red" if diffs['diff_a_basement_humi'] > 0.1 else "text-gray",
        "diff_floor_temp_class": "text-blue" if abs(diffs['diff_floor_temp']) > 0.1 else "text-gray",
        "diff_floor_humi_class": "text-green" if diffs['diff_floor_humi'] < -0.5 else "text-red" if diffs['diff_floor_humi'] > 0.5 else "text-gray",
        "diff_a_floor_humi_class": "text-green" if diffs['diff_a_floor_humi'] < -0.1 else "text-red" if diffs['diff_a_floor_humi'] > 0.1 else "text-gray",
    }

    # Настройка состояния кнопок
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

    # Форматирование времени (чч:мм)
    vent_start_str = vent_start_time[11:16] if len(str(vent_start_time)) >= 16 else str(vent_start_time)
    vent_now_str = vent_now_time[11:16] if len(str(vent_now_time)) >= 16 else str(vent_now_time)

    context = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "vent_start_time": vent_start_str,
        "vent_now_time": vent_now_str,
        **db_data,
        **before_data,
        **diffs,
        **style_classes
    }

    return templates.TemplateResponse(request=request, name="ventilation.html", context=context)

@app.post("/api/ventilation/start")
async def start_ventilation():
    """Запись старта проветривания в БД с привязкой ID и timestamp из api_table."""
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    
    can_start = True
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table.get('status_ventilation'): 
            can_start = False

    if can_start:
        latest_records = get_latest_climate_data('api_table')
        if latest_records: 
            api_on_db['status_ventilation'] = True      
            api_on_db['timestamp'] = latest_records[0]['timestamp']
            api_on_db['ventilation_start'] = latest_records[0]['id']
            api_on_db['stop_ventilation'] = 0
            write_climate_data('ventilation_table', api_on_db)
            api_log.info(f"[БД] Успешный старт проветривания: api_id={api_on_db['ventilation_start']}, timestamp={api_on_db['timestamp']}")
        else:
            api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/ventilation", status_code=303)


@app.post("/api/ventilation/stop")
async def stop_ventilation():
    """Запись остановки проветривания в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_ventilation_table = get_latest_climate_data('ventilation_table')
    if latest_ventilation_table:
        status_ventilation_table = latest_ventilation_table[0]
        if status_ventilation_table.get('status_ventilation'):
            latest_records = get_latest_climate_data('api_table')
            if latest_records:
                api_on_db['timestamp'] = status_ventilation_table.get('timestamp')
                api_on_db['status_ventilation'] = False
                api_on_db['ventilation_start'] = status_ventilation_table.get('ventilation_start')
                api_on_db['stop_ventilation'] = latest_records[0]['id']
                write_climate_data('ventilation_table', api_on_db, row_id=status_ventilation_table.get('id'))
                api_log.info(f"[БД] Успешный стоп проветривания: api_id={api_on_db['stop_ventilation']}")
            else:
                api_log.warning("На сервер не приходят значения из базы данных") 

    return RedirectResponse(url="/ventilation", status_code=303)

@app.get("/heating", response_class=HTMLResponse)
async def get_heating_page(request: Request):
    """Страница ручного управления отоплением и сравнительной таблицы."""
    latest_records = get_latest_climate_data('api_table')
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных")
        return get_no_data_response(request)
        
    db_data = latest_records[0]
    latest_heating_table = get_latest_climate_data("heating_table")
    
    if latest_heating_table and latest_heating_table[0].get("stop_heating") == 0:
        status_heating_table = latest_heating_table[0]
        heat_start_id = status_heating_table.get("heating_start")
        before_records = get_latest_climate_data('api_table', heat_start_id, heat_start_id) if heat_start_id else []
        heat_before = before_records[0] if before_records else dict(db_data)
        heat_active = True
        heat_start_time = heat_before.get('timestamp', db_data.get('timestamp', '—'))
        heat_now_time = db_data.get('timestamp', '—')
    else:
        heat_active = False
        heat_before = dict(db_data)
        heat_start_time = db_data.get('timestamp', '—')
        heat_now_time = db_data.get('timestamp', '—')

    def safe_diff(val1, val2):
        if val1 is not None and val2 is not None:
            return float(val1) - float(val2)
        return 0.0

    diffs = {
        'diff_basement_temp': safe_diff(db_data.get('basement_temp'), heat_before.get('basement_temp')),
        'diff_basement_humi': safe_diff(db_data.get('basement_humi'), heat_before.get('basement_humi')),
        'diff_floor_temp': safe_diff(db_data.get('floor_temp'), heat_before.get('floor_temp')),
        'diff_floor_humi': safe_diff(db_data.get('floor_humi'), heat_before.get('floor_humi'))
    }

    style_classes = {
        'diff_basement_temp_class': "text-green" if diffs['diff_basement_temp'] > 0.1 else "text-red" if diffs['diff_basement_temp'] < -0.1 else "text-gray",
        "diff_basement_humi_class": "text-green" if diffs['diff_basement_humi'] < -0.5 else "text-red" if diffs['diff_basement_humi'] > 0.5 else "text-gray",
        "diff_floor_temp_class": "text-green" if diffs['diff_floor_temp'] > 0.1 else "text-red" if diffs['diff_floor_temp'] < -0.1 else "text-gray",
        "diff_floor_humi_class": "text-green" if diffs['diff_floor_humi'] < -0.5 else "text-red" if diffs['diff_floor_humi'] > 0.5 else "text-gray"
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

    heat_start_str = heat_start_time[11:16] if len(str(heat_start_time)) >= 16 else str(heat_start_time)
    heat_now_str = heat_now_time[11:16] if len(str(heat_now_time)) >= 16 else str(heat_now_time)

    context = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "btn_start_class": btn_start_class,
        "btn_stop_class": btn_stop_class,
        "btn_start_disabled": btn_start_disabled,
        "btn_stop_disabled": btn_stop_disabled,
        "heat_start_time": heat_start_str,
        "heat_now_time": heat_now_str,
        **db_data,
        **before_data,
        **diffs,
        **style_classes
    }

    return templates.TemplateResponse(request=request, name="heating.html", context=context)

@app.post("/api/heating/start")
async def start_heating():
    """Запись старта отопления в БД с привязкой ID и timestamp из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data('heating_table')
    is_heating_active = False
    
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table.get('stop_heating') == 0:
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
            api_log.warning("На сервер не приходят значения из базы данных")

    return RedirectResponse(url="/heating", status_code=303)

@app.post("/api/heating/stop")
async def stop_heating():
    """Запись остановки отопления в БД с фиксацией ID текущей записи из api_table."""
    api_on_db = {}
    latest_heating_table = get_latest_climate_data('heating_table')
    if latest_heating_table:
        status_heating_table = latest_heating_table[0]
        if status_heating_table.get('stop_heating') == 0:
            latest_records = get_latest_climate_data('api_table')
            if latest_records:
                api_on_db['timestamp'] = status_heating_table.get('timestamp')
                api_on_db['heating_start'] = status_heating_table.get('heating_start')
                api_on_db['stop_heating'] = latest_records[0]['id']
                write_climate_data('heating_table', api_on_db, row_id=status_heating_table.get('id'))
                api_log.info(f"[БД] Успешный стоп отопления: api_id={api_on_db['stop_heating']}")
            else:
                api_log.warning("На сервер не приходят значения из базы данных") 
                
    return RedirectResponse(url="/heating", status_code=303)

@app.get("/gas", response_class=HTMLResponse)
async def get_gas_page(request: Request):
    """Страница ввода и отображения показаний счетчика газа."""
    latest_records = get_latest_climate_data('api_table')
    if not latest_records:
        api_log.warning("На сервер не приходят значения из базы данных для страницы газа")
        return get_no_data_response(request)
        
    db_data = latest_records[0]
    gas_val = db_data.get('gas_meter')
    
    gas_display = f"{gas_val:.3f} м³" if gas_val is not None else "Не установлено"
    gas_input_val = f"{gas_val:.3f}" if gas_val is not None else ""
    
    context = {
        "website_return_time": config.WEBSITE_RETURN_TIME,
        "current_gas": gas_display,
        "gas_input_value": gas_input_val,
        "timestamp": db_data.get('timestamp', '—')
    }

    return templates.TemplateResponse(request=request, name="gas.html", context=context)

@app.post("/api/gas/update")
async def update_gas_meter(request: Request):
    """Обновление показаний счетчика газа в последней строке таблиц api_table и table_sensor_data."""
    body = await request.body()
    parsed_data = parse_qs(body.decode("utf-8"))
    gas_meter_val = parsed_data.get('gas_meter')

    if not gas_meter_val:
        api_log.warning("В запросе отсутствует поле gas_meter")
        return RedirectResponse(url="/gas", status_code=303)

    try:
        gas_meter = float(gas_meter_val[0])
    except ValueError:
        api_log.warning("Не удалось преобразовать значение gas_meter в число с плавающей точкой")
        return RedirectResponse(url="/gas", status_code=303)

    latest_api = get_latest_climate_data('api_table')
    if latest_api:
        last_api_id = latest_api[0]['id']
        latest_api[0]['gas_meter'] = gas_meter
        write_climate_data('api_table', latest_api[0], row_id=last_api_id)
        api_log.info(f"[БД] Успешно обновлен счетчик газа в api_table (id={last_api_id}): {gas_meter}")
    else:
        api_log.warning("api_table пуста, не удалось обновить счетчик газа")
        
    latest_sensor = get_latest_climate_data('table_sensor_data')
    if latest_sensor:
        last_sensor_id = latest_sensor[0]['id']
        latest_sensor[0]['gas_meter'] = gas_meter
        write_climate_data('table_sensor_data', latest_sensor[0], row_id=last_sensor_id)
        api_log.info(f"[БД] Успешно обновлен счетчик газа в table_sensor_data (id={last_sensor_id}): {gas_meter}")
    else:
        api_log.warning("table_sensor_data пуста, не удалось обновить счетчик газа")

    return RedirectResponse(url="/gas", status_code=303)