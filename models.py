import sqlite3
import logging
from settings import config

work_log = logging.getLogger("climat_app.models")


def get_db_connection():
    """Создает подключение к базе данных SQLite с включенным автокоммитом."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def write_climate_data(name_table, data_sensors_all: dict, row_id: int = None) -> bool:
    """
    Записывает текущие показатели в таблицу. 
    Если передан row_id, перезаписывает (или создает) строку с этим ID.
    """
    names = list(data_sensors_all.keys())
    incoming_data = list(data_sensors_all.values())

    if row_id is not None:
        # Добавляем id в список полей и значений для INSERT OR REPLACE
        names.append("id")
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
        print(f"[БД] Ошибка при расчете среднего значения difference_temp: {e}")
        return config.T_FLOOR_MAC_DIFF