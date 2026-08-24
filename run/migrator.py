# python3.12 run/migrator.py
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Set

import run_program


def get_db_connection(path_db: str | Path) -> sqlite3.Connection:
    """Создает и возвращает подключение к базе данных SQLite."""
    conn = sqlite3.connect(path_db)
    conn.row_factory = sqlite3.Row
    return conn


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    """Возвращает список имен всех столбцов указанной таблицы."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        return [row[1] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"[Ошибка] Не удалось получить структуру таблицы {table_name}: {e}")
        return []


def get_existing_dates(conn: sqlite3.Connection, table_name: str, date_col: str = "timestamp") -> Set[Any]:
    """Извлекает все существующие значения даты/времени из целевой таблицы для O(1) проверки дубликатов."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {date_col} FROM {table_name} WHERE {date_col} IS NOT NULL")
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.Error as e:
        print(f"[Ошибка] Не удалось получить существующие даты из {table_name}: {e}")
        return set()


def get_timestamp_to_id_map(conn: sqlite3.Connection) -> Dict[str, int]:
    """Строит словарь соответствий timestamp -> id на основе главной таблицы table_sensor_data."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, id FROM table_sensor_data WHERE timestamp IS NOT NULL")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except sqlite3.Error as e:
        print(f"[Ошибка] Не удалось построить карту timestamp -> id: {e}")
        return {}


def migrate_primary_table(
    target_conn: sqlite3.Connection,
    backup_files: List[Path],
    table_name: str = "table_sensor_data",
) -> None:
    """Мигрирует основную таблицу сенсоров (table_sensor_data) из бэкапов.

    Генерирует уникальные автоинкрементные ID в целевой БД.
    """
    print(f"\n--- [Главная таблица] Миграция: {table_name} ---")
    target_columns = get_table_columns(target_conn, table_name)
    if not target_columns:
        print(f"[Пропуск] Таблица {table_name} отсутствует в целевой БД.")
        return

    date_col = "timestamp"
    if date_col not in target_columns:
        print(f"[Предупреждение] Колонка '{date_col}' не найдена в {table_name}.")
        return

    existing_dates = get_existing_dates(target_conn, table_name, date_col)
    print(f"[Инфо] Существующих записей в основной БД: {len(existing_dates)}")

    total_inserted = 0
    total_skipped = 0

    for backup_path in backup_files:
        try:
            with get_db_connection(backup_path) as backup_conn:
                backup_columns = get_table_columns(backup_conn, table_name)
                if not backup_columns or date_col not in backup_columns:
                    continue

                # Исключаем 'id', чтобы целевая БД автоматически генерировала первичный ключ
                common_columns = [
                    col for col in target_columns
                    if col in backup_columns and col.lower() != "id"
                ]
                cols_str = ", ".join(common_columns)
                placeholders = ", ".join(["?"] * len(common_columns))

                query = f"SELECT {cols_str} FROM {table_name} WHERE {date_col} IS NOT NULL ORDER BY {date_col} ASC"
                cursor = backup_conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

                rows_to_insert = []
                for row in rows:
                    row_dict = dict(row)
                    row_date = row_dict[date_col]

                    if row_date in existing_dates:
                        total_skipped += 1
                    else:
                        rows_to_insert.append(tuple(row_dict[col] for col in common_columns))
                        existing_dates.add(row_date)

                if rows_to_insert:
                    insert_query = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
                    target_conn.executemany(insert_query, rows_to_insert)
                    target_conn.commit()
                    inserted_count = len(rows_to_insert)
                    total_inserted += inserted_count
                    print(f"  [+] {backup_path.name}: добавлено {inserted_count} новых записей.")

        except sqlite3.Error as e:
            print(f"  [Ошибка] Чтение/запись файла {backup_path.name}: {e}")

    print(f"[Итог для {table_name}] Добавлено: {total_inserted}, Пропущено дубликатов: {total_skipped}")


def migrate_dependent_table(
    target_conn: sqlite3.Connection,
    backup_files: List[Path],
    table_name: str,
    ts_to_id: Dict[str, int],
) -> None:
    """Мигрирует вторичные таблицы (gas_table, weather_site_table и т.д.),

    связывая 'id' с соответствующим ID из table_sensor_data по значению timestamp.
    """
    print(f"\n--- [Зависимая таблица] Миграция: {table_name} ---")
    target_columns = get_table_columns(target_conn, table_name)
    if not target_columns:
        print(f"[Пропуск] Таблица {table_name} отсутствует в целевой БД.")
        return

    date_col = "timestamp"
    if date_col not in target_columns:
        print(f"[Пропуск] Колонка '{date_col}' отсутствует в {table_name}.")
        return

    existing_dates = get_existing_dates(target_conn, table_name, date_col)
    print(f"[Инфо] Существующих записей в {table_name}: {len(existing_dates)}")

    has_id_col = "id" in target_columns
    total_inserted = 0
    total_skipped = 0

    for backup_path in backup_files:
        try:
            with get_db_connection(backup_path) as backup_conn:
                backup_columns = get_table_columns(backup_conn, table_name)
                if not backup_columns or date_col not in backup_columns:
                    continue

                # Выбираем общие колонки без 'id'
                common_non_id = [
                    col for col in target_columns
                    if col in backup_columns and col.lower() != "id"
                ]
                if not common_non_id:
                    continue

                insert_columns = ["id"] + common_non_id if has_id_col else common_non_id
                select_cols_str = ", ".join(common_non_id)
                insert_cols_str = ", ".join(insert_columns)
                placeholders = ", ".join(["?"] * len(insert_columns))

                query = f"SELECT {select_cols_str} FROM {table_name} WHERE {date_col} IS NOT NULL ORDER BY {date_col} ASC"
                cursor = backup_conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()

                rows_to_insert = []
                for row in rows:
                    row_dict = dict(row)
                    row_date = row_dict[date_col]

                    if row_date in existing_dates:
                        total_skipped += 1
                    else:
                        if has_id_col:
                            row_id = ts_to_id.get(row_date)
                            row_tuple = (row_id,) + tuple(row_dict[col] for col in common_non_id)
                        else:
                            row_tuple = tuple(row_dict[col] for col in common_non_id)

                        rows_to_insert.append(row_tuple)
                        existing_dates.add(row_date)

                if rows_to_insert:
                    insert_query = f"INSERT INTO {table_name} ({insert_cols_str}) VALUES ({placeholders})"
                    target_conn.executemany(insert_query, rows_to_insert)
                    target_conn.commit()
                    inserted_count = len(rows_to_insert)
                    total_inserted += inserted_count
                    print(f"  [+] {backup_path.name}: добавлено {inserted_count} новых записей.")

        except sqlite3.Error as e:
            print(f"  [Ошибка] Чтение/запись файла {backup_path.name}: {e}")

    print(f"[Итог для {table_name}] Добавлено: {total_inserted}, Пропущено дубликатов: {total_skipped}")


def main() -> None:
    print("=" * 80)
    print(" ЗАПУСК ПРОЦЕССА МИГРАЦИИ И ОБЪЕДИНЕНИЯ ДАННЫХ")
    print("=" * 80)

    backup_dir = Path(run_program.backup_dir)
    target_db_path = run_program.database_file

    if not backup_dir.exists():
        print(f"[Ошибка] Директория с резервными копиями не найдена: {backup_dir}")
        return

    # Получаем файлы бэкапов в хронологическом порядке
    backup_files = sorted(
        [
            f for f in backup_dir.iterdir()
            if f.is_file() and f.suffix in (".sqlite3", ".db")
        ]
    )

    if not backup_files:
        print("[Инфо] В директории резервных копий нет файлов для миграции.")
        return

    print(f"[Инфо] Найдено файлов резервных копий: {len(backup_files)}")

    try:
        with get_db_connection(target_db_path) as target_conn:
            cursor = target_conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            target_tables = [row[0] for row in cursor.fetchall()]

            # Таблицы, исключаемые из миграции зависимых данных
            exclude_tables = {
                "table_sensor_data",
                "settings_table",
                "sqlite_sequence",
                "api_table",
                "ventilation_table",
                "heating_table",
                "hourly_coefficients_table",
            }
            now_db_tables = [t for t in target_tables if t not in exclude_tables]
            print(f"[Инфо] Таблицы для миграции ({len(now_db_tables)}): {now_db_tables}")

            # 1. Сначала мигрируем главную таблицу датчиков (table_sensor_data)
            migrate_primary_table(target_conn, backup_files, "table_sensor_data")

            # 2. Формируем единую карту timestamp -> id для подстановки во все зависимые таблицы
            ts_to_id = get_timestamp_to_id_map(target_conn)
            print(f"[Инфо] Кэш timestamp -> ID сформирован ({len(ts_to_id)} записей в карте).")

            # 3. Мигрируем остальные таблицы
            for table_name in now_db_tables:
                migrate_dependent_table(target_conn, backup_files, table_name, ts_to_id)

    except sqlite3.Error as e:
        print(f"[Критическая ошибка] Ошибка подключения к основной базе данных: {e}")

    print("\n" + "=" * 80)
    print(" МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
    print("=" * 80)


if __name__ == "__main__":
    main()