import sqlite3
import logging
from datetime import datetime
from settings import config

work_log = logging.getLogger("climat_app.models")


def get_db_connection():
    """Создает подключение к базе данных SQLite с включенным автокоммитом."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def write_climate_data(name_table, data_all: dict, row_id: int = None) -> bool:
    """
    Записывает текущие показатели в таблицу. 
    Если передан row_id, перезаписывает (или создает) строку с этим ID.
    """
    names = list(data_all.keys())
    incoming_data = list(data_all.values())

    if row_id is not None:
        # Добавляем id в список полей и значений для INSERT OR REPLACE
        names.append('id')
        incoming_data.append(row_id)
        
        columns = ", ".join(names)
        placeholders = ", ".join(["?"] * len(names))
        query = f"INSERT OR REPLACE INTO {name_table} ({columns}) VALUES ({placeholders})"
    else:
        # Стандартный INSERT для добавления новой строки с автоинкрементом
        columns = ", ".join(names)
        placeholders = ", ".join(["?"] * len(names))
        query = f"INSERT INTO {name_table} ({columns}) VALUES ({placeholders})"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(incoming_data))
            conn.commit()
            work_log.info(f"[БД] Данные успешно записаны в таблицу {name_table}")
        return True
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка записи в базу данных: {e}")
        print(f"[БД] Ошибка записи в базу данных: {e}")
        return False

def get_latest_climate_data(name_table: str, start_id: int = None, stop_id: int = None):
    """
    Возвращает записи из таблицы по условиям start_id и/или stop_id.
    
    - Если оба ID не указаны, возвращается последняя строка по ID.
    - Если указан только start_id, возвращаются строки от start_id до конца.
    - Если указан только stop_id, возвращаются строки от начала до stop_id.
    - Если указаны оба ID и они равны, возвращается конкретная строка.
    - Если указаны оба ID и они разные, возвращается выборка в этом диапазоне.
    """
    query = f"SELECT * FROM {name_table}"
    params = []

    # Реализация логики условий в зависимости от переданных аргументов
    if start_id is None and stop_id is None:
        # Возвращаем последнюю строку
        query += " ORDER BY ID DESC LIMIT 1"
    elif start_id is not None and stop_id is not None:
        if start_id == stop_id:
            # Конкретная строка
            query += " WHERE ID = ?"
            params.append(start_id)
        else:
            # Выборка по диапазону ID
            query += " WHERE ID >= ? AND ID <= ? ORDER BY ID ASC"
            params.extend([start_id, stop_id])
    elif start_id is not None:
        # От start_id до конца таблицы
        query += " WHERE ID >= ? ORDER BY ID ASC"
        params.append(start_id)
    else:  # stop_id is not None
        # От начала таблицы до stop_id
        query += " WHERE ID <= ? ORDER BY ID ASC"
        params.append(stop_id)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        work_log.info(f"[БД] Ошибка чтения из базы данных: {e}")
        print(f"[БД] Ошибка чтения из базы данных: {e}")
        return []


def get_average_difference_temp() -> float:
    """
    Вычисляет среднее значение всех данных из столбца difference_temp.
    В случае ошибки или отсутствия данных возвращает config.T_FLOOR_MAC_DIFF
    """
    query = "SELECT AVG(difference_temp) as avg_diff FROM table_sensor_data"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            if row and row["avg_diff"] is not None:
                return round(row["avg_diff"], 2)
            return config.T_FLOOR_MAC_DIFF
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка при расчете среднего значения difference_temp: {e}")
        print(f"[БД] Ошибка при расчете среднего значения difference_temp: {e}")
        return config.T_FLOOR_MAC_DIFF
    
# Запись настроек в базу данных
work_log.info("-"*50)
settings_in_db = {}

latest_settings = get_latest_climate_data('settings_table')
if not latest_settings:
    settings_in_db['mode'] = config.MODE
    settings_in_db['interval_seconds'] = config.INTERVAL_SECONDS
    settings_in_db['max_retries'] = config.MAX_RETRIES
    settings_in_db['website_return_time'] = config.WEBSITE_RETURN_TIME
    settings_in_db['absolute_humidity_tolerance'] = config.ABSOLUTE_HUMIDITY_TOLERANCE
    settings_in_db['minimum_humidity'] = config.MINIMUM_HUMIDITY
    settings_in_db['target_rh'] = config.TARGET_RH
    settings_in_db['dangerous_humidity'] = config.DANGEROUS_HUMIDITY
    settings_in_db['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
else:
    settings_in_db = latest_settings[0]

latest_records = get_latest_climate_data('table_sensor_data')
if latest_records:
   in_db_sensor_data = latest_records[0]
   if in_db_sensor_data['average_temp']:
      settings_in_db['t_floor_mac_diff'] = in_db_sensor_data['average_temp']
      config.T_FLOOR_MAC_DIFF = in_db_sensor_data['average_temp']
   else:
      settings_in_db['t_floor_mac_diff'] = config.T_FLOOR_MAC_DIFF
else:
   settings_in_db['t_floor_mac_diff'] = config.T_FLOOR_MAC_DIFF

write_climate_data('settings_table', settings_in_db, row_id=1)