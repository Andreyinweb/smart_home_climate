import math
from typing import Tuple

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

def analyze_heating(basement_temp: float, a_basement_humi: float, floor_temp_diff: float, target_rh: float) -> Tuple[bool, float]:
    """
    Определение необходимости и расчет дельты компенсационного подогрева воздуха в подвале,
    чтобы влажность в самом холодном углу пола опустилась до целевого значения.
    """
    floor_temp = basement_temp - floor_temp_diff
    currenfloor_temp_rh = calculate_relative_humidity(floor_temp, a_basement_humi)
    if currenfloor_temp_rh <= target_rh:
        return False, 0.0
    
    # Итерационный подбор необходимой дельты нагрева с шагом 0.1 °C
    for delta in [x * 0.1 for x in range(1, 150)]:
        sim_basement_temp_heated = basement_temp + delta
        sim_floor_temp_heated = sim_basement_temp_heated - floor_temp_diff
        rh_at_heated_floor = calculate_relative_humidity(sim_floor_temp_heated, a_basement_humi)
        if rh_at_heated_floor <= target_rh:
            return True, round(delta, 1)
            
    return True, 0.0