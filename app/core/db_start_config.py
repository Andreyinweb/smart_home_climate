# app/core/db_start_config.py

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Set

from app.core.config import settings
import app.db.repository as db
from app.services.programmer_service import Programmer

work_log = logging.getLogger("climat_app.db_start_config")

DAY_ABBR = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY_INDEX = {name: idx for idx, name in enumerate(DAY_ABBR)}


async def init_settings_table(log_to_api: bool = False) -> None:
    """
    Проверяет наличие записи id=1 в settings_table.
    Если запись отсутствует, заполняет её из конфигурации.
    Если запись уже существует, проверяет все поля и дозаполняет значение из конфига, если поле None.
    """
    existing_settings = await db.get_record_by_id(
        "settings_table", 1, pk_col="id", log_to_api=log_to_api
    )

    programmer_mode_val = (
        settings.programmer_mode.value
        if hasattr(settings.programmer_mode, "value")
        else settings.programmer_mode
    )

    default_data = {
        "id": 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": settings.sensor_mode.value,
        "interval_seconds": settings.interval_seconds,
        "previous_interval_in_seconds": settings.previous_interval_in_seconds,
        "max_retries": settings.max_retries,
        "website_return_time": settings.website_return_time,
        "t_floor_mac_diff": settings.t_floor_mac_diff,
        "absolute_humidity_tolerance": settings.absolute_humidity_tolerance,
        "minimum_humidity": settings.minimum_humidity,
        "target_rh": settings.target_rh,
        "dangerous_humidity": settings.dangerous_humidity,
        "price_gas": settings.price_gas,
        "hot_water_per_hour": settings.hot_water_per_hour,
        "minimum_temperature": settings.minimum_temperature,
        "target_temperature": settings.target_temperature,
        "maximum_temperature": settings.maximum_temperature,
        "hysteresis_temperature": settings.hysteresis_temperature,
        "programmer_mode": programmer_mode_val,
    }

    if existing_settings is None:
        work_log.info("[DB Init] Запись id=1 в 'settings_table' не найдена. Первичное заполнение из config.settings...")
        success = await db.upsert_record(
            "settings_table", default_data, pk_col="id", log_to_api=log_to_api
        )
        if success:
            work_log.info("[DB Init] Первичное заполнение 'settings_table' успешно завершено.")
        else:
            work_log.error("[DB Init] Ошибка при первичном заполнении 'settings_table'.")
    else:
        updated_data = dict(existing_settings)
        has_updates = False

        for key, default_val in default_data.items():
            if key not in updated_data or updated_data[key] is None:
                updated_data[key] = default_val
                has_updates = True

        if has_updates:
            work_log.info("[DB Init] В 'settings_table' найдены незаполненные поля (None). Дозаполнение из конфигурации...")
            updated_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            success = await db.upsert_record(
                "settings_table", updated_data, pk_col="id", log_to_api=log_to_api
            )
            if success:
                work_log.info("[DB Init] Дозаполнение 'settings_table' успешно завершено.")
            else:
                work_log.error("[DB Init] Ошибка при дозаполнении 'settings_table'.")
        else:
            work_log.info("[DB Init] Таблица 'settings_table' уже содержит все заполненные настройки (id=1).")


async def init_programmer_const_table(log_to_api: bool = False) -> None:
    """
    Проверяет наличие записи id=1 в programmer_const.
    Если запись отсутствует, выполняет первичное заполнение начальными значениями из конфигурации.
    """
    existing_record = await db.get_record_by_id(
        "programmer_const", 1, pk_col="id", log_to_api=log_to_api
    )

    if existing_record is not None:
        work_log.info("[DB Init] Таблица 'programmer_const' уже содержит записи (id=1).")
        return

    work_log.info("[DB Init] Запись id=1 в 'programmer_const' не найдена. Первичное заполнение из config.settings...")

    temp_min = round(settings.target_temperature - settings.hysteresis_temperature / 2, 1)
    temp_max = round(settings.target_temperature + settings.hysteresis_temperature / 2, 1)

    default_data = {
        "id": 1,
        "const_min": temp_min,
        "const_max": temp_max,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    success = await db.upsert_record(
        "programmer_const", default_data, pk_col="id", log_to_api=log_to_api
    )
    if success:
        work_log.info("[DB Init] Первичное заполнение 'programmer_const' успешно завершено.")
    else:
        work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_const'.")


async def init_programmer_temporarily_table(log_to_api: bool = False) -> None:
    """
    Проверяет наличие записи id=1 в programmer_temporarily.
    Если запись отсутствует, выполняет первичное заполнение начальными значениями.
    """
    existing_record = await db.get_record_by_id(
        "programmer_temporarily", 1, pk_col="id", log_to_api=log_to_api
    )

    if existing_record is not None:
        work_log.info("[DB Init] Таблица 'programmer_temporarily' уже содержит записи (id=1).")
        return

    work_log.info("[DB Init] Запись id=1 в 'programmer_temporarily' не найдена. Первичное заполнение...")

    now = datetime.now()
    temporarily = settings.target_temperature

    default_data = {
        "id": 1,
        "temporarily": temporarily,
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    success = await db.upsert_record(
        "programmer_temporarily", default_data, pk_col="id", log_to_api=log_to_api
    )
    if success:
        work_log.info("[DB Init] Первичное заполнение 'programmer_temporarily' успешно завершено.")
    else:
        work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_temporarily'.")


async def init_heating_table(log_to_api: bool = False) -> None:
    """
    Проверяет наличие записи id=1 в heating_table.
    Если запись отсутствует, выполняет первичное заполнение начальными значениями.
    """
    existing_record = await db.get_record_by_id(
        "heating_table", 1, pk_col="id", log_to_api=log_to_api
    )

    if existing_record is not None:
        work_log.info("[DB Init] Таблица 'heating_table' уже содержит записи (id=1).")
        return

    work_log.info("[DB Init] Запись id=1 в 'heating_table' не найдена. Первичное заполнение...")

    temp_min = round(settings.target_temperature - settings.hysteresis_temperature / 2, 1)
    temp_max = round(settings.target_temperature + settings.hysteresis_temperature / 2, 1)

    default_data = {
        "id": 1,
        "temperature_start": temp_min,
        "temperature_stop": temp_max,
        "status_heating": False,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    success = await db.upsert_record(
        "heating_table", default_data, pk_col="id", log_to_api=log_to_api
    )
    if success:
        work_log.info("[DB Init] Первичное заполнение 'heating_table' успешно завершено.")
    else:
        work_log.error("[DB Init] Ошибка при первичном заполнении 'heating_table'.")


def _parse_week_day(week_day: str) -> Set[int]:
    """
    Преобразует значение week_day в множество номеров дней недели (Mo=0 ... Su=6).
    Поддерживает одиночный день ("Mo") и диапазон ("Mo_Fr", "Sa_Su", "Mo_Su").
    При неизвестном значении возвращает пустое множество.
    """
    try:
        if "_" in week_day:
            start, end = week_day.split("_", 1)
            return set(range(DAY_INDEX[start], DAY_INDEX[end] + 1))
        return {DAY_INDEX[week_day]}
    except KeyError:
        return set()


def _calc_system_row(
    rows: List[Dict[str, Any]],
    week_mode: str,
    now: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Вычисляет системную строку programmer_week (id=1) на момент now.

    Логика:
    - Берутся строки расписания (id > 1) с week_mode == week_mode.
    - Строятся все наступления этих интервалов в окне [now - 7 дней; now + 7 дней].
    - now_id — последний интервал, который уже начался (<= now);
      next_id — первый интервал, который начнётся позже now.
    - week_time системной строки — дата и время начала next_id (конец текущего цикла).
    - week_temperature — температура интервала now_id.
    Возвращает словарь для upsert или None, если расписания для режима нет.
    """
    cycle_points = []

    for row in rows:
        if row.get("week_mode") != week_mode:
            continue

        try:
            row_time = datetime.strptime(row["week_time"], "%H:%M").time()
        except (KeyError, TypeError, ValueError):
            work_log.warning(f"[DB Init] Некорректное week_time в строке id={row.get('id')}: {row.get('week_time')}")
            continue

        days = _parse_week_day(row.get("week_day", ""))
        if not days:
            work_log.warning(f"[DB Init] Некорректный week_day в строке id={row.get('id')}: {row.get('week_day')}")
            continue

        for offset in range(-7, 8):
            day = now.date() + timedelta(days=offset)
            if day.weekday() in days:
                cycle_points.append((datetime.combine(day, row_time), row))

    if not cycle_points:
        return None

    cycle_points.sort(key=lambda point: point[0])
    past = [point for point in cycle_points if point[0] <= now]
    future = [point for point in cycle_points if point[0] > now]

    if not past or not future:
        return None

    active_start, active_row = past[-1]
    next_start, next_row = future[0]

    return {
        "id": 1,
        "now_id": active_row["id"],
        "next_id": next_row["id"],
        "week_mode": week_mode,
        "week_day": active_row["week_day"],
        "week_time": next_start.strftime("%Y-%m-%d %H:%M:%S"),
        "week_temperature": float(active_row["week_temperature"]),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_default_week_schedule(now_datetime_str: str) -> List[Dict[str, Any]]:
    """
    Формирует начальные строки расписания programmer_week (id > 1).
    При первичном заполнении возможны дубли строк (например, для режима week).
    Программа удаляет их в процессе работы.
    """
    target = settings.target_temperature

    base_schedule = [
        {"id": 2, "week_time": "06:00", "week_temperature": float(target)},
        {"id": 3, "week_time": "10:00", "week_temperature": float(target - 2)},
        {"id": 4, "week_time": "14:00", "week_temperature": float(target)},
        {"id": 5, "week_time": "16:00", "week_temperature": float(target - 2)},
        {"id": 6, "week_time": "18:00", "week_temperature": float(target)},
        {"id": 7, "week_time": "22:00", "week_temperature": 19.0},
    ]

    # Сортируем расписание по времени хронологически
    sorted_schedule = sorted(base_schedule, key=lambda x: x["week_time"])

    records: List[Dict[str, Any]] = [
        {
            "id": item["id"],
            "week_mode": "week",
            "week_day": "Mo_Su",
            "week_time": item["week_time"],
            "week_temperature": item["week_temperature"],
            "updated_at": now_datetime_str,
        }
        for item in sorted_schedule
    ]

    # Для всех режимов дней недели берутся первый и последний интервал суток
    two_elements = [sorted_schedule[0], sorted_schedule[-1]]
    next_id = sorted_schedule[-1]["id"]

    for week_mode_item, day_list in settings.days_week_mode.items():
        for day_item in day_list:
            for item in two_elements:
                next_id += 1
                records.append({
                    "id": next_id,
                    "week_mode": week_mode_item,
                    "week_day": day_item,
                    "week_time": item["week_time"],
                    "week_temperature": item["week_temperature"],
                    "updated_at": now_datetime_str,
                })

    return records


async def init_programmer_week_table(log_to_api: bool = False) -> None:
    """
    Инициализирует таблицу programmer_week.

    - Если записи нет (первый запуск), заполняет расписание по умолчанию.
    - В любом случае пересчитывает системную строку id=1 под текущую дату и время:
      now_id, next_id, week_time (конец текущего цикла), week_temperature, updated_at.
      Это исправляет строку id=1, оставшуюся после миграции из старой БД.
    """
    existing_record = await db.get_record_by_id(
        "programmer_week", 1, pk_col="id", log_to_api=log_to_api
    )

    now = datetime.now()
    now_datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    all_success = True

    if existing_record is None:
        work_log.info("[DB Init] Запись id=1 в 'programmer_week' не найдена. Первичное заполнение расписания...")
        for record in _build_default_week_schedule(now_datetime_str):
            success = await db.upsert_record(
                "programmer_week", record, pk_col="id", log_to_api=log_to_api
            )
            if not success:
                all_success = False
    else:
        work_log.info("[DB Init] Таблица 'programmer_week' уже содержит записи (id=1). Пересчёт системной строки...")

    # Режим берём из текущей системной строки, если он допустим, иначе 'week'
    current_mode = existing_record.get("week_mode") if existing_record else None
    if current_mode not in settings.days_week_mode:
        current_mode = "week"

    schedule_rows = await db.fetch_range(
        "programmer_week",
        filter_col="id",
        start_val=2,
        order_asc=True,
        log_to_api=log_to_api,
    )

    system_record = _calc_system_row(schedule_rows, current_mode, now)
    if system_record is None:
        work_log.error(f"[DB Init] Не удалось вычислить системную строку 'programmer_week' для режима '{current_mode}'.")
        return

    success = await db.upsert_record(
        "programmer_week", system_record, pk_col="id", log_to_api=log_to_api
    )
    if not success:
        all_success = False

    if all_success:
        work_log.info("[DB Init] Инициализация 'programmer_week' успешно завершена.")
    else:
        work_log.error("[DB Init] Ошибка при инициализации 'programmer_week'.")


async def init_db_start_data() -> None:
    """Единая точка входа для инициализации стартовых данных во всех таблицах БД."""
    work_log.info("[DB Init] Запуск проверки и инициализации стартовых данных БД...")
    await init_settings_table()
    await init_programmer_const_table()
    await init_programmer_temporarily_table()
    await init_heating_table()
    await init_programmer_week_table()
    work_log.info("[DB Init] Инициализация стартовых данных БД полностью завершена.")

# # app/core/db_start_config.py

# import asyncio
# from datetime import datetime, timedelta
# import logging

# from app.core.config import settings
# import app.db.repository as db
# from app.services.programmer_service import Programmer

# work_log = logging.getLogger("climat_app.db_start_config")


# async def init_settings_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в settings_table.
#     Если запись отсутствует, заполняет её из конфигурации.
#     Если запись уже существует, проверяет все поля и дозаполняет значение из конфига, если поле None.
#     """
#     existing_settings = await db.get_record_by_id(
#         "settings_table", 1, pk_col="id", log_to_api=log_to_api
#     )

#     programmer_mode_val = (
#         settings.programmer_mode.value
#         if hasattr(settings.programmer_mode, "value")
#         else settings.programmer_mode
#     )

#     default_data = {
#         "id": 1,
#         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#         "mode": settings.sensor_mode.value,
#         "interval_seconds": settings.interval_seconds,
#         "previous_interval_in_seconds": settings.previous_interval_in_seconds,
#         "max_retries": settings.max_retries,
#         "website_return_time": settings.website_return_time,
#         "t_floor_mac_diff": settings.t_floor_mac_diff,
#         "absolute_humidity_tolerance": settings.absolute_humidity_tolerance,
#         "minimum_humidity": settings.minimum_humidity,
#         "target_rh": settings.target_rh,
#         "dangerous_humidity": settings.dangerous_humidity,
#         "price_gas": settings.price_gas,
#         "hot_water_per_hour": settings.hot_water_per_hour,
#         "minimum_temperature": settings.minimum_temperature,
#         "target_temperature": settings.target_temperature,
#         "maximum_temperature": settings.maximum_temperature,
#         "hysteresis_temperature": settings.hysteresis_temperature,
#         "programmer_mode": programmer_mode_val,
#     }

#     if existing_settings is None:
#         work_log.info("[DB Init] Запись id=1 в 'settings_table' не найдена. Первичное заполнение из config.settings...")
#         success = await db.upsert_record(
#             "settings_table", default_data, pk_col="id", log_to_api=log_to_api
#         )
#         if success:
#             work_log.info("[DB Init] Первичное заполнение 'settings_table' успешно завершено.")
#         else:
#             work_log.error("[DB Init] Ошибка при первичном заполнении 'settings_table'.")
#     else:
#         updated_data = dict(existing_settings)
#         has_updates = False

#         for key, default_val in default_data.items():
#             if key not in updated_data or updated_data[key] is None:
#                 updated_data[key] = default_val
#                 has_updates = True

#         if has_updates:
#             work_log.info("[DB Init] В 'settings_table' найдены незаполненные поля (None). Дозаполнение из конфигурации...")
#             updated_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#             success = await db.upsert_record(
#                 "settings_table", updated_data, pk_col="id", log_to_api=log_to_api
#             )
#             if success:
#                 work_log.info("[DB Init] Дозаполнение 'settings_table' успешно завершено.")
#             else:
#                 work_log.error("[DB Init] Ошибка при дозаполнении 'settings_table'.")
#         else:
#             work_log.info("[DB Init] Таблица 'settings_table' уже содержит все заполненные настройки (id=1).")


# async def init_programmer_const_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в programmer_const.
#     Если запись отсутствует, выполняет первичное заполнение начальными значениями из конфигурации.
#     """
#     existing_record = await db.get_record_by_id(
#         "programmer_const", 1, pk_col="id", log_to_api=log_to_api
#     )

#     if existing_record is not None:
#         work_log.info("[DB Init] Таблица 'programmer_const' уже содержит записи (id=1).")
#         return

#     work_log.info("[DB Init] Запись id=1 в 'programmer_const' не найдена. Первичное заполнение из config.settings...")

#     temp_min = round(settings.target_temperature - settings.hysteresis_temperature / 2, 1)
#     temp_max = round(settings.target_temperature + settings.hysteresis_temperature / 2, 1)

#     default_data = {
#         "id": 1,
#         "const_min": temp_min,
#         "const_max": temp_max,
#         "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#     }

#     success = await db.upsert_record(
#         "programmer_const", default_data, pk_col="id", log_to_api=log_to_api
#     )
#     if success:
#         work_log.info("[DB Init] Первичное заполнение 'programmer_const' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_const'.")


# async def init_programmer_temporarily_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в programmer_temporarily.
#     Если запись отсутствует, выполняет первичное заполнение начальными значениями.
#     """
#     existing_record = await db.get_record_by_id(
#         "programmer_temporarily", 1, pk_col="id", log_to_api=log_to_api
#     )

#     if existing_record is not None:
#         work_log.info("[DB Init] Таблица 'programmer_temporarily' уже содержит записи (id=1).")
#         return

#     work_log.info("[DB Init] Запись id=1 в 'programmer_temporarily' не найдена. Первичное заполнение...")

#     now = datetime.now()
#     temporarily = settings.target_temperature

#     default_data = {
#         "id": 1,
#         "temporarily": temporarily,
#         "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
#     }

#     success = await db.upsert_record(
#         "programmer_temporarily", default_data, pk_col="id", log_to_api=log_to_api
#     )
#     if success:
#         work_log.info("[DB Init] Первичное заполнение 'programmer_temporarily' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_temporarily'.")


# async def init_heating_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в heating_table.
#     Если запись отсутствует, выполняет первичное заполнение начальными значениями.
#     """
#     existing_record = await db.get_record_by_id(
#         "heating_table", 1, pk_col="id", log_to_api=log_to_api
#     )

#     if existing_record is not None:
#         work_log.info("[DB Init] Таблица 'heating_table' уже содержит записи (id=1).")
#         return

#     work_log.info("[DB Init] Запись id=1 в 'heating_table' не найдена. Первичное заполнение...")

#     temp_min = round(settings.target_temperature - settings.hysteresis_temperature / 2, 1)
#     temp_max = round(settings.target_temperature + settings.hysteresis_temperature / 2, 1)

#     default_data = {
#         "id": 1,
#         "temperature_start": temp_min,
#         "temperature_stop": temp_max,
#         "status_heating": False,
#         "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#     }

#     success = await db.upsert_record(
#         "heating_table", default_data, pk_col="id", log_to_api=log_to_api
#     )
#     if success:
#         work_log.info("[DB Init] Первичное заполнение 'heating_table' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'heating_table'.")

# async def init_programmer_week_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в programmer_week.
#     Если запись отсутствует, выполняет первичное заполнение таблицы
#     на основе начального списка интервалов и текущего времени.
#     """
#     existing_record = await db.get_record_by_id(
#         "programmer_week", 1, pk_col="id", log_to_api=log_to_api
#     )

#     now = datetime.now()
#     now_time_str = now.strftime("%H:%M")
#     now_datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")

#     if existing_record is not None:
#         work_log.info("[DB Init] Таблица 'programmer_week' уже содержит записи (id=1).")
#         # TODO Переписать первую строку по актуальной дате, аналог далее в программе.
#         return
    

#     work_log.info("[DB Init] Запись id=1 в 'programmer_week' не найдена. Первичное заполнение...")

#     default_schedule = [
#         {
#             "id": 2,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "06:00",
#             "week_temperature": float(settings.target_temperature),
#         },
#         {
#             "id": 3,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "10:00",
#             "week_temperature": float(settings.target_temperature - 2),
#         },
#         {
#             "id": 4,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "14:00",
#             "week_temperature": float(settings.target_temperature),
#         },
#         {
#             "id": 5,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "16:00",
#             "week_temperature": float(settings.target_temperature - 2),
#         },
#         {
#             "id": 6,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "18:00",
#             "week_temperature": float(settings.target_temperature),
#         },
#         {
#             "id": 7,
#             "week_mode": "week",
#             "week_day": "Mo_Su",
#             "week_time": "22:00",
#             "week_temperature": 19.0,
#         },
#     ]


#     # Сортируем расписание по времени хронологически
#     sorted_schedule = sorted(default_schedule, key=lambda x: x["week_time"])
#     n = len(sorted_schedule)

#     # Определяем активный интервал по умолчанию (последний интервал суток)
#     active_idx = n - 1

#     # Ищем актуальный интервал для текущего времени
#     for idx, item in enumerate(sorted_schedule):
#         if now_time_str >= item["week_time"]:
#             active_idx = idx
#         else:
#             break

#     next_idx = (active_idx + 1) % n

#     active_item = sorted_schedule[active_idx]
#     next_item = sorted_schedule[next_idx]

#     # Вычисляем дату и время следующего перехода
#     if next_item["week_time"] > now_time_str:
#         target_date = now.date()
#     else:
#         target_date = now.date() + timedelta(days=1)

#     next_datetime_str = f"{target_date.strftime('%Y-%m-%d')} {next_item['week_time']}:00"

#     # Формируем системную строку (id=1), содержащую ссылки now_id и next_id
#     system_record = {
#         "id": 1,
#         "now_id": active_item["id"],
#         "next_id": next_item["id"],
#         "week_mode": active_item["week_mode"],
#         "week_day": active_item["week_day"],
#         "week_time": next_datetime_str,
#         "week_temperature": active_item["week_temperature"],
#         "updated_at": now_datetime_str,
#     }

#     all_success = await db.upsert_record(
#         "programmer_week", system_record, pk_col="id", log_to_api=log_to_api
#     )

#     # Сохраняем элементы расписания (id > 1) week_mode: week
#     for item in sorted_schedule:
#         record = {
#             "id": item["id"],
#             "week_mode": item["week_mode"],
#             "week_day": item["week_day"],
#             "week_time": item["week_time"],
#             "week_temperature": item["week_temperature"],
#             "updated_at": now_datetime_str,
#         }
#         success = await db.upsert_record(
#             "programmer_week", record, pk_col="id", log_to_api=log_to_api
#         )
#         if not success:
#             all_success = False
# ########################################################################################################################
#     # Выберает два элемента
#     now_id = item["id"]
#     two_elements = [sorted_schedule[0], sorted_schedule[-1]]
#     days_week_mode = settings.days_week_mode
#     week_mode_list = list(days_week_mode.keys())
#     # Сохраняем элементы расписания (id > 1) week_mode
#     for week_mode_item in week_mode_list:
#         for day_item in days_week_mode[week_mode_item]:
#             for item in two_elements:            
#                 now_id += 1
#                 record = {
#                     "id": now_id,
#                     "week_mode": week_mode_item,
#                     "week_day": day_item,
#                     "week_time": item["week_time"],
#                     "week_temperature": item["week_temperature"],
#                     "updated_at": now_datetime_str,
#                 }
#                 success = await db.upsert_record(
#                     "programmer_week", record, pk_col="id", log_to_api=log_to_api
#                 )
#                 if not success:
#                     all_success = False
  
        
               
#     if all_success:
#         work_log.info("[DB Init] Первичное заполнение 'programmer_week' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_week'.")


# async def init_db_start_data() -> None:
#     """Единая точка входа для инициализации стартовых данных во всех таблицах БД."""
#     work_log.info("[DB Init] Запуск проверки и инициализации стартовых данных БД...")
#     await init_settings_table()
#     await init_programmer_const_table()
#     await init_programmer_temporarily_table()
#     await init_heating_table()
#     await init_programmer_week_table()
#     work_log.info("[DB Init] Инициализация стартовых данных БД полностью завершена.")