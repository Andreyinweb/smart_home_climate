# python3.12 run/migrator.py

import sqlite3
import run_program
from pathlib import Path
from typing import List, Set, Optional, Dict, Any

def get_db_connection(path_db: str | Path) -> sqlite3.Connection:
    """
    Создает и возвращает подключение к базе данных SQLite.
    
    :param path_db: Путь к файлу базы данных SQLite.
    :return: Объект подключения sqlite3.Connection с row_factory = sqlite3.Row.
    """
    conn = sqlite3.connect(path_db)
    conn.row_factory = sqlite3.Row
    return conn


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    """
    Возвращает список имен всех столбцов указанной таблицы.
    
    :param conn: Подключение к БД.
    :param table_name: Имя таблицы.
    :return: Список строк с названиями столбцов.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        return [row[1] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"[Ошибка] Не удалось получить структуру таблицы {table_name}: {e}")
        return []


def find_date_column(columns: List[str]) -> Optional[str]:
    """
    Определяет название колонки, содержащей дату или временную метку.
    
    :param columns: Список названий столбцов таблицы.
    :return: Имя колонки даты или None, если не найдена.
    """
    # Список наиболее частых названий столбцов с датой/временем
    priority_candidates = ['date', 'timestamp', 'datetime', 'time', 'created_at', 'dt']
    col_map = {c.lower(): c for c in columns}
    
    # 1. Точное совпадение по приоритету
    for candidate in priority_candidates:
        if candidate in col_map:
            return col_map[candidate]
            
    # 2. Неполное совпадение (если подстрока 'date' или 'time' есть в названии)
    for c in columns:
        if 'date' in c.lower() or 'time' in c.lower():
            return c
            
    return None


def get_existing_dates(conn: sqlite3.Connection, table_name: str, date_col: str) -> Set[Any]:
    """
    Извлекает все существующие значения даты из целевой таблицы для быстрой проверки дубликатов.
    
    :param conn: Подключение к целевой БД.
    :param table_name: Название таблицы.
    :param date_col: Название столбца даты.
    :return: Множество (set) со всеми существующими датами.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {date_col} FROM {table_name} WHERE {date_col} IS NOT NULL")
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.Error as e:
        print(f"[Ошибка] Не удалось получить существующие даты из {table_name}: {e}")
        return set()


def migrate_table_data(target_conn: sqlite3.Connection, backup_files: List[Path], table_name: str):
    """
    Мигрирует данные одной таблицы из всех бэкап-файлов в основную базу данных.
    
    - Исключает дубликаты по полю даты.
    - Сортирует записи хронологически (от старых к новым).
    - Переносит только общие столбцы.
    
    :param target_conn: Соединение с целевой (основной) БД.
    :param backup_files: Список путей к бэкап-файлам SQLite (отсортированный по хронологии).
    :param table_name: Имя переносимой таблицы.
    """
    print(f"\n--- Обработка таблицы: {table_name} ---")
    
    # 1. Получаем список колонок в целевой таблице
    target_columns = get_table_columns(target_conn, table_name)
    if not target_columns:
        print(f"[Пропуск] Таблица {table_name} отсутствует или пуста в целевой БД.")
        return

    # Определяем ключевое поле даты
    date_col = find_date_column(target_columns)
    if not date_col:
        print(f"[Предупреждение] В целевой таблице {table_name} не найдена колонка с датой! Миграция пропущена.")
        return

    print(f"[Инфо] Колонка сравнения по дате: '{date_col}'")

    # 2. Собираем уже существующие даты из основной БД
    existing_dates = get_existing_dates(target_conn, table_name, date_col)
    print(f"[Инфо] Существующих записей в основной БД: {len(existing_dates)}")

    total_inserted = 0
    total_skipped = 0

    # 3. Проходим по бэкапам по хронологии
    for backup_path in backup_files:
        try:
            with get_db_connection(backup_path) as backup_conn:
                backup_columns = get_table_columns(backup_conn, table_name)
                
                # Проверяем наличие таблицы в бэкапе
                if not backup_columns:
                    continue

                # Находим общие столбцы (исключаем 'id', чтобы SQLite автоинкрементировал первичный ключ)
                common_columns = [col for col in target_columns if col in backup_columns and col.lower() != 'id']
                
                if date_col not in common_columns:
                    print(f"  [Пропуск] Файл {backup_path.name}: отсутствует колонка даты '{date_col}' в бэкапе.")
                    continue

                cols_str = ", ".join(common_columns)
                placeholders = ", ".join(["?"] * len(common_columns))
                
                # Выбираем данные из бэкапа, отсортированные от старых к новым
                query = f"SELECT {cols_str} FROM {table_name} WHERE {date_col} IS NOT NULL ORDER BY {date_col} ASC"
                cursor = backup_conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

                rows_to_insert = []
                for row in rows:
                    row_dict = dict(row)
                    row_date = row_dict[date_col]
                    
                    # Проверка на дубликаты
                    if row_date in existing_dates:
                        total_skipped += 1
                    else:
                        rows_to_insert.append(tuple(row_dict[col] for col in common_columns))
                        existing_dates.add(row_date)  # Добавляем в кэш, чтобы избежать дубликатов внутри самих бэкапов

                # Массовая вставка новых данных
                if rows_to_insert:
                    insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
                    target_conn.executemany(insert_query, rows_to_insert)
                    target_conn.commit()
                    inserted_count = len(rows_to_insert)
                    total_inserted += inserted_count
                    print(f"  [+] Файл {backup_path.name}: добавлено {inserted_count} новых записей.")

        except sqlite3.Error as e:
            print(f"  [Ошибка] Ошибка чтения/записи файла {backup_path.name}: {e}")

    print(f"[Итог для {table_name}] Успешно добавлено: {total_inserted}, Пропущено дубликатов: {total_skipped}")


def main():
    print("=" * 80)
    print(" ЗАПУСК ПРОЦЕССА МИГРАЦИИ И ОБЪЕДИНЕНИЯ ДАННЫХ")
    print("=" * 80)

    backup_dir = Path(run_program.backup_dir)
    target_db_path = run_program.database_file

    if not backup_dir.exists():
        print(f"[Ошибка] Директория с резервными копиями не найдена: {backup_dir}")
        return

    # 1. Получаем список файлов бэкапов (сортируем по имени для соблюдения хронологии YYYYMMDD_HHMMSS)
    backup_files = sorted([f for f in backup_dir.iterdir() if f.is_file()])

    if not backup_files:
        print("[Инфо] В директории резервных копий нет файлов для миграции.")
        return

    print(f"[Инфо] Найдено файлов резервных копий: {len(backup_files)}")

    # 2. Получаем список актуальных таблиц из целевой базы данных
    try:
        with get_db_connection(target_db_path) as target_conn:
            cursor = target_conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            target_tables = [row[0] for row in cursor.fetchall()]

            # Список исключаемых системных и служебных таблиц
            exclude_tables = {
                'settings_table', 
                'sqlite_sequence', 
                'api_table', 
                'ventilation_table', 
                'heating_table', 
                'hourly_coefficients_table'
            }
            now_db_tables = [t for t in target_tables if t not in exclude_tables]
            print(f"[Инфо] Таблицы для миграции ({len(now_db_tables)}): {now_db_tables}")

            # 3. Выполняем миграцию по каждой таблице
            for table_name in now_db_tables:
                migrate_table_data(target_conn, backup_files, table_name)

    except sqlite3.Error as e:
        print(f"[Критическая ошибка] Ошибка подключения к основной базе данных: {e}")

    print("\n" + "=" * 80)
    print(" МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
    print("=" * 80)
    run_program.create_backup(target_db_path, backup_dir)

if __name__ == "__main__":
    main()