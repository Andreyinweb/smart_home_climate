import os
import math
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from settings import config, work_log
import operations
from models import get_latest_climate_data

app = FastAPI(title="Smart Home Climate API")

# Глобальный разделяемый словарь с последними данными опроса в едином формате
shared_data = {
    "street": {"temp": 0.0, "humi": 0.0, "voltage": 0.0}, 
    "basement": {"temp": 0.0, "humi": 0.0, "voltage": 0.0}, 
    "floor": {"temp": 0.0, "humi": 0.0, "voltage": 0.0},
    "difference_temp": 0.0,
    "average_temp": 0.0,
    "Date": ""
}

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
    print(f"latest_records: {latest_records}")  # TODO: Удалить после тестирования
    
    if latest_records:
        db_data = latest_records[0]
        
        # Безопасное получение значений с обработкой None (NULL в БД)
        t_street_raw = db_data.get("street_temp")
        t_street = float(t_street_raw) if t_street_raw is not None else 0.0
        
        h_street_raw = db_data.get("street_humi")
        h_street = float(h_street_raw) if h_street_raw is not None else 0.0
        
        v_street_raw = db_data.get("street_voltage")
        v_street = float(v_street_raw) if v_street_raw is not None else 0.0

        t_cellar_raw = db_data.get("basement_temp")
        t_cellar = float(t_cellar_raw) if t_cellar_raw is not None else 0.0
        
        h_cellar_raw = db_data.get("basement_humi")
        h_cellar = float(h_cellar_raw) if h_cellar_raw is not None else 0.0
        
        v_cellar_raw = db_data.get("basement_voltage")
        v_cellar = float(v_cellar_raw) if v_cellar_raw is not None else 0.0

        v_floor_raw = db_data.get("floor_voltage")
        v_floor = float(v_floor_raw) if v_floor_raw is not None else 0.0
        
        db_date = db_data.get("Date") or "Нет данных"

        # Обновляем shared_data в соответствии с новой структурой
        shared_data["street"] = {"temp": t_street, "humi": h_street, "voltage": v_street}
        shared_data["basement"] = {"temp": t_cellar, "humi": h_cellar, "voltage": v_cellar}
        
        t_floor_raw = db_data.get("floor_temp")
        t_floor_db = float(t_floor_raw) if t_floor_raw is not None else 0.0
        
        h_floor_raw = db_data.get("floor_humi")
        h_floor_db = float(h_floor_raw) if h_floor_raw is not None else 0.0

        shared_data["floor"] = {"temp": t_floor_db, "humi": h_floor_db, "voltage": v_floor}
        
        diff_temp_raw = db_data.get("difference_temp")
        shared_data["difference_temp"] = float(diff_temp_raw) if diff_temp_raw is not None else 0.0
        
        avg_temp_raw = db_data.get("average_temp")
        shared_data["average_temp"] = float(avg_temp_raw) if avg_temp_raw is not None else 0.0
        
        shared_data["Date"] = db_date

        # Вычисление параметров у пола в зависимости от режима MODE
        if config.MODE == "FLOOR":
            t_floor = t_floor_db
            h_floor_calc = h_floor_db
        else:
            t_floor = t_cellar - config.T_FLOOR_MAC_DIFF
            ah_cellar_temp = operations.calculate_absolute_humidity(t_cellar, h_cellar)
            h_floor_calc = operations.calculate_relative_humidity(t_floor, ah_cellar_temp)
    else:
        t_street, h_street, v_street = 0.0, 0.0, 0.0
        t_cellar, h_cellar, v_cellar = 0.0, 0.0, 0.0
        t_floor, h_floor_calc, v_floor = 0.0, 0.0, 0.0
        db_date = "База данных пуста"

    # Расчет абсолютных влажностей
    ah_street = operations.calculate_absolute_humidity(t_street, h_street)
    ah_cellar = operations.calculate_absolute_humidity(t_cellar, h_cellar)
    ah_floor_calc = operations.calculate_absolute_humidity(t_floor, h_floor_calc)

    # Расчет точек росы
    dp_street = calculate_dew_point(t_street, h_street)
    dp_cellar = calculate_dew_point(t_cellar, h_cellar)
    dp_floor = calculate_dew_point(t_floor, h_floor_calc)

    # Расчет проветривания с учетом абсолютной погрешности ABSOLUTE_HUMIDITY_TOLERANCE (0.5 г/м³)
    humidity_difference = round(ah_cellar - ah_street, 2)
    is_safe_ventilation = humidity_difference > config.ABSOLUTE_HUMIDITY_TOLERANCE
    has_draft = t_cellar > t_street

    if is_safe_ventilation and has_draft:
        vent_status = "ДА"
        try:
            vent_time_val = round(10.4 / math.sqrt(t_cellar - t_street))
            vent_reason = f"Время проветривания: {vent_time_val} мин."
        except (ZeroDivisionError, ValueError):
            vent_reason = "Время проветривания рассчитать не удалось."
    elif not is_safe_ventilation:
        vent_status = "НЕТ"
        vent_reason = "Влага пойдет (конденсат)."
    else:
        vent_status = "НЕТ"
        vent_reason = "Тяги нет."

    vent_class = "bg-green-100 text-green-800" if vent_status == "ДА" else "bg-red-100 text-red-800"

    # Моделирование замещения (Проветривание)
    sim_ah_cellar = ah_street
    sim_h_cellar = operations.calculate_relative_humidity(t_cellar, sim_ah_cellar)
    sim_h_floor = operations.calculate_relative_humidity(t_floor, sim_ah_cellar)

    # Расчет компенсационного нагрева (Отопление)
    heating_needed = h_floor_calc > config.TARGET_RH
    heating_delta = 0.0

    if heating_needed:
        for delta in [x * 0.1 for x in range(1, 150)]:
            sim_t_floor_heated = t_floor + delta
            rh_at_heated_floor = operations.calculate_relative_humidity(sim_t_floor_heated, ah_cellar)
            if rh_at_heated_floor <= config.TARGET_RH:
                heating_delta = round(delta, 1)
                break

    heat_status = "ДА" if heating_needed else "НЕТ"
    heat_info = f"+{heating_delta} °C" if heating_needed else ""
    heat_class = "bg-amber-100 text-amber-800" if heating_needed else "bg-gray-100 text-gray-700"

    # Итоговые параметры после догрева
    if heating_needed:
        t_cellar_heated = round(t_cellar + heating_delta, 1)
        h_cellar_heated = operations.calculate_relative_humidity(t_cellar_heated, ah_cellar)
        t_floor_heated = round(t_floor + heating_delta, 1)
        h_floor_heated = operations.calculate_relative_humidity(t_floor_heated, ah_cellar)
    else:
        t_cellar_heated = t_cellar
        h_cellar_heated = h_cellar
        t_floor_heated = t_floor
        h_floor_heated = h_floor_calc

    # Чтение шаблона разметки
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)

    # Форматирование шаблона расчетными данными с учетом WEBSITE_RETURN_TIME
    rendered_html = template.format(
        v_bedroom=v_floor,
        v_street=v_street,
        v_cellar=v_cellar,
        t_street=t_street,
        h_street=h_street,
        ah_street=ah_street,
        dp_street=dp_street,
        t_cellar=t_cellar,
        h_cellar=h_cellar,
        ah_cellar=ah_cellar,
        dp_cellar=dp_cellar,
        t_floor=t_floor,
        h_floor_calc=h_floor_calc,
        ah_floor_calc=ah_floor_calc,
        dp_floor=dp_floor,
        vent_status=vent_status,
        vent_reason=vent_reason,
        vent_class=vent_class,
        humidity_difference=humidity_difference,
        sim_h_cellar=sim_h_cellar,
        sim_h_floor=sim_h_floor,
        sim_ah_cellar=sim_ah_cellar,
        heat_status=heat_status,
        heat_info=heat_info,
        heat_class=heat_class,
        t_cellar_heated=t_cellar_heated,
        h_cellar_heated=h_cellar_heated,
        t_floor_heated=t_floor_heated,
        h_floor_heated=h_floor_heated,
        website_return_time=config.WEBSITE_RETURN_TIME,
        db_date=db_date,
        max_rh=config.TARGET_RH
    )

    return HTMLResponse(rendered_html)