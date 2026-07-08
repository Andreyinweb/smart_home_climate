import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import config
import operations

app = FastAPI(title="Smart Home Climate API")

# Глобальный разделяемый словарь с последними сырыми данными опроса
shared_data = {
    "A4:C1:38:53:82:0F": {"temp": 0.7, "humi": 5.0, "voltage": 1}, # Улица
    "A4:C1:38:51:C3:0D": {"temp": 0.2, "humi": 5.0, "voltage": 1}, # Подвал
    "A4:C1:38:10:3B:D1": {"temp": 0.48, "humi": 5.0, "voltage": 1}  # Спальня
}

@app.get("/api/data")
async def get_raw_data():
    """Получение сырых данных в формате JSON."""
    return shared_data

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Сборка дашборда на основе физических расчетов и шаблона HTML."""
    # Получение параметров из разделяемого кэша датчиков
    u_data = shared_data.get("A4:C1:38:53:82:0F", {"temp": 0.0, "humi": 0.0, "voltage": 0.0})
    p_data = shared_data.get("A4:C1:38:51:C3:0D", {"temp": 0.0, "humi": 0.0, "voltage": 0.0})
    s_data = shared_data.get("A4:C1:38:10:3B:D1", {"temp": 0.0, "humi": 0.0, "voltage": 0.0})

    t_street, h_street = u_data["temp"], u_data["humi"]
    t_cellar, h_cellar = p_data["temp"], p_data["humi"]

    # Динамический расчет температуры самого холодного угла пола подвала
    t_floor = t_cellar - config.T_FLOOR_DIFF

    # Расчеты текущего состояния
    ah_street = operations.calculate_absolute_humidity(t_street, h_street)
    ah_cellar = operations.calculate_absolute_humidity(t_cellar, h_cellar)
    h_floor_calc = operations.calculate_relative_humidity(t_floor, ah_cellar)
    ah_floor_calc = operations.calculate_absolute_humidity(t_floor, h_floor_calc)

    # Расчеты вентиляции
    vent_status, vent_reason = operations.analyze_ventilation(t_street, ah_street, t_cellar, ah_cellar)
    vent_class = "bg-green-100 text-green-800" if vent_status == "ДА" else "bg-red-100 text-red-800"
    
    sim_ah_cellar = ah_street
    sim_h_cellar = operations.calculate_relative_humidity(t_cellar, sim_ah_cellar)
    sim_h_floor = operations.calculate_relative_humidity(t_floor, sim_ah_cellar)

    # Расчеты отопления
    heating_needed, heating_delta = operations.analyze_heating(t_cellar, ah_cellar, config.T_FLOOR_DIFF, config.TARGET_RH)
    heat_status = "ДА" if heating_needed else "НЕТ"
    heat_info = f"{heating_delta} °C." if heating_needed else ""
    heat_class = "bg-amber-100 text-amber-800" if heating_needed else "bg-gray-100 text-gray-700"

    t_cellar_heated = t_cellar + heating_delta
    h_cellar_heated = operations.calculate_relative_humidity(t_cellar_heated, ah_cellar)
    
    t_floor_heated = t_floor + heating_delta
    h_floor_heated = operations.calculate_relative_humidity(t_floor_heated, ah_cellar)

    # Чтение шаблона разметки
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        return HTMLResponse("Ошибка: Файл шаблона index.html не найден.", status_code=500)

    # Форматирование шаблона расчетными данными
    rendered_html = template.format(
        v_bedroom=s_data.get("voltage", 0.0),
        v_street=u_data.get("voltage", 0.0),
        v_cellar=p_data.get("voltage", 0.0),
        t_street=t_street,
        h_street=h_street,
        ah_street=ah_street,
        t_cellar=t_cellar,
        h_cellar=h_cellar,
        ah_cellar=ah_cellar,
        t_floor=t_floor,
        h_floor_calc=h_floor_calc,
        ah_floor_calc=ah_floor_calc,
        vent_status=vent_status,
        vent_reason=vent_reason,
        vent_class=vent_class,
        sim_h_cellar=sim_h_cellar,
        sim_h_floor=sim_h_floor,
        sim_ah_cellar=sim_ah_cellar,
        heat_status=heat_status,
        heat_info=heat_info,
        heat_class=heat_class,
        t_cellar_heated=t_cellar_heated,
        h_cellar_heated=h_cellar_heated,
        t_floor_heated=t_floor_heated,
        h_floor_heated=h_floor_heated
    )

    return HTMLResponse(rendered_html)