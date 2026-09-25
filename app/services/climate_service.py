# app/services/climate_service.py

import math
from typing import Dict, Any, Tuple


def calculate_absolute_humidity(temp: float | None, humi: float | None) -> float:
    """Расчет абсолютной влажности (г/м³)."""
    if temp is None or humi is None:
        return 0.0
    try:
        es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
        e = es * (humi / 100.0)
        ah = (216.7 * e) / (temp + 273.15)
        return round(ah, 2)
    except Exception:
        return 0.0


def calculate_dew_point(temp: float | None, humi: float | None) -> float:
    """Расчет точки росы (°C)."""
    if temp is None or humi is None or humi <= 0:
        return 0.0
    try:
        a = 17.27
        b = 237.7
        alpha = ((a * temp) / (b + temp)) + math.log(humi / 100.0)
        dp = (b * alpha) / (a - alpha)
        return round(dp, 2)
    except Exception:
        return 0.0


def calculate_relative_humidity(temp: float | None, ah: float | None) -> float:
    """Обратный расчет относительной влажности (%)."""
    if temp is None or ah is None or temp <= -273.15 or ah <= 0:
        return 0.0
    try:
        es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
        if es == 0:
            return 0.0
        e = (ah * (temp + 273.15)) / 216.7
        rh = (e / es) * 100.0
        return min(100.0, max(0.0, round(rh, 2)))
    except Exception:
        return 0.0


def calculating_temperature_from_humidity(temp: float, ah: float, target_rh: float) -> Tuple[float, float]:
    """Расчет догрева воздуха (°C) для достижения target_rh."""
    temp_heated = round(temp, 1)
    delta = 0.0
    for _ in range(300):
        rh = calculate_relative_humidity(temp_heated, ah)
        if rh <= target_rh:
            break
        temp_heated += 0.1
        delta += 0.1
    return round(temp_heated, 1), round(delta, 1)


def build_sensor_record(
    raw_ble_data: Dict[str, Any],
    sys_settings: Any,
    avg_diff_temp: float = 0.0
) -> Dict[str, Any]:
    """Формирует запись строго под схему таблицы 'table_sensor_data'."""
    mode = getattr(sys_settings, "mode", "BASEMENT_STREET_FLOOR")
    t_floor_mac_diff = getattr(sys_settings, "t_floor_mac_diff", 0.0)

    data = {
        "timestamp": raw_ble_data.get("timestamp"),
        "street_temp": raw_ble_data.get("street_temp"),
        "basement_temp": raw_ble_data.get("basement_temp"),
        "floor_temp": raw_ble_data.get("floor_temp"),
        "street_humi": raw_ble_data.get("street_humi"),
        "basement_humi": raw_ble_data.get("basement_humi"),
        "floor_humi": raw_ble_data.get("floor_humi"),
        "street_voltage": raw_ble_data.get("street_voltage", 0.0),
        "basement_voltage": raw_ble_data.get("basement_voltage", 0.0),
        "floor_voltage": raw_ble_data.get("floor_voltage", 0.0),
        "sensor_or_calc_street": raw_ble_data.get("sensor_or_calc_street", True),
        "sensor_or_calc_basement": raw_ble_data.get("sensor_or_calc_basement", True),
        "sensor_or_calc_floor": raw_ble_data.get("sensor_or_calc_floor", True),
        "difference_temp": 0.0,
        "average_temp": avg_diff_temp
    }

    b_temp = data["basement_temp"]
    b_humi = data["basement_humi"]

    # TODO: Доделать обработку отсутствия датчиков подвала и пола (подстановка предыдущих значений из базы)
    if b_temp is None and data["floor_temp"] is None:
        data["sensor_or_calc_basement"] = False
        data["sensor_or_calc_floor"] = False
        return data

    if mode == "BASEMENT_STREET":
        if b_temp is not None and b_humi is not None:
            data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
            abs_b = calculate_absolute_humidity(b_temp, b_humi)
            data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
            data["floor_voltage"] = 0.0
            data["difference_temp"] = t_floor_mac_diff
            data["sensor_or_calc_basement"] = True
            data["sensor_or_calc_floor"] = False

    elif mode in ["BASEMENT_STREET_FLOOR", "BASEMENT_FLOOR"]:
        if b_temp is not None and data["floor_temp"] is not None:
            data["difference_temp"] = round(b_temp - data["floor_temp"], 2)
            data["sensor_or_calc_basement"] = True
            data["sensor_or_calc_floor"] = True
        elif b_temp is not None:
            data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
            abs_b = calculate_absolute_humidity(b_temp, b_humi)
            data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
            data["floor_voltage"] = 0.0
            data["difference_temp"] = round(b_temp - data["floor_temp"], 2)
            data["sensor_or_calc_basement"] = True
            data["sensor_or_calc_floor"] = False

    else:  # BASEMENT
        if b_temp is not None and b_humi is not None:
            data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
            abs_b = calculate_absolute_humidity(b_temp, b_humi)
            data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
            data["floor_voltage"] = 0.0
            data["difference_temp"] = t_floor_mac_diff
            data["average_temp"] = t_floor_mac_diff
            data["sensor_or_calc_basement"] = True
            data["sensor_or_calc_floor"] = False

    return data


def build_api_record(
    sensor_data: Dict[str, Any],
    row_id: int,
    sys_settings: Any
) -> Dict[str, Any]:
    """Формирует запись строго под схему таблицы 'api_table'."""
    abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)
    target_rh = getattr(sys_settings, "target_rh", 60.0)

    s_temp = sensor_data.get("street_temp", 0.0) or 0.0
    s_humi = sensor_data.get("street_humi", 0.0) or 0.0
    b_temp = sensor_data.get("basement_temp", 0.0) or 0.0
    b_humi = sensor_data.get("basement_humi", 0.0) or 0.0
    f_temp = sensor_data.get("floor_temp", 0.0) or 0.0
    f_humi = sensor_data.get("floor_humi", 0.0) or 0.0

    a_street = calculate_absolute_humidity(s_temp, s_humi)
    a_basement = calculate_absolute_humidity(b_temp, b_humi)
    a_floor = calculate_absolute_humidity(f_temp, f_humi)

    dp_street = calculate_dew_point(s_temp, s_humi)
    dp_basement = calculate_dew_point(b_temp, b_humi)
    dp_floor = calculate_dew_point(f_temp, f_humi)

    humidity_diff = round(a_basement - a_street, 2)

    if humidity_diff >= abs_tolerance:
        vent_status = True
        temp_diff = abs(b_temp - s_temp)
        vent_time_val = round(10.4 / math.sqrt(temp_diff)) if temp_diff > 0 else 0
    else:
        vent_status = False
        vent_time_val = 0

    sim_a_basement_humi = a_street
    sim_basement_humi = calculate_relative_humidity(b_temp, sim_a_basement_humi)
    sim_floor_humi = calculate_relative_humidity(f_temp, sim_a_basement_humi)

    if vent_status and sim_floor_humi > target_rh:
        floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_street, target_rh)
        heat_status = True
        basement_temp_heated = round(b_temp + heating_delta, 1)
        basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_street)
        a_basement_humi_heated = a_street
        floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_street)
        a_floor_humi_heated = a_street
    elif not vent_status and f_humi > target_rh:
        floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_floor, target_rh)
        heat_status = True
        basement_temp_heated = round(b_temp + heating_delta, 1)
        basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_basement)
        a_basement_humi_heated = a_basement
        floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_basement)
        a_floor_humi_heated = a_basement
    else:
        heat_status = False
        heating_delta = 0.0
        floor_temp_heated = f_temp
        basement_temp_heated = b_temp
        basement_humi_heated = b_humi
        a_basement_humi_heated = a_basement
        floor_humi_heated = f_humi
        a_floor_humi_heated = a_floor

    return {
        "id": row_id,
        "timestamp": sensor_data.get("timestamp"),
        "a_floor_humi": a_floor,
        "dp_floor": dp_floor,
        "a_street_humi": a_street,
        "dp_street": dp_street,
        "a_basement_humi": a_basement,
        "dp_basement": dp_basement,
        "humidity_difference": humidity_diff,
        "vent_status": vent_status,
        "vent_time_val": vent_time_val,
        "sim_a_basement_humi": sim_a_basement_humi,
        "sim_basement_humi": sim_basement_humi,
        "sim_floor_humi": sim_floor_humi,
        "heating_delta": heating_delta,
        "heat_status": heat_status,
        "floor_temp_heated": floor_temp_heated,
        "basement_temp_heated": basement_temp_heated,
        "basement_humi_heated": basement_humi_heated,
        "a_basement_humi_heated": a_basement_humi_heated,
        "floor_humi_heated": floor_humi_heated,
        "a_floor_humi_heated": a_floor_humi_heated,
        "last_graph_sensor_id": 0
    }