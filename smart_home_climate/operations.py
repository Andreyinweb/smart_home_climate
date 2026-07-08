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

def analyze_ventilation(t_street: float, ah_street: float, t_cellar: float, ah_cellar: float) -> Tuple[str, str]:
    """
    Анализ возможности и безопасности проветривания.
    """
    is_safe = ah_street < ah_cellar
    has_draft = t_cellar > t_street
    
    if is_safe and has_draft:
        return "ДА", "Условия оптимальны."
    elif not is_safe:
        return "НЕТ", "Влага пойдет (конденсат)."
    else:
        return "НЕТ", "Тяги нет."

def analyze_heating(t_cellar: float, ah_cellar: float, t_floor_diff: float, target_rh: float) -> Tuple[bool, float]:
    """
    Определение необходимости и расчет дельты компенсационного подогрева воздуха в подвале,
    чтобы влажность в самом холодном углу пола опустилась до целевого значения.
    """
    t_floor = t_cellar - t_floor_diff
    current_floor_rh = calculate_relative_humidity(t_floor, ah_cellar)
    if current_floor_rh <= target_rh:
        return False, 0.0
    
    # Итерационный подбор необходимой дельты нагрева с шагом 0.1 °C
    for delta in [x * 0.1 for x in range(1, 150)]:
        sim_t_cellar_heated = t_cellar + delta
        sim_t_floor_heated = sim_t_cellar_heated - t_floor_diff
        rh_at_heated_floor = calculate_relative_humidity(sim_t_floor_heated, ah_cellar)
        if rh_at_heated_floor <= target_rh:
            return True, round(delta, 1)
            
    return True, 0.0