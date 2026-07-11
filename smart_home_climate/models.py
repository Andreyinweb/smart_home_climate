import sqlite3
import os
from run.run_data import DATA_DIR, DATA_FILE

DB_PATH = os.path.join(DATA_DIR, DATA_FILE)

def get_db_connection():
    """Создает подключение к базе данных SQLite с включенным автокоммитом."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def write_climate_data(data_sensors_all: dict) -> bool:
    """
    Записывает текущие показатели датчиков и расчетные данные в таблицу table_climate.
    """
    query = "INSERT INTO table_climate ("
    name_list = list(data_sensors_all.keys())
    incoming_data = []
    count_values = 0
    for name in name_list:
        if type(data_sensors_all[name]) is dict:
            climate_variables = list(data_sensors_all[name].keys())
            for variable in climate_variables:
                query += f" {name}_{variable},"
                count_values += 1
                incoming_data.append(data_sensors_all[name][variable])
        else:
            query += f" {name},"
            count_values += 1
            incoming_data.append(data_sensors_all[name])
    query = query[:-1] + ") VALUES (" + "?, " * count_values
    query = query[:-2]  + ")"
    incoming_data = tuple(incoming_data)
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, incoming_data)
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

def get_average_difference_temp() -> float:
    """
    Вычисляет среднее значение всех данных из столбца difference_temp.
    В случае ошибки или отсутствия данных возвращает 0.0.
    """
    query = "SELECT AVG(difference_temp) as avg_diff FROM table_climate"
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