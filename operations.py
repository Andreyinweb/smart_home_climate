import math
from typing import Tuple
from settings import config
import logging
import models

work_log = logging.getLogger("climat_app.operations")

def settings_in_db():    
    latest_settings = models.get_latest_climate_data('settings_table')
    if latest_settings:
        settings_in_db = latest_settings[0]
        DATE_SETINGS = settings_in_db['timestamp'] # 0
        MODE = settings_in_db['mode']              # 1
        INTERVAL_SECONDS = settings_in_db['interval_seconds'] # 2
        WEBSITE_RETURN_TIME = settings_in_db['website_return_time'] # 3
        MAX_RETRIES = settings_in_db['max_retries'] # 4
        T_FLOOR_MAC_DIFF = settings_in_db['t_floor_mac_diff'] # 5
        ABSOLUTE_HUMIDITY_TOLERANCE = settings_in_db['absolute_humidity_tolerance'] # 6
        MINIMUM_HUMIDITY = settings_in_db['minimum_humidity'] # 7
        TARGET_RH = settings_in_db['target_rh']  # 8
        DANGEROUS_HUMIDITY =settings_in_db['dangerous_humidity'] # 9
    else:
        work_log.error("Невозможно получить данные из базы settings_table.")
        exit(1)

    return (DATE_SETINGS, MODE, INTERVAL_SECONDS, WEBSITE_RETURN_TIME,
             MAX_RETRIES, T_FLOOR_MAC_DIFF, ABSOLUTE_HUMIDITY_TOLERANCE, 
             MINIMUM_HUMIDITY, TARGET_RH, DANGEROUS_HUMIDITY)

def calculate_absolute_humidity(temp: float, humi: float) -> float:
    """
    Расчет абсолютной влажности (г/м³) по формуле Магнуса-Тетенса.
    """
    if temp is None or humi is None:
        return 0.0
    # Насыщенное давление пара (hPa)
    es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
    # Фактическое давление пара (hPa)
    e = es * (humi / 100.0)
    # Вычисление абсолютной влажности (г/м³)
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
    if temp is None or ah is None or temp < -273.15:
        return 0.0
    es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
    e = (ah * (temp + 273.15)) / 216.7
    rh = (e / es) * 100.0
    return min(100.0, max(0.0, round(rh, 2)))

def analyze_ventilation(street_temp: float, a_street_humi: float, basement_temp: float, a_basement_humi: float) -> Tuple[str, str]:
    """
    Анализ возможности и безопасности проветривания.
    """
    is_safe = a_street_humi < a_basement_humi
    has_draft = basement_temp > street_temp
    
    if is_safe and has_draft:
        return "ДА", "Условия оптимальны."
    elif not is_safe:
        return "НЕТ", "Влага пойдет (конденсат)."
    else:
        return "НЕТ", "Тяги нет."

def calculating_temperature_from_humidity(temp: float, ah: float):
    """
    Расчет температуры отопления.
    """
    TARGET_RH = settings_in_db()[8]
    temp_heating = round(temp,1)
    for delta in range(1, 300):
        relative_humidity = calculate_relative_humidity(temp_heating, ah)
        if relative_humidity < TARGET_RH:
            break
        temp_heating = temp_heating + delta * 0.1
    
    return temp_heating, round(delta*0.1, 1)

