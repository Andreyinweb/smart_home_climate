 # app/services/heating_service.py

import logging
from typing import Any, Dict, Optional

from app.db.repository import BaseRepository
from app.services.relay_service import RelayController

logger = logging.getLogger("climat_app.heating_controller")

class HeatingController:
    """
    Контроллер управления логикой отопления и физическим состоянием USB-реле котла.
    """

    def __init__(self, repo: BaseRepository, relay: RelayController) -> None:
        self.repo = repo
        self.relay = relay

    async def start(self, is_automation: bool = False) -> bool:
        """
        Запуск отопления (ручной или автоматический по порогу).
        """
        latest_heat = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        if latest_heat and latest_heat.get("status_heating") is True:
            logger.info("[start] Отопление уже запущено. Запуск пропущен.")
            return False

        latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
        if not latest_sensor or "id" not in latest_sensor or "timestamp" not in latest_sensor:
            logger.warning("[start] Отсутствуют корректные данные в table_sensor_data. Запуск отопления отменен.")
            return False

        turn_on_success = await self.relay.turn_on()
        relay_state = await self.relay.get_state()

        if not turn_on_success or not relay_state:
            logger.error(
                "[start] Сбой или блокировка включения реле: turn_on=%s, get_state=%s. Запись в БД отменена.",
                turn_on_success,
                relay_state,
            )
            return False

        data_to_write: Dict[str, Any] = {
            "id": latest_sensor["id"],
            "timestamp": latest_sensor["timestamp"],
            "status_heating": True,
            "stop_heat_plus": 0,
            "automation_start": is_automation,
        }

        await self.repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
        logger.info(f"[start] Успешный запуск отопления зафиксирован в БД: sensor_id={latest_sensor['id']}")
        return True

    async def stop(self, is_automation: bool = False) -> bool:
        """
        Остановка отопления (ручная или автоматическая по порогу).
        """
        latest_heat = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        if not latest_heat or not latest_heat.get("status_heating"):
            logger.info("[stop] Отопление выключено. Остановка пропущена.")
            return False

        latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
        current_sensor_id = latest_sensor["id"] if (latest_sensor and "id" in latest_sensor) else latest_heat["id"]
        heat_start_id = latest_heat["id"]
        stop_heat_plus = max(0, current_sensor_id - heat_start_id)

        turn_off_success = await self.relay.turn_off()
        relay_state = await self.relay.get_state()

        if not turn_off_success or relay_state:
            logger.error(
                "[stop] Сбой или блокировка выключения реле: turn_off=%s, get_state=%s. Запись в БД отменена.",
                turn_off_success,
                relay_state,
            )
            return False

        if stop_heat_plus == 0:
            await self.repo.delete_record_by_id("heating_table", heat_start_id, pk_col="id", log_to_api=False)
            logger.info(f"[stop] Запись отопления удалена (stop_heat_plus=0): id={heat_start_id}")
        else:
            data_to_write: Dict[str, Any] = {
                "id": heat_start_id,
                "timestamp": latest_heat["timestamp"],
                "status_heating": False,
                "stop_heat_plus": stop_heat_plus,
                "automation_stop": is_automation,
            }
            await self.repo.upsert_record("heating_table", data_to_write, pk_col="id", log_to_api=False)
            logger.info(
                f"[stop] Зафиксирована остановка отопления: start_id={heat_start_id}, "
                f"current_id={current_sensor_id}, diff={stop_heat_plus}"
            )

        return True

    async def check_temperature(self, sensor_record: Dict[str, Any]) -> None:
        """
        Проверка температурных порогов в фоновом цикле.
        """
        if not sensor_record:
            return

        basement_temp = sensor_record.get("basement_temp")
        if basement_temp is None:
            return

        sys_settings = await self.repo.get_or_create_settings(log_to_api=False)
        minimum_temperature = getattr(sys_settings, "minimum_temperature", None)
        target_temperature = getattr(sys_settings, "target_temperature", None)
        maximum_temperature = getattr(sys_settings, "maximum_temperature", None)

        latest_heat = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        is_heating_active = bool(latest_heat and latest_heat.get("status_heating"))

        if not is_heating_active:
            if minimum_temperature is not None and basement_temp <= minimum_temperature:
                logger.warning(
                    f"[check_temperature] Критическое снижение температуры подвала: {basement_temp}°C <= {minimum_temperature}°C. Автозапуск."
                )
                await self.start(is_automation=True)
        else:
            heat_start_id = latest_heat.get("id")
            sensor_before = (
                await self.repo.get_record_by_id("table_sensor_data", heat_start_id, log_to_api=False)
                if heat_start_id
                else None
            )
            start_basement_temp = sensor_before.get("basement_temp") if sensor_before else basement_temp

            target_limit = maximum_temperature

            if target_limit is not None and basement_temp >= target_limit:
                logger.warning(
                    f"[check_temperature] Достигнут температурный предел ({basement_temp}°C >= {target_limit}°C). Автоостановка."
                )
                await self.stop(is_automation=True)
