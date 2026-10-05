# app/services/heating_service.py

import logging
from typing import Any, Dict

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

    async def stop(self, is_automation: bool = False, stop_forcibly: int = 0) -> bool:
        """
        Остановка отопления (ручная или автоматическая по порогу).
        """
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

    async def check_temperature(self, temperature: float) -> bool:
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
                await self.start(is_automation=True)
                return True
            
        if temperature >= maximum_temperature:
            if not latest_heating.get("status_heating"):
                return False
            else:
                logger.info(
                    f"[check_temperature] Температура : {temperature}°C >= {maximum_temperature}°C. Автоостановка отопления."
                )
                await self.stop(is_automation=True)
                return True

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
# from datetime import datetime
# from typing import Any, Dict, Optional

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


# # class Programmer:
# #     """
# #     Класс программатора для управления режимами отопления.
# #     """

# #     def __init__(self, repo: BaseRepository, heating_controller: HeatingController) -> None:
# #         self.repo = repo
# #         self.heating_controller = heating_controller

# #     def _calculate_target_datetime(self, updated_at_str: str, temporarily_time_str: str) -> Optional[datetime]:
# #         """
# #         Вычисление точной даты и времени окончания временного режима с учетом перехода через сутки.
# #         """
# #         if not updated_at_str or not temporarily_time_str:
# #             logger.debug("[_calculate_target_datetime] Отсутствует время или дата установки для расчета окончания.")
# #             return None

# #         try:
# #             updated_at_dt = datetime.strptime(updated_at_str[:19], "%Y-%m-%d %H:%M:%S")
# #             time_parts = temporarily_time_str.strip().split(":")
# #             hours = int(time_parts[0])
# #             minutes = int(time_parts[1]) if len(time_parts) > 1 else 0

# #             target_dt = updated_at_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0)

# #             if target_dt <= updated_at_dt:
# #                 target_dt += timedelta(days=1)
# #                 logger.debug(
# #                     f"[_calculate_target_datetime] Переход через сутки: установка {updated_at_dt}, "
# #                     f"целевое время {temporarily_time_str} -> окончание {target_dt}"
# #                 )
# #             else:
# #                 logger.debug(
# #                     f"[_calculate_target_datetime] Окончание в тот же день: установка {updated_at_dt}, "
# #                     f"целевое время {temporarily_time_str} -> окончание {target_dt}"
# #                 )

# #             return target_dt
# #         except Exception as e:
# #             logger.error(f"[_calculate_target_datetime] Ошибка расчета target_datetime: {e}")
# #             return None

# #     async def evaluate(self) -> None:
# #         """
# #         Основной метод проверки programmer_mode, оценки времени действия уставок и выбора режима.
# #         """
# #         sys_settings = await self.repo.get_settings_db(log_to_api=False)
# #         programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")
# #         logger.debug(f"[evaluate] Старт проверки. Текущий режим программатора: {programmer_mode}")

# #         now = datetime.now()

# #         if programmer_mode == "PROGRAMMER_CONST":
# #             logger.debug("[evaluate] Выполнение логики ПОСТОЯННОГО режима.")
# #             await self._process_programmer_const()

# #         elif programmer_mode == "PROGRAMMER_TEMPORARILY_CONST":
# #             record = await self.repo.get_record_by_id("programmer_temporarily", 1)
# #             is_expired = False

# #             if record and record.get("updated_at") and record.get("temporarily_time"):
# #                 target_dt = self._calculate_target_datetime(
# #                     str(record["updated_at"]),
# #                     str(record["temporarily_time"])
# #                 )
# #                 if target_dt and now >= target_dt:
# #                     is_expired = True
# #                     logger.info(
# #                         f"[evaluate] Время действия временного режима истекло ({now} >= {target_dt}). "
# #                         f"Автоматический возврат в PROGRAMMER_CONST."
# #                     )

# #             if is_expired:
# #                 await self.repo.upsert_record(
# #                     "settings_table",
# #                     {"id": 1, "programmer_mode": "PROGRAMMER_CONST"},
# #                     pk_col="id",
# #                 )
# #                 await self._process_programmer_const()
# #             else:
# #                 logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_CONST активен.")
# #                 await self._process_programmer_temporarily()

# #         elif programmer_mode == "PROGRAMMER_TEMPORARILY_WEEK":
# #             record = await self.repo.get_record_by_id("programmer_temporarily", 1)
# #             is_expired = False
# #             temp_time = record.get("temporarily_time") if record else None

# #             if record and record.get("updated_at") and temp_time and str(temp_time).strip() not in ("", "00:00", "0"):
# #                 target_dt = self._calculate_target_datetime(
# #                     str(record["updated_at"]),
# #                     str(temp_time)
# #                 )
# #                 if target_dt and now >= target_dt:
# #                     is_expired = True
# #                     logger.info(
# #                         f"[evaluate] Время действия временного режима истекло ({now} >= {target_dt}). "
# #                         f"Автоматический возврат в PROGRAMMER_WEEK."
# #                     )

# #             if is_expired:
# #                 await self.repo.upsert_record(
# #                     "settings_table",
# #                     {"id": 1, "programmer_mode": "PROGRAMMER_WEEK"},
# #                     pk_col="id",
# #                 )
# #                 await self._process_programmer_week()
# #             else:
# #                 logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_WEEK активен.")
# #                 await self._process_programmer_temporarily()

# #         elif programmer_mode == "PROGRAMMER_WEEK":
# #             logger.debug("[evaluate] Выполнение логики НЕДЕЛЬНОГО режима.")
# #             await self._process_programmer_week()

# #     async def update_programmer_mode(self, flag_temporarily: bool = False, flag_const: bool = False) -> str:
# #         """
# #         Определение и обновление нового режима работы программатора в БД.
# #         """
# #         sys_settings = await self.repo.get_settings_db(log_to_api=False)
# #         current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

# #         if flag_temporarily:
# #             if current_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK"):
# #                 new_mode = "PROGRAMMER_TEMPORARILY_WEEK"
# #             else:
# #                 new_mode = "PROGRAMMER_TEMPORARILY_CONST"
# #         elif flag_const:
# #             new_mode = "PROGRAMMER_CONST"
# #         else:
# #             new_mode = current_mode if current_mode else "PROGRAMMER_CONST"

# #         logger.debug(f"[update_programmer_mode] Смена режима: {current_mode} -> {new_mode}")

# #         await self.repo.upsert_record(
# #             "settings_table",
# #             {"id": 1, "programmer_mode": new_mode},
# #             pk_col="id",
# #         )
# #         return new_mode

# #     async def save_programmer_const(self, const_min: float, const_max: float) -> bool:
# #         """
# #         Сохранение настроек постоянного режима (строка id=1).
# #         """
# #         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         data = {
# #             "id": 1,
# #             "const_min": const_min,
# #             "const_max": const_max,
# #             "updated_at": now_str,
# #         }
# #         logger.debug(f"[save_programmer_const] Запись в programmer_const: {data}")
# #         await self.repo.upsert_record("programmer_const", data, pk_col="id")
# #         return True

# #     async def save_programmer_temporarily(self, temporarily: float, temporarily_time: Optional[str] = None) -> bool:
# #         """
# #         Сохранение настроек временного режима (строка id=1).
# #         """
# #         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         data = {
# #             "id": 1,
# #             "temporarily": temporarily,
# #             "temporarily_time": temporarily_time,
# #             "updated_at": now_str,
# #         }
# #         logger.debug(f"[save_programmer_temporarily] Запись в programmer_temporarily: {data}")
# #         await self.repo.upsert_record("programmer_temporarily", data, pk_col="id")
# #         return True

# #     async def _process_programmer_const(self) -> bool:
# #         logger.debug("[_process_programmer_const] Загрузка настроек постоянного режима из БД.")
# #         record = await self.repo.get_record_by_id("programmer_const", 1)
# #         if not record:
# #             logger.warning("Запись с id=1 в таблице programmer_const не найдена.")
# #             return False

# #         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         heating_data = {
# #             "id": 1,
# #             "temperature_start": record["const_min"],
# #             "temperature_stop": record["const_max"],
# #             "updated_at": now_str,
# #         }
# #         await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
# #         logger.debug(f"[_process_programmer_const] Установлены пороги отопления в heating_table: {heating_data}")
# #         return True

# #     async def _process_programmer_temporarily(self) -> bool:
# #         logger.debug("[_process_programmer_temporarily] Загрузка настроек временного режима из БД.")
# #         record = await self.repo.get_record_by_id("programmer_temporarily", 1)
# #         if not record or record.get("temporarily") is None:
# #             logger.warning("Запись с id=1 в таблице programmer_temporarily не найдена.")
# #             return False

# #         sys_settings = await self.repo.get_settings_db(log_to_api=False)
# #         hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
# #         if hysteresis is None:
# #             hysteresis = 1.0

# #         temporarily = float(record["temporarily"])
# #         temperature_start = round(temporarily - hysteresis / 2, 1)
# #         temperature_stop = round(temporarily + hysteresis / 2, 1)

# #         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         heating_data = {
# #             "id": 1,
# #             "temperature_start": temperature_start,
# #             "temperature_stop": temperature_stop,
# #             "updated_at": now_str,
# #         }
# #         await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
# #         logger.debug(f"[_process_programmer_temporarily] Установлены пороги отопления в heating_table: {heating_data}")
# #         return True

# #     async def _process_programmer_week(self) -> None:
# #         logger.debug("[_process_programmer_week] Вызов логики недельного режима (заготовка).")
# #         pass


   