import os
import math
import statistics
from typing import Tuple, List
import calendar
from datetime import datetime, timedelta
import logging
import models
from settings import config

work_log = logging.getLogger("climat_app.operations")
api_log = logging.getLogger("api_app.api")

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
        PRICE_GAS = settings_in_db['price_gas'] # 10
        HOT_WATER_PER_HOUR = settings_in_db['hot_water_per_hour'] # 11

    else:
        work_log.error("Невозможно получить данные из базы settings_table.")
        exit(1)

    return (DATE_SETINGS, MODE, INTERVAL_SECONDS, WEBSITE_RETURN_TIME,
             MAX_RETRIES, T_FLOOR_MAC_DIFF, ABSOLUTE_HUMIDITY_TOLERANCE, 
             MINIMUM_HUMIDITY, TARGET_RH, DANGEROUS_HUMIDITY, PRICE_GAS,HOT_WATER_PER_HOUR)

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


def create_backup(source_file, backup_dir, max_backups=100):
    try:
        if not os.path.isfile(source_file):
            raise FileNotFoundError(f"Файл не найден: {source_file}")

        os.makedirs(backup_dir, exist_ok=True)

        filename = os.path.basename(source_file)
        name, ext = os.path.splitext(filename)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = os.path.join(backup_dir, backup_name)

        with open(source_file, 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())

        prefix = f"{name}_"
        backups = [f for f in os.listdir(backup_dir) 
                 if f.startswith(prefix) and f.endswith(ext)]
        
        if len(backups) > max_backups - 1:
            backups.sort()
            for old_backup in backups[:-max_backups]:
                os.remove(os.path.join(backup_dir, old_backup))
                print(f"Удалён старый бэкап: {old_backup}")
        work_log.info(f"Резервная копия создана: {backup_path}")
        print(f"Резервная копия создана: {backup_path}")
        return backup_path

    except Exception as e:
        work_log.error(f"Ошибка при создании резервной копии: {e}")
        print(f"Ошибка: {e}")
        return None

################################################ ГАЗ  ###############################################
def calculate_hours_passed(timestamp: str) -> float:
    """Вычисляет количество часов, прошедших с начала месяца до указанного времени."""
    if not timestamp:
        return 0.0
    try:
        dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return 0.0

    hours_passed = (dt.day - 1) * 24 + dt.hour + dt.minute / 60 + dt.second / 3600

    if hours_passed <= 0:
        return 0.0
    else:
        return hours_passed
    

def get_days_in_month(timestamp: str) -> int:
    """Возвращает количество дней в месяце для указанного времени."""
    if not timestamp:
        return 0
    try:
        dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return 0    
    
    days_in_month = calendar.monthrange(dt.year, dt.month)[1]

    if days_in_month <= 0:
        return 0
    else:
        return days_in_month


def calc_gas_meter(gas_meter: float, start_of_month_gas=None, id_now=None)-> bool:
    """
    Обновляет данные счетчика газа в базе данных.
    
    :param gas_meter: Текущее значение счетчика газа.
    :param start_of_month_gas: Значение счетчика газа на начало месяца (опционально).
    """
    """ 
    id INTEGER , +
    timestamp TEXT NOT NULL,+
    gas_meter REAL,+
    start_of_month_gas_meter REAL,+
    gas_difference REAL,+
    average_street_temp REAL,+
    average_basement_temp REAL,+
    delta_T REAL,+
    coefficient_gas REAL,+
    gas_per_hour REAL, +
    gas_per_month REAL, + 
    hot_water_per_month REAL, +
    hot_water_per_hour REAL, +
    price_gas REAL, +
    cost_of_gas REAL, +
    gas_forecast REAL, 
    projected_price REAL 
    """

    gas_out_db = {}        
    latest_sensor = models.get_latest_climate_data("table_sensor_data", start_id=id_now, stop_id=id_now)
    if latest_sensor:
        gas_out_db["id"] = latest_sensor[0]["id"]
        gas_out_db['timestamp'] = latest_sensor[0]["timestamp"]

        latest_gas = models.get_latest_climate_data("gas_table", start_id=id_now, stop_id=id_now)
        # Определение значения начала месяца
        if latest_gas:
            if start_of_month_gas:
                gas_out_db['start_of_month_gas_meter'] = start_of_month_gas
            else:
                gas_out_db['start_of_month_gas_meter'] = latest_gas[0]["start_of_month_gas_meter"]

            if latest_gas[0]['gas_meter'] >= gas_meter or latest_gas[0]['start_of_month_gas_meter'] >= gas_meter or latest_gas[0]['id'] >= latest_sensor[0]["id"]:
                if not id_now:
                    api_log.info(f"[БД] Значение счетчика газа {latest_gas[0]['gas_meter']} в gas_table не изменилось: {gas_meter}")
                    return False
        else:
            gas_out_db['start_of_month_gas_meter'] = config.START_OF_MONTH_GAS_METER

      
        gas_out_db['gas_meter'] = gas_meter

        days_in_month = get_days_in_month(gas_out_db['timestamp'])
        gas_out_db['hot_water_per_hour'] = settings_in_db()[11]  # HOT_WATER_PER_HOUR
        gas_out_db['hot_water_per_month'] = round(gas_out_db['hot_water_per_hour'] * 24 * days_in_month, 3)        

        # Расчет разницы, коэффициента и стоимости
        gas_out_db['gas_difference'] = round(gas_meter - gas_out_db['start_of_month_gas_meter'], 3)

        average_street_temp = models.get_interval_average('table_sensor_data', 'street_temp', interval_type='month', target_time=latest_sensor[0]["timestamp"][0:7])
        average_basement_temp = models.get_interval_average('table_sensor_data', 'basement_temp', interval_type='month', target_time=latest_sensor[0]["timestamp"][0:7])

        gas_out_db['average_street_temp'] = average_street_temp
        gas_out_db['average_basement_temp'] = average_basement_temp
        gas_out_db['delta_T'] = round(average_basement_temp - average_street_temp, 2)
        gas_out_db['gas_per_hour'] = round((gas_out_db['gas_difference'] / calculate_hours_passed(gas_out_db['timestamp'])) - gas_out_db['hot_water_per_hour'], 3)
        
        if gas_out_db['gas_per_hour'] <= 0.0:
            gas_out_db['gas_per_hour'] = 0.0

        gas_out_db['gas_per_month'] = round(gas_out_db['gas_per_hour']* 24 * days_in_month, 3)

        gas_out_db['coefficient_gas'] = round(gas_out_db['gas_per_month'] / gas_out_db['delta_T'], 3)
        
        gas_out_db['price_gas'] = settings_in_db()[10]
        gas_out_db['cost_of_gas'] = round(gas_out_db['gas_difference'] * gas_out_db['price_gas'], 2)
        gas_out_db['gas_forecast'] = round(gas_out_db['gas_per_month'] + gas_out_db['hot_water_per_month'], 2)
        gas_out_db['projected_price'] = round(gas_out_db['gas_forecast'] * gas_out_db['price_gas'], 2)

        return gas_out_db

    else:
        api_log.warning("table_sensor_data пуста, не удалось обновить счетчик газа")
        return False

def calc_of_month_gas(start_of_month_gas:float)->bool:
    """
    Пересчёт базы данных
    """
    current_now = datetime.now()
    start_date = current_now.strftime("%Y-%m") + "-01"

    latest_gas = models.get_climate_data_by_date('gas_table', start_date=start_date)
    # Определение значения начала месяца
    if latest_gas: 
        if latest_gas[0]['start_of_month_gas_meter'] >= start_of_month_gas or latest_gas[-1]['start_of_month_gas_meter'] >= start_of_month_gas or latest_gas[0]['gas_meter'] <= start_of_month_gas:
            api_log.info(f"[БД] Значение счетчика газа {latest_gas[0]['start_of_month_gas_meter']} в gas_table не изменилось: {start_of_month_gas}")
            return False  
           
        for line_db in latest_gas:
            gas_out_db = {}
            gas_out_db = calc_gas_meter(line_db['gas_meter'], start_of_month_gas=start_of_month_gas, id_now=line_db["id"])
            gas_out_db['start_of_month_gas_meter'] = start_of_month_gas         
            models.update_data_db("gas_table", gas_out_db, line_db["id"])

        return True
    
    return False