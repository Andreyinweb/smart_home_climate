import sqlite3
import os
from datetime import datetime
from run.run_data import DATA_DIR, DATA_FILE

DB_PATH = os.path.join(DATA_DIR, DATA_FILE)

def get_db_connection():
    """Создает подключение к базе данных SQLite с включенным автокоммитом."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def write_climate_data(
    street_temp: float, street_humi: float, street_voltage: float,
    basement_temp: float, basement_humi: float, basement_voltage: float,
    floor_temp: float, floor_humi: float, floor_voltage: float,
    difference_temp: float, average_temp: float
) -> bool:
    """
    Записывает текущие показатели датчиков и расчетные данные в таблицу table_climate.
    """
    query = """
    INSERT INTO table_climate (
        Date,
        street_temp, street_humi, street_voltage,
        basement_temp, basement_humi, basement_voltage,
        floor_temp, floor_humi, floor_voltage,
        difference_temp, average_temp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (
                current_time,
                street_temp, street_humi, street_voltage,
                basement_temp, basement_humi, basement_voltage,
                floor_temp, floor_humi, floor_voltage,
                difference_temp, average_temp
            ))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[БД] Ошибка записи в базу данных: {e}")
        return False

def get_latest_climate_data(limit: int = 1):
    """
    Возвращает последние записи из таблицы table_climate.
    """
    query = f"""
    SELECT * FROM table_climate
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