import os
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения из файла .env
load_dotenv()

PROJECT_DIR: str = Path.cwd()
DATA_DIR: str = str(os.environ.get("DB_DIR", PROJECT_DIR))
DATA_FILE: str = str(os.environ.get("DB_NAME", "climate_data.sqlite3"))
backup_dir: str = str(os.environ.get("BACKUP", f"{PROJECT_DIR}/backup"))
database_file = DATA_DIR + "/" + DATA_FILE

def check_or_create_database(db_file):
    if not os.path.exists(db_file):
        print(f"Файл базы данных '{db_file}' не найден. Создаем новый...")
        try:
            dir_path = os.path.dirname(db_file) or '.'
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            if dir_path and not os.access(dir_path, os.W_OK):
                raise PermissionError(f"Нет прав на запись в директорию: {dir_path}")
            open(db_file, 'a').close()
            print(f"Файл '{db_file}' успешно создан.")
        except Exception as e:
            print(f"Ошибка при создании базы данных: {type(e).__name__}: {e}")
    else:
        print(f"Файл базы данных '{db_file}' уже существует.")

def create_table(db_path, table_name, fields):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"""
        SELECT count(*) FROM sqlite_master 
        WHERE type='table' AND name='{table_name}'
        """)
        
        if cursor.fetchone()[0] > 0:
            print(f"Таблица '{table_name}' уже существует в базе данных.")
            conn.close()
            return False
        
        cursor.executescript(f"""
            CREATE TABLE IF NOT EXISTS {table_name}
            {fields}
        """)

        conn.commit()
        conn.close()
        print(f"Таблица '{table_name}' успешно создана.")
        return True
    except sqlite3.Error as e:
        print(f"Ошибка при создании таблицы: {e}")
        return False
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")
        return False

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

        print(f"Резервная копия создана: {backup_path}")
        return backup_path

    except Exception as e:
        print(f"Ошибка: {e}")
        return None

check_or_create_database(database_file)

# Создаём таблицу settings_table
fields_db = """ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    mode TEXT, 
    interval_seconds INTEGER, 
    max_retries INTEGER, 
    website_return_time INTEGER, 
    t_floor_mac_diff REAL, 
    absolute_humidity_tolerance REAL,
    minimum_humidity  REAL,
    target_rh REAL,
    dangerous_humidity REAL,
    price_gas REAL   
    )
    """
create_table(db_path=database_file, table_name='settings_table', fields=fields_db)


# Создаём таблицу table_sensor_data
fields_db = """ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    street_temp REAL,
    basement_temp REAL,
    floor_temp REAL,
    difference_temp REAL,
    average_temp REAL,
    street_humi REAL,
    basement_humi REAL,
    floor_humi REAL,
    street_voltage REAL,
    basement_voltage REAL,
    floor_voltage REAL,
    sensor_or_calc_street BOOLEAN,
    sensor_or_calc_basement BOOLEAN,
    sensor_or_calc_floor BOOLEAN
)
"""
create_table(db_path=database_file, table_name='table_sensor_data', fields=fields_db)


# Создаём таблицу gas_table
fields_db = """ (
    id INTEGER ,
    timestamp TEXT NOT NULL,
    gas_meter REAL,
    start_of_month_gas_meter REAL,
    gas_difference REAL,
    average_street_temp REAL,
    average_basement_temp REAL,
    delta_T REAL,
    coefficient_gas REAL,
    gas_per_hour REAL,
    gas_per_month REAL,
    hot_water_per_month REAL,
    hot_water_per_hour REAL,
    price_gas REAL,
    cost_of_gas REAL,
    gas_forecast REAL,
    projected_price REAL
)
"""
create_table(db_path=database_file, table_name='gas_table', fields=fields_db)



# Создаём таблицу api_table
fields_db = """ (
    id INTEGER ,
    timestamp TEXT,    
    a_floor_humi REAL,
    dp_floor REAL,
    a_street_humi REAL,
    dp_street REAL,
    a_basement_humi REAL,
    dp_basement REAL,
    humidity_difference REAL,
    vent_status BOOLEAN,
    vent_time_val INTEGER,
    sim_a_basement_humi REAL,
    sim_basement_humi REAL,
    sim_floor_humi REAL,
    heating_delta REAL,
    heat_status BOOLEAN,
    floor_temp_heated REAL,
    basement_temp_heated REAL,
    basement_humi_heated REAL,
    a_basement_humi_heated REAL,
    floor_humi_heated REAL,
    a_floor_humi_heated REAL
    )
    """
create_table(db_path=database_file, table_name='api_table', fields=fields_db)

# Создаём таблицу ventilation_table
fields_db = """ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    status_ventilation BOOLEAN,
    ventilation_start INTEGER,
    stop_ventilation INTEGER   
    )
    """
create_table(db_path=database_file, table_name='ventilation_table', fields=fields_db)

# Создаём таблицу heating_table
fields_db = """ (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    status_heating BOOLEAN,
    heating_start INTEGER,
    stop_heating INTEGER   
    )
    """
create_table(db_path=database_file, table_name='heating_table', fields=fields_db)

# Таблица сырых данных с сайта (weather_site_table)
fields_db = """ (
    id INTEGER ,
    timestamp TEXT NOT NULL,
    site_temp REAL NOT NULL,
    site_humi REAL NOT NULL,
    site_ah REAL NOT NULL
)
"""
create_table(db_path=database_file, table_name='weather_site_table', fields=fields_db)

# Таблица часовых калибровочных коэффициентов (hourly_coefficients_table)
fields_db = """ (
    hour INTEGER PRIMARY KEY,
    delta_temp REAL DEFAULT 0.0,
    delta_ah REAL DEFAULT 0.0,
    samples_count INTEGER DEFAULT 0,
    updated_at TEXT
)
"""
if create_table(db_path=database_file, table_name='hourly_coefficients_table', fields=fields_db):
    try:
        conn = sqlite3.connect(database_file)
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for h in range(24):
            cursor.execute(
                "INSERT OR IGNORE INTO hourly_coefficients_table (hour, delta_temp, delta_ah, samples_count, updated_at) VALUES (?, 0.0, 0.0, 0, ?)",
                (h, now_str)
            )
        conn.commit()
        conn.close()
        print("Инициализирована таблица 'hourly_coefficients_table' 24 часовыми записями.")
    except Exception as e:
        print(f"Ошибка заполнения hourly_coefficients_table: {e}")
        
