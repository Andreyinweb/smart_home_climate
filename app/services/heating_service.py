# app/services/heating_service.py

import asyncio
import logging
from typing import Any, Dict, Optional

from app.db.repository import BaseRepository
from app.services.relay_service import RelayController

logger = logging.getLogger("climat_app.heating_controller")


class HeatingController:
    """
    Контроллер управления логикой отопления и физическим состоянием USB-реле котла.
    Защищен от одновременного выполнения операций управления через асинхронную блокировку.
    """

    def __init__(self, repo: BaseRepository, relay: RelayController) -> None:
        self.repo = repo
        self.relay = relay
        self._lock = asyncio.Lock()

    async def start(self, is_automation: bool = False) -> Optional[bool]:
        """
        Запуск отопления (ручной или автоматический по порогу).
        Если операция уже выполняется другим запросом, возвращает None.
        """
        if self._lock.locked():
            logger.warning("[start] Операция уже выполняется другим запросом. Запрос отклонен.")
            return None

        async with self._lock:
            latest_on = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
            if latest_on and latest_on.get("status_heating") is True:
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

            data_to_history: Dict[str, Any] = {
                "id": latest_sensor["id"],
                "timestamp": latest_sensor["timestamp"],
                "status_heating": True,
                "stop_heat_plus": 0,
                "automation_start": is_automation,
                "automation_stop": False,
            }
            data_to_heating_table: Dict[str, Any] = {
                "id": 1,
                "status_heating": True
            }

            await self.repo.upsert_record("heating_table", data_to_heating_table, pk_col="id", log_to_api=False)
            await self.repo.upsert_record("history_of_heating", data_to_history, pk_col="id", log_to_api=False)  
            
            logger.info(
                f"[start] Успешный запуск отопления зафиксирован в БД: sensor_id={latest_sensor['id']}"
            )
            return True

    async def stop(self, is_automation: bool = False, stop_forcibly: int = 0) -> Optional[bool]:
        """
        Остановка отопления (ручная или автоматическая по порогу).
        Если операция уже выполняется другим запросом, возвращает None.
        """
        if self._lock.locked():
            logger.warning("[stop] Операция уже выполняется другим запросом. Запрос отклонен.")
            return None

        async with self._lock:
            latest_heat = await self.repo.get_latest_record("history_of_heating", order_by_col="id", log_to_api=False)
            latest_off = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
            if not latest_off or not latest_off.get("status_heating"):
                logger.info("[stop] Отопление выключено. Остановка пропущена.")
                return False

            latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
            current_sensor_id = latest_sensor["id"] if (latest_sensor and "id" in latest_sensor) else latest_heat["id"]
            heat_start_id = latest_heat["id"]
            stop_heat_plus = max(0, current_sensor_id - heat_start_id)

            turn_off_success = await self.relay.turn_off(stop_programm=stop_forcibly)
            relay_state = await self.relay.get_state()

            if not turn_off_success or relay_state:
                logger.error(
                    "[stop] Сбой или блокировка выключения реле: turn_off=%s, get_state=%s. Запись в БД отменена.",
                    turn_off_success,
                    relay_state,
                )
                return False

            if stop_heat_plus == 0:
                await self.repo.delete_record_by_id("history_of_heating", heat_start_id, pk_col="id", log_to_api=False)
                logger.info(f"[stop] Запись отопления удалена (stop_heat_plus=0): id={heat_start_id}")
            else:
                data_to_history: Dict[str, Any] = {
                    "id": heat_start_id,
                    "timestamp": latest_heat["timestamp"],
                    "status_heating": False,
                    "stop_heat_plus": stop_heat_plus,
                    "automation_start": latest_heat.get("automation_start", False),
                    "automation_stop": is_automation,
                }
                data_to_heating_table: Dict[str, Any] = {
                    "id": 1,
                    "status_heating": False
                }
                
                await self.repo.upsert_record("heating_table", data_to_heating_table, pk_col="id", log_to_api=False)
                await self.repo.upsert_record("history_of_heating", data_to_history, pk_col="id", log_to_api=False)
                logger.info(
                    f"[stop] Зафиксирована остановка отопления: start_id={heat_start_id}, "
                    f"current_id={current_sensor_id}, diff={stop_heat_plus}"
                )

            return True

    async def check_temperature(self, temperature: float) -> Optional[bool]:
        latest_heating = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        if not latest_heating or not latest_heating.get("temperature_start") or not latest_heating.get("temperature_stop"):
            logger.warning("[check_temperature] Нет записей в heating_table")
            return False

        minimum_temperature = latest_heating.get("temperature_start")
        maximum_temperature = latest_heating.get("temperature_stop")

        if temperature <= minimum_temperature:
            if latest_heating.get("status_heating"):
                return False
            else:
                logger.info(
                    f"[check_temperature] Температура : {temperature}°C <= {minimum_temperature}°C. Автозапуск отопления."
                )
                res = await self.start(is_automation=True)
                return res if res is not None else False
            
        if temperature >= maximum_temperature:
            if not latest_heating.get("status_heating"):
                return False
            else:
                logger.info(
                    f"[check_temperature] Температура : {temperature}°C >= {maximum_temperature}°C. Автоостановка отопления."
                )
                res = await self.stop(is_automation=True)
                return res if res is not None else False

        return False

    async def min_max_temperature(self, sensor_record: Dict[str, Any]) -> None:
        """
        Защитная проверка температурных порогов (минимум и максимум из settings_table).
        """
        if not sensor_record:
            return

        basement_temp = sensor_record.get("basement_temp")
        if basement_temp is None:
            return

        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        minimum_temperature = getattr(sys_settings, "minimum_temperature", None)
        maximum_temperature = getattr(sys_settings, "maximum_temperature", None)

        latest_heat = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
        is_heating_active = bool(latest_heat and latest_heat.get("status_heating"))

        if not is_heating_active:
            if minimum_temperature is not None and basement_temp <= minimum_temperature:
                logger.warning(
                    f"[min_max_temperature] Критическое снижение температуры подвала: {basement_temp}°C <= {minimum_temperature}°C. Аварийный автозапуск."
                )
                await self.start(is_automation=True)
        else:
            if maximum_temperature is not None and basement_temp >= maximum_temperature:
                logger.warning(
                    f"[min_max_temperature] Превышен критический максимум температуры ({basement_temp}°C >= {maximum_temperature}°C). Аварийная автоостановка."
                )
                await self.stop(is_automation=True)



# # app/services/heating_service.py

# import logging
# from typing import Any, Dict

# from app.db.repository import BaseRepository
# from app.services.relay_service import RelayController

# logger = logging.getLogger("climat_app.heating_controller")


# class HeatingController:
#     """
#     Контроллер управления логикой отопления и физическим состоянием USB-реле котла.
#     """

#     def __init__(self, repo: BaseRepository, relay: RelayController) -> None:
#         self.repo = repo
#         self.relay = relay

#     async def start(self, is_automation: bool = False) -> bool:
#         """
#         Запуск отопления (ручной или автоматический по порогу).
#         """
#         latest_on = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
#         if latest_on and latest_on.get("status_heating") is True:
#             logger.info("[start] Отопление уже запущено. Запуск пропущен.")
#             return False

#         latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#         if not latest_sensor or "id" not in latest_sensor or "timestamp" not in latest_sensor:
#             logger.warning("[start] Отсутствуют корректные данные в table_sensor_data. Запуск отопления отменен.")
#             return False

#         turn_on_success = await self.relay.turn_on()
#         relay_state = await self.relay.get_state()

#         if not turn_on_success or not relay_state:
#             logger.error(
#                 "[start] Сбой или блокировка включения реле: turn_on=%s, get_state=%s. Запись в БД отменена.",
#                 turn_on_success,
#                 relay_state,
#             )
#             return False

#         data_to_history: Dict[str, Any] = {
#             "id": latest_sensor["id"],
#             "timestamp": latest_sensor["timestamp"],
#             "status_heating": True,
#             "stop_heat_plus": 0,
#             "automation_start": is_automation,
#             "automation_stop": False,
#         }
#         data_to_heating_table: Dict[str, Any] = {
#             "id": 1,
#             "status_heating": True
#         }

#         await self.repo.upsert_record("heating_table", data_to_heating_table, pk_col="id", log_to_api=False)
#         await self.repo.upsert_record("history_of_heating", data_to_history, pk_col="id", log_to_api=False)  
        
#         logger.info(
#             f"[start] Успешный запуск отопления зафиксирован в БД: sensor_id={latest_sensor['id']}"
#         )
#         return True

#     async def stop(self, is_automation: bool = False, stop_forcibly: int = 0) -> bool:
#         """
#         Остановка отопления (ручная или автоматическая по порогу).
#         """
#         latest_heat = await self.repo.get_latest_record("history_of_heating", order_by_col="id", log_to_api=False)
#         latest_off = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
#         if not latest_off or not latest_off.get("status_heating"):
#             logger.info("[stop] Отопление выключено. Остановка пропущена.")
#             return False

#         latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#         current_sensor_id = latest_sensor["id"] if (latest_sensor and "id" in latest_sensor) else latest_heat["id"]
#         heat_start_id = latest_heat["id"]
#         stop_heat_plus = max(0, current_sensor_id - heat_start_id)

#         turn_off_success = await self.relay.turn_off(stop_programm=stop_forcibly)
#         relay_state = await self.relay.get_state()

#         if not turn_off_success or relay_state:
#             logger.error(
#                 "[stop] Сбой или блокировка выключения реле: turn_off=%s, get_state=%s. Запись в БД отменена.",
#                 turn_off_success,
#                 relay_state,
#             )
#             return False

#         if stop_heat_plus == 0:
#             await self.repo.delete_record_by_id("history_of_heating", heat_start_id, pk_col="id", log_to_api=False)
#             logger.info(f"[stop] Запись отопления удалена (stop_heat_plus=0): id={heat_start_id}")
#         else:
#             data_to_history: Dict[str, Any] = {
#                 "id": heat_start_id,
#                 "timestamp": latest_heat["timestamp"],
#                 "status_heating": False,
#                 "stop_heat_plus": stop_heat_plus,
#                 "automation_start": latest_heat.get("automation_start", False),
#                 "automation_stop": is_automation,
#             }
#             data_to_heating_table: Dict[str, Any] = {
#                 "id": 1,
#                 "status_heating": False
#             }
            
#             await self.repo.upsert_record("heating_table", data_to_heating_table, pk_col="id", log_to_api=False)
#             await self.repo.upsert_record("history_of_heating", data_to_history, pk_col="id", log_to_api=False)
#             logger.info(
#                 f"[stop] Зафиксирована остановка отопления: start_id={heat_start_id}, "
#                 f"current_id={current_sensor_id}, diff={stop_heat_plus}"
#             )

#         return True

#     async def check_temperature(self, temperature: float) -> bool:
#         latest_heating = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
#         if not latest_heating or not latest_heating.get("temperature_start") or not latest_heating.get("temperature_stop"):
#             logger.warning("[check_temperature] Нет записей в heating_table")
#             return False

#         minimum_temperature = latest_heating.get("temperature_start")
#         maximum_temperature = latest_heating.get("temperature_stop")

#         if temperature <= minimum_temperature:
#             if latest_heating.get("status_heating"):
#                 return False
#             else:
#                 logger.info(
#                     f"[check_temperature] Температура : {temperature}°C <= {minimum_temperature}°C. Автозапуск отопления."
#                 )
#                 await self.start(is_automation=True)
#                 return True
            
#         if temperature >= maximum_temperature:
#             if not latest_heating.get("status_heating"):
#                 return False
#             else:
#                 logger.info(
#                     f"[check_temperature] Температура : {temperature}°C >= {maximum_temperature}°C. Автоостановка отопления."
#                 )
#                 await self.stop(is_automation=True)
#                 return True

#         return False

#     async def min_max_temperature(self, sensor_record: Dict[str, Any]) -> None:
#         """
#         Защитная проверка температурных порогов (минимум и максимум из settings_table).
#         """
#         if not sensor_record:
#             return

#         basement_temp = sensor_record.get("basement_temp")
#         if basement_temp is None:
#             return

#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         minimum_temperature = getattr(sys_settings, "minimum_temperature", None)
#         maximum_temperature = getattr(sys_settings, "maximum_temperature", None)

#         latest_heat = await self.repo.get_latest_record("heating_table", order_by_col="id", log_to_api=False)
#         is_heating_active = bool(latest_heat and latest_heat.get("status_heating"))

#         if not is_heating_active:
#             if minimum_temperature is not None and basement_temp <= minimum_temperature:
#                 logger.warning(
#                     f"[min_max_temperature] Критическое снижение температуры подвала: {basement_temp}°C <= {minimum_temperature}°C. Аварийный автозапуск."
#                 )
#                 await self.start(is_automation=True)
#         else:
#             if maximum_temperature is not None and basement_temp >= maximum_temperature:
#                 logger.warning(
#                     f"[min_max_temperature] Превышен критический максимум температуры ({basement_temp}°C >= {maximum_temperature}°C). Аварийная автоостановка."
#                 )
#                 await self.stop(is_automation=True)