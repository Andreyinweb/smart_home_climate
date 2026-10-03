# app/core/db_start_config.py

import asyncio
from datetime import datetime, timedelta
import logging

from app.core.config import settings
import app.db.repository as db

work_log = logging.getLogger("climat_app.db_start_config")


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

    default_data = {
        "id": 1,
        "const_min": settings.target_temperature,
        "const_max": settings.target_temperature,
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
    default_data = {
        "id": 1,
        "temporarily_min": settings.target_temperature,
        "temporarily_max": settings.target_temperature,
        "temporarily_time": (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    success = await db.upsert_record(
        "programmer_temporarily", default_data, pk_col="id", log_to_api=log_to_api
    )
    if success:
        work_log.info("[DB Init] Первичное заполнение 'programmer_temporarily' успешно завершено.")
    else:
        work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_temporarily'.")


async def init_db_start_data() -> None:
    """Единая точка входа для инициализации стартовых данных во всех таблицах БД."""
    work_log.info("[DB Init] Запуск проверки и инициализации стартовых данных БД...")
    await init_settings_table()
    await init_programmer_const_table()
    await init_programmer_temporarily_table()
    work_log.info("[DB Init] Инициализация стартовых данных БД полностью завершена.")



# # app/core/db_start_config.py

# import asyncio
# from datetime import datetime
# import logging

# from app.core.config import settings
# import app.db.repository as db

# work_log = logging.getLogger("climat_app.db_start_config")


# async def init_settings_table(log_to_api: bool = False) -> None:
#     """
#     Проверяет наличие записи id=1 в settings_table.
#     Если запись отсутствует, выполняет первичное заполнение начальными значениями из конфигурации.
#     """
#     existing_settings = await db.get_record_by_id(
#         "settings_table", 1, pk_col="id", log_to_api=log_to_api
#     )

#     if existing_settings is not None:
#         work_log.info("[DB Init] Таблица 'settings_table' уже содержит системные настройки (id=1).")
#         return

#     work_log.info("[DB Init] Запись id=1 в 'settings_table' не найдена. Первичное заполнение из config.settings...")

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

#     success = await db.upsert_record(
#         "settings_table", default_data, pk_col="id", log_to_api=log_to_api
#     )
#     if success:
#         work_log.info("[DB Init] Первичное заполнение 'settings_table' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'settings_table'.")


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

#     default_data = {
#         "id": 1,
#         "const_min": settings.target_temperature,
#         "const_max": settings.target_temperature,
#         "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#     }

#     success = await db.upsert_record(
#         "programmer_const", default_data, pk_col="id", log_to_api=log_to_api
#     )
#     if success:
#         work_log.info("[DB Init] Первичное заполнение 'programmer_const' успешно завершено.")
#     else:
#         work_log.error("[DB Init] Ошибка при первичном заполнении 'programmer_const'.")


# async def init_db_start_data() -> None:
#     """Единая точка входа для инициализации стартовых данных во всех таблицах БД."""
#     work_log.info("[DB Init] Запуск проверки и инициализации стартовых данных БД...")
#     await init_settings_table()
#     await init_programmer_const_table()
#     work_log.info("[DB Init] Инициализация стартовых данных БД полностью завершена.")