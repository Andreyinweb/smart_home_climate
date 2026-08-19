import math
import statistics
from typing import Tuple, List
import calendar
from datetime import datetime, timedelta
import logging
import models

work_log = logging.getLogger("climat_app.operations")

def settings_in_db():    
    latest_settings = models.get_latest_climate_data('settings_table')
    if latest_settings:
        settings_in_db = latest_settings[0]
        DATE_SETINGS = settings_in_db['timestamp']
        MODE = settings_in_db['mode']
        INTERVAL_SECONDS = settings_in_db['interval_seconds']
        WEBSITE_RETURN_TIME = settings_in_db['website_return_time']
        MAX_RETRIES = settings_in_db['max_retries']
        T_FLOOR_MAC_DIFF = settings_in_db['t_floor_mac_diff']
        ABSOLUTE_HUMIDITY_TOLERANCE = settings_in_db['absolute_humidity_tolerance']
        MINIMUM_HUMIDITY = settings_in_db['minimum_humidity']
        TARGET_RH = settings_in_db['target_rh']
        DANGEROUS_HUMIDITY = settings_in_db['dangerous_humidity']
        PRICE_GAS = settings_in_db['price_gas']
    else:
        work_log.error("Невозможно получить данные из базы settings_table.")
        exit(1)

    return (DATE_SETINGS, MODE, INTERVAL_SECONDS, WEBSITE_RETURN_TIME,
             MAX_RETRIES, T_FLOOR_MAC_DIFF, ABSOLUTE_HUMIDITY_TOLERANCE, 
             MINIMUM_HUMIDITY, TARGET_RH, DANGEROUS_HUMIDITY, PRICE_GAS)

def calculate_absolute_humidity(temp: float, humi: float) -> float:
    """
    Расчет абсолютной влажности (г/м³) по формуле Магнуса-Тетенса.
    """
    if temp is None or humi is None:
        return 0.0
    es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
    e = es * (humi / 100.0)
    ah = (216.7 * e) / (temp + 273.15)
    return round(ah, 2)

def calculate_dew_point(temp: float, humi: float) -> float:
    """Расчет точки росы (°C) по формуле Магнуса."""
    if temp is None or humi is None or humi == 0:
        return 0.0
    a = 17.27
    b = 237.7
    alpha = ((a * temp) / (b + temp)) + math.log(humi / 100.0)
    dp = (b * alpha) / (a - alpha)
    return round(dp, 2)

def calculate_relative_humidity(temp: float, ah: float) -> float:
    """
    Обратный расчет относительной влажности (%) по температуре и абсолютной влажности.
    """
    if temp is None or ah is None or temp < -273.15 or ah <= 0:
        return 0.0
    es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
    if es == 0:
        return 0.0
    e = (ah * (temp + 273.15)) / 216.7
    rh = (e / es) * 100.0
    return min(100.0, max(0.0, round(rh, 2)))

def calculate_median(values: List[float]) -> float:
    """Вычисляет медианное значение списка чисел."""
    if not values:
        return 0.0
    return float(statistics.median(values))

def calculate_winter_climate(
    site_temp: float,
    site_ah: float,
    delta_temp: float,
    delta_ah: float
) -> Tuple[float, float, float]:
    """
    Вычисляет расчетную уличную температуру (T), абсолютную влажность (AH) и относительную влажность (RH)
    для зимнего периода без уличного датчика.
    """
    temp_calc = round(site_temp + delta_temp, 2)
    ah_calc = max(0.0001, round(site_ah + delta_ah, 4))
    rh_calc = calculate_relative_humidity(temp_calc, ah_calc)
    return temp_calc, ah_calc, rh_calc

def analyze_ventilation(street_temp: float, a_street_humi: float, basement_temp: float, a_basement_humi: float) -> Tuple[str, str]:
    """Анализ возможности и безопасности проветривания."""
    is_safe = a_street_humi < a_basement_humi
    has_draft = basement_temp > street_temp
    
    if is_safe and has_draft:
        return "ДА", "Условия оптимальны."
    elif not is_safe:
        return "НЕТ", "Влага пойдет (конденсат)."
    else:
        return "НЕТ", "Тяги нет."

def calculating_temperature_from_humidity(temp: float, ah: float):
    """Расчет температуры отопления."""
    TARGET_RH = settings_in_db()[8]
    temp_heating = round(temp, 1)
    delta = 0
    for delta in range(0, 300):
        relative_humidity = calculate_relative_humidity(temp_heating, ah)
        if relative_humidity < TARGET_RH:
            break
        temp_heating = temp_heating + 0.1
    
    return temp_heating, round(delta * 0.1, 1)

def coefficient_gas(street_temp: float, basement_temp: float, gas_difference: float, timestamp: str) -> float:
    """Расчет коэффициента расхода газа."""
    if street_temp is None or basement_temp is None or gas_difference is None or timestamp is None:
        return 0.0

    temp_diff = abs(basement_temp - street_temp)
    if temp_diff == 0:
        return 0.0

    try:
        dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return 0.0

    hours_passed = (dt.day - 1) * 24 + dt.hour + dt.minute / 60 + dt.second / 3600

    if hours_passed == 0:
        return 0.0

    days_in_month = calendar.monthrange(dt.year, dt.month)[1]

    gas_per_hour = gas_difference / hours_passed
    gas_per_month = gas_per_hour * 24 * days_in_month

    coefficient = round(gas_per_month / temp_diff, 3)
    return coefficient

def get_time_difference_str(start_str: str, end_str: str, fmt: str = "%H:%M") -> str:
    t_start = datetime.strptime(start_str, fmt)
    t_end = datetime.strptime(end_str, fmt)
    
    diff = t_end - t_start
    if diff.total_seconds() < 0:
        diff += timedelta(days=1)
        
    total_minutes = int(diff.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    return f"{hours}:{minutes:02d}"