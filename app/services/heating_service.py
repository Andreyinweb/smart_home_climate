# app/services/heating_service.py

import logging
from typing import Any, Dict, Optional

from app.db.repository import BaseRepository
from app.services.relay_service import RelayController

logger = logging.getLogger("climat_app.heating_service")


async def determine_target_temperature(
    basement_temp: Optional[float],
    target_temp: Optional[float],
    max_temp: Optional[float],
) -> float:
    """
    Определяет целевую температуру догрева котла:
    - Если текущая температура подвала ниже целевой, догреваем до target_temperature.
    - В противном случае (если выше или равна), догреваем до maximum_temperature.
    """
    if basement_temp is None:
        return target_temp if target_temp is not None else 0.0

    t_target = target_temp if target_temp is not None else 0.0
    t_max = max_temp if max_temp is not None else 0.0

    if basement_temp < t_target:
        return t_target
    return t_max


async def process_manual_heating_start(
    repo: BaseRepository,
    relay: RelayController,
) -> bool:
    """
    Обрабатывает ручной запуск отопления:
    1. Проверяет текущую запись в heating_table.
    2. Если отопление еще не включено, определяет целевую температуру на момент включения
       согласно условию (сравнение basement_temp с target_temperature).
    3. Записывает запись о старте в heating_table 
    4. Осуществляет физическое включение реле котла.
    """
    latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    if latest_heat and latest_heat.get("status_heating"):
        logger.info("Отопление уже запущено, повторный запуск пропущен.")
        return False

    latest_sensor = await repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    if not latest_sensor:
        logger.warning("Отсутствуют данные с датчиков в table_sensor_data. Запуск отопления отменен.")
        return False

    sys_settings = await repo.get_or_create_settings(log_to_api=False)

    basement_temp = latest_sensor.get("basement_temp")
    target_temp = getattr(sys_settings, "target_temperature", None)
    max_temp = getattr(sys_settings, "maximum_temperature", None)

    target_heat_temp = await determine_target_temperature(basement_temp, target_temp, max_temp)

    logger.info(
        f"[Отопление] Старт: basement_temp={basement_temp}, target_temperature={target_temp}, "
        f"maximum_temperature={max_temp} -> Установлена целевая температура нагрева: {target_heat_temp}°C"
    )

    data_to_write: Dict[str, Any] = {
        "id": latest_sensor["id"],
        "timestamp": latest_sensor["timestamp"],
        "status_heating": True,
        "stop_heat_plus": 0,
        "automation_start": False,
    }



    try:
        if await relay.turn_on():
            if await relay.get_state():
                await repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
                logger.info(f"Успешная запись старта отопления в heating_table: sensor_id={latest_sensor['id']}")
    except Exception as e:
        logger.error(f"Сбой при физическом включении реле котла: {e}")

    return True


async def check_and_stop_heating(
    repo: BaseRepository,
    relay: RelayController,
    current_sensor_record: Dict[str, Any],
) -> bool:
    """
    Проверяет в основном цикле условия остановки отопления:
    Если отопление включено, сверяет текущую температуру подвала с целевым лимитом.
    При достижении или превышении целевой температуры выключает котел и фиксирует остановку в БД.
    """
    latest_heat = await repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
    if not latest_heat or not latest_heat.get("status_heating"):
        return False

    heat_start_id = latest_heat.get("id")
    sensor_before = await repo.get_record_by_id("table_sensor_data", heat_start_id, log_to_api=False)
    if not sensor_before:
        return False

    sys_settings = await repo.get_or_create_settings(log_to_api=False)
    target_temp = getattr(sys_settings, "target_temperature", None)
    max_temp = getattr(sys_settings, "maximum_temperature", None)

    start_basement_temp = sensor_before.get("basement_temp")
    target_heat_limit = await determine_target_temperature(start_basement_temp, target_temp, max_temp)

    current_basement_temp = current_sensor_record.get("basement_temp")
    if current_basement_temp is None:
        return False

    if current_basement_temp >= target_heat_limit:
        current_id = current_sensor_record.get("id")
        stop_heat_plus = current_id - heat_start_id

        if stop_heat_plus == 0:
            if await relay.turn_off():
                if not await relay.get_state():
                    await repo.delete_record_by_id("heating_table", heat_start_id, pk_col="id", log_to_api=False)
                    logger.info(f"Отопление завершено (stop_heat_plus=0, id={heat_start_id}), запись удалена.")
        else:
            data_to_write: Dict[str, Any] = {
                "id": heat_start_id,
                "timestamp": latest_heat["timestamp"],
                "status_heating": False,
                "stop_heat_plus": stop_heat_plus,
                "automation_stop": True
            }
            if await relay.turn_off():
                if not await relay.get_state():
                    await repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
                    logger.info(
                        f"[Отопление] Достигнута целевая температура ({current_basement_temp}°C >= {target_heat_limit}°C). "
                        f"Отопление остановлено. start_id={heat_start_id}, stop_id={current_id}, diff={stop_heat_plus}"
                    )


        return True

    return False

