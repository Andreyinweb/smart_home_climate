import sqlite3
import logging
from settings import config

work_log = logging.getLogger("climat_app.models")


def get_db_connection():
    """Создает подключение к базе данных SQLite с включенным автокоммитом."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def write_climate_data(name_table, data_sensors_all: dict) -> bool:
    """
    Записывает текущие показатели датчиков и расчетные данные в таблицу table_sensor_data.
    """
    names = list(data_sensors_all.keys())
    incoming_data = tuple(data_sensors_all.values())

    columns = ", ".join(names)
    placeholders = ", ".join(["?"] * len(names))

    query = f"INSERT INTO " + name_table + f" ({columns}) VALUES ({placeholders})"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, incoming_data)
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[БД] Ошибка записи в базу данных: {e}")
        return False

def get_latest_climate_data(name_table, limit: int = 1):
    """
    Возвращает последние записи из таблицы table_sensor_data.
    """
    query = f"""
    SELECT * FROM {name_table}
    ORDER BY ID DESC
    LIMIT {limit}
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        print(f"[БД] Ошибка чтения из базы данных: {e}")
        return []

def get_average_difference_temp() -> float:
    """
    Вычисляет среднее значение всех данных из столбца difference_temp.
    В случае ошибки или отсутствия данных возвращает 0.0.
    """
    query = "SELECT AVG(difference_temp) as avg_diff FROM table_sensor_data"
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            if row and row["avg_diff"] is not None:
                return round(row["avg_diff"], 2)
            return 0.0
    except sqlite3.Error as e:
        print(f"[БД] Ошибка при расчете среднего значения difference_temp: {e}")
        return 0.0