
# python3 run_program.py

import os
import sqlite3
from datetime import datetime

from run_data import PROJECT_DIR, DATA_DIR, DATA_FILE

database_file = DATA_DIR + "/" + DATA_FILE
bakcup_dir = PROJECT_DIR + "/backup/"

def check_or_create_database(db_file):
    # Проверяем существование файла
    if not os.path.exists(db_file):
        print(f"Файл базы данных '{db_file}' не найден. Создаем новый...")
        
        try:
            # Сначала проверяем доступность директории для записи
            dir_path = os.path.dirname(db_file) or '.'
            if not os.access(dir_path, os.W_OK):
                raise PermissionError(f"Нет прав на запись в директорию: {dir_path}")
            
            # Явно создаем пустой файл перед подключением
            open(db_file, 'a').close()
            print(f"Файл '{db_file}' успешно создан.")

        except Exception as e:
            print(f"Ошибка при создании базы данных: {type(e).__name__}: {e}")

    else:
        print(f"Файл базы данных '{db_file}' уже существует.")



def create_table(db_path, table_name, fields):
    """
    Создаёт таблицу в базе данных SQLite с автоматическим ID, именем таблицы и списком валют
    
    :param db_path: путь к файлу базы данных (например, 'cripto_data.sqlite3')
    :param table_name: имя создаваемой таблицы    
    :return: True при успешном создании, False при ошибке
    """
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем существование таблицы
        cursor.execute(f"""
        SELECT count(*) FROM sqlite_master 
        WHERE type='table' AND name='{table_name}'
        """)
        
        if cursor.fetchone()[0] > 0:
            print(f"Таблица '{table_name}' уже существует в базе данных.")
            return False
        
        # Создаём таблицу
        cursor.executescript(f"""
                        CREATE TABLE IF NOT EXISTS {table_name}
                        {fields}

        """)

        # Сохраняем изменения и закрываем соединение
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
    """
    Создает резервную копию файла с датой-временем в имени (без использования shutil)
    
    :param source_file: путь к исходному файлу
    :param backup_dir: директория для бэкапа
    :param max_backups: максимальное количество резервных копий
    :return: путь к созданной копии или None при ошибке
    """
    try:
        # Проверка исходного файла
        if not os.path.isfile(source_file):
            raise FileNotFoundError(f"Файл не найден: {source_file}")

        # Создаем директорию для бэкапа (если не существует)
        os.makedirs(backup_dir, exist_ok=True)

        # Получаем компоненты имени файла
        filename = os.path.basename(source_file)
        name, ext = os.path.splitext(filename)
        
        # Формируем новое имя с timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = os.path.join(backup_dir, backup_name)

        # Копируем файл (вариант через os)
        with open(source_file, 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())

        # Удаляем старые копии (если их больше max_backups)
        prefix = f"{name}_"
        backups = [f for f in os.listdir(backup_dir) 
                 if f.startswith(prefix) and f.endswith(ext)]
        
        if len(backups) > max_backups - 1:
            # Сортируем по имени (что соответствует времени из-за формата timestamp)
            backups.sort()
            # Удаляем самые старые (первые в списке)
            for old_backup in backups[:-max_backups]:
                os.remove(os.path.join(backup_dir, old_backup))
                print(f"Удалён старый бэкап: {old_backup}")

        print(f"Резервная копия создана: {backup_path}")
        return backup_path

    except Exception as e:
        print(f"Ошибка: {e}")
        return None

# Проверяем и создаем базу данных"
check_or_create_database(database_file)
exit(0)

# Создаём таблицу имён баз данных
fields_db = """ (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            name_table TEXT NOT NULL,
            mode TEXT NOT NULL,
            count INTEGER NOT NULL,
            currency_list TEXT NOT NULL
            
            
        )
        """
create_table(db_path=database_file, table_name="table_data_name", fields=fields_db)

# Создаём таблицу текущих настроек
fields_db = """ (
            table_now TEXT NOT NULL,
            mode TEXT NOT NULL,
            trading_allowed TEXT NOT NULL,
            count INTEGER NOT NULL,
            currency_list TEXT NOT NULL,
            start BOOLEAN DEFAULT FALSE,          
            work BOOLEAN DEFAULT FALSE,
            dict_speed TEXT,
            graph_dict TEXT);
            INSERT INTO now_table (table_now, trading_allowed, mode, currency_list, count, start, work)
            SELECT 'run', 'wait', 'run', 'run', -1, FALSE, FALSE
            WHERE NOT EXISTS (SELECT 1 FROM now_table);       
        """
create_table(db_path=database_file, table_name="now_table", fields=fields_db)

# Создаем резервную копию базы данных
create_backup(database_file, bakcup_dir)

