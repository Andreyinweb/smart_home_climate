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

def write_climate_data(name_table: str, data_all: dict, row_id: int = None) -> bool:
    """
    Записывает текущие показатели в таблицу. 
    Если передан row_id, перезаписывает (или создает) строку с этим ID.
    """
    names = list(data_all.keys())
    incoming_data = list(data_all.values())

    if row_id is not None:
        names.append('id')
        incoming_data.append(row_id)
        
        columns = ", ".join(names)
        placeholders = ", ".join(["?"] * len(names))
        query = f"INSERT OR REPLACE INTO {name_table} ({columns}) VALUES ({placeholders})"
    else:
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

def update_data_db(name_table: str, data_all: dict, row_id: int) -> bool:
    """Обновляет указанные колонки в существующей строке по row_id."""
    if not data_all or row_id is None:
        work_log.error("[БД] Ошибка: не переданы данные для обновления или row_id")
        return False

    set_clause = ", ".join([f"{col} = ?" for col in data_all.keys()])
    values = list(data_all.values())
    values.append(row_id)

    query = f"UPDATE {name_table} SET {set_clause} WHERE id = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(values))
            conn.commit()

            if cursor.rowcount == 0:
                work_log.warning(f"[БД] Запись с id={row_id} в таблице {name_table} не найдена")
                return False

            work_log.info(f"[БД] Запись id={row_id} в {name_table} успешно обновлена")
        return True
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка обновления базы данных: {e}")
        print(f"[БД] Ошибка обновления базы данных: {e}")
        return False

def get_latest_climate_data(name_table: str, start_id: int = None, stop_id: int = None) -> list:
    """Возвращает записи из таблицы по условиям start_id и/или stop_id."""
    query = f"SELECT * FROM {name_table}"
    params = []

    if start_id is None and stop_id is None:
        query += " ORDER BY ID DESC LIMIT 1"
    elif start_id is not None and stop_id is not None:
        if start_id == stop_id:
            query += " WHERE ID = ?"
            params.append(start_id)
        else:
            query += " WHERE ID >= ? AND ID <= ? ORDER BY ID ASC"
            params.extend([start_id, stop_id])
    elif start_id is not None:
        query += " WHERE ID >= ? ORDER BY ID ASC"
        params.append(start_id)
    else:
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
    """Вычисляет среднее значение всех данных из столбца difference_temp."""
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

def get_hourly_coefficient(hour: int) -> dict:
    """Возвращает калибровочные коэффициенты для указанного часа."""
    query = "SELECT delta_temp, delta_ah FROM hourly_coefficients_table WHERE hour = ?"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (hour,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {'delta_temp': 0.0, 'delta_ah': 0.0}
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка чтения коэффициентов для часа {hour}: {e}")
        return {'delta_temp': 0.0, 'delta_ah': 0.0}

def update_hourly_coefficient(hour: int, delta_temp: float, delta_ah: float, samples_count: int) -> bool:
    """Обновляет коэффициенты в hourly_coefficients_table для конкретного часа."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    query = """
        UPDATE hourly_coefficients_table
        SET delta_temp = ?, delta_ah = ?, samples_count = ?, updated_at = ?
        WHERE hour = ?
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (round(delta_temp, 3), round(delta_ah, 4), samples_count, now_str, hour))
            conn.commit()
            return True
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка обновления коэффициента часа {hour}: {e}")
        return False

def get_calibration_data(max_time_diff_seconds: int = 600) -> list:
    """
    Выбирает совпадающие по времени записи из table_sensor_data и weather_site_table
    для выполнения калибровки уличных коэффициентов.
    """
    query = """
    SELECT 
        CAST(strftime('%H', s.timestamp) AS INTEGER) AS hour_val,
        s.street_temp,
        s.street_humi,
        w.site_temp,
        w.site_ah
    FROM table_sensor_data s
    JOIN weather_site_table w 
      ON ABS(strftime('%s', s.timestamp) - strftime('%s', w.timestamp)) <= ?
    WHERE s.sensor_or_calc_street = 1
      AND s.street_temp IS NOT NULL 
      AND s.street_humi IS NOT NULL;
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (max_time_diff_seconds,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка запроса данных для калибровки: {e}")
        return []

work_log.info("-" * 60)
work_log.info(f"Программа запущена. MODE = {config.MODE}.")
settings_out_db = {}

latest_settings = get_latest_climate_data('settings_table')
if not latest_settings:
    settings_out_db['mode'] = config.MODE
    settings_out_db['interval_seconds'] = config.INTERVAL_SECONDS
    settings_out_db['max_retries'] = config.MAX_RETRIES
    settings_out_db['website_return_time'] = config.WEBSITE_RETURN_TIME
    settings_out_db['absolute_humidity_tolerance'] = config.ABSOLUTE_HUMIDITY_TOLERANCE
    settings_out_db['minimum_humidity'] = config.MINIMUM_HUMIDITY
    settings_out_db['target_rh'] = config.TARGET_RH
    settings_out_db['dangerous_humidity'] = config.DANGEROUS_HUMIDITY
    settings_out_db['price_gas'] = config.PRICE_GAS
    settings_out_db['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
else:
    settings_out_db = latest_settings[0]

latest_records = get_latest_climate_data('table_sensor_data')
if latest_records:
    in_db_sensor_data = latest_records[0]
    if in_db_sensor_data.get('average_temp'):
        settings_out_db['t_floor_mac_diff'] = in_db_sensor_data['average_temp']
        settings_out_db['timestamp'] = in_db_sensor_data['timestamp']
        config.T_FLOOR_MAC_DIFF = in_db_sensor_data['average_temp']
    else:
        settings_out_db['t_floor_mac_diff'] = config.T_FLOOR_MAC_DIFF
else:
    settings_out_db['t_floor_mac_diff'] = config.T_FLOOR_MAC_DIFF

write_climate_data('settings_table', settings_out_db, row_id=1)