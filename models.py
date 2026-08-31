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


def get_climate_data_by_date(name_table: str, start_date=None, stop_date=None) -> list:
    """Возвращает записи из таблицы по условиям start_date и/или stop_date по столбцу timestamp."""
    query = f"SELECT * FROM {name_table}"
    params = []

    if start_date is None and stop_date is None:
        query += " ORDER BY timestamp DESC LIMIT 1"
    elif start_date is not None and stop_date is not None:
        if start_date == stop_date:
            query += " WHERE timestamp = ?"
            params.append(start_date)
        else:
            query += " WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC"
            params.extend([start_date, stop_date])
    elif start_date is not None:
        query += " WHERE timestamp >= ? ORDER BY timestamp ASC"
        params.append(start_date)
    else:
        query += " WHERE timestamp <= ? ORDER BY timestamp ASC"
        params.append(stop_date)

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

def get_interval_average(
    name_table: str,
    column_name: str,
    interval_type: str = 'hour',
    target_time: str = None
) -> float:
    """
    Вычисляет среднее значение столбца за указанный интервал времени.

    :param name_table: Имя таблицы в БД.
    :param column_name: Имя столбца для вычисления среднего значения.
    :param interval_type: Тип интервала ('hour'/'час', 'day'/'день', 'month'/'месяц').
    :param target_time: Конкретная дата/время в формате строки (например, '2026-08-23 14:00', '2026-08-23', '2026-08').
                        Если не передано, вычисляет за относительный интервал от текущего времени.
    :return: Среднее значение (float), округленное до 2 знаков, или None.
    """
    normalized_interval = str(interval_type).strip().lower()
    params = []

    if target_time:
        clean_time = str(target_time).strip()
        if normalized_interval in ('hour', 'час'):
            query = f"""
                SELECT AVG({column_name}) AS avg_val
                FROM {name_table}
                WHERE strftime('%Y-%m-%d %H', timestamp) = ?
            """
            params.append(clean_time[:13])
        elif normalized_interval in ('day', 'день'):
            query = f"""
                SELECT AVG({column_name}) AS avg_val
                FROM {name_table}
                WHERE strftime('%Y-%m-%d', timestamp) = ?
            """
            params.append(clean_time[:10])
        elif normalized_interval in ('month', 'месяц'):
            query = f"""
                SELECT AVG({column_name}) AS avg_val
                FROM {name_table}
                WHERE strftime('%Y-%m', timestamp) = ?
            """
            params.append(clean_time[:7])
        else:
            work_log.error(f"[БД] Передан неподдерживаемый интервал времени: '{interval_type}'")
            return None
    else:
        interval_map = {
            'hour': '-1 hour', 'час': '-1 hour',
            'day': '-1 day', 'день': '-1 day',
            'month': '-1 month', 'месяц': '-1 month'
        }
        modifier = interval_map.get(normalized_interval, '-1 hour')
        query = f"""
            SELECT AVG({column_name}) AS avg_val
            FROM {name_table}
            WHERE timestamp >= datetime('now', '{modifier}')
        """

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            if row and row["avg_val"] is not None:
                return round(float(row["avg_val"]), 2)
            return None
    except sqlite3.Error as e:
        work_log.error(f"[БД] Ошибка вычисления среднего значения {column_name} в {name_table}: {e}")
        print(f"[БД] Ошибка вычисления среднего значения {column_name} в {name_table}: {e}")
        return None
    
######################################

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
    settings_out_db['hot_water_per_hour'] = config.HOT_WATER_PER_HOUR
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