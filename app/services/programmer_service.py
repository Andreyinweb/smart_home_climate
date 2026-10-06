# app/services/programmer_service.py

from datetime import datetime, timedelta
import logging
from typing import Optional

from app.db.repository import BaseRepository
from app.services.heating_service import HeatingController

logger = logging.getLogger("climat_app.programmer_service")


class Programmer:
    """
    Класс программатора для управления режимами отопления.
    """

    def __init__(self, repo: BaseRepository, heating_controller: HeatingController) -> None:
        self.repo = repo
        self.heating_controller = heating_controller

    def _calculate_target_datetime(self, updated_at_str: str, temporarily_time_str: str) -> Optional[datetime]:
        """
        Вычисление точной даты и времени окончания временного режима с учетом перехода через сутки.
        """
        if not updated_at_str or not temporarily_time_str:
            logger.debug("[_calculate_target_datetime] Отсутствует время или дата установки для расчета окончания.")
            return None

        try:
            updated_at_dt = datetime.strptime(updated_at_str[:19], "%Y-%m-%d %H:%M:%S")
            time_parts = temporarily_time_str.strip().split(":")
            hours = int(time_parts[0])
            minutes = int(time_parts[1]) if len(time_parts) > 1 else 0

            target_dt = updated_at_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0)

            if target_dt <= updated_at_dt:
                target_dt += timedelta(days=1)
                logger.debug(
                    f"[_calculate_target_datetime] Переход через сутки: установка {updated_at_dt}, "
                    f"целевое время {temporarily_time_str} -> окончание {target_dt}"
                )
            else:
                logger.debug(
                    f"[_calculate_target_datetime] Окончание в тот же день: установка {updated_at_dt}, "
                    f"целевое время {temporarily_time_str} -> окончание {target_dt}"
                )

            return target_dt
        except Exception as e:
            logger.error(f"[_calculate_target_datetime] Ошибка расчета target_datetime: {e}")
            return None

    async def evaluate(self) -> None:
        """
        Основной метод проверки programmer_mode, оценки времени действия уставок и выбора режима.
        """
        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")
        logger.debug(f"[evaluate] Старт проверки. Текущий режим программатора: {programmer_mode}")

        now = datetime.now()

        if programmer_mode == "PROGRAMMER_CONST":
            logger.debug("[evaluate] Выполнение логики ПОСТОЯННОГО режима.")
            await self._process_programmer_const()

        elif programmer_mode == "PROGRAMMER_WEEK":
            logger.debug("[evaluate] Выполнение логики НЕДЕЛЬНОГО режима.")
            record = await self.repo.get_record_by_id("programmer_week", 1)
            if not record or not record.get("week_time"):
                logger.warning("[evaluate] Запись с id=1 в programmer_week не найдена или отсутствует week_time.")
                return

            try:
                target_dt = datetime.strptime(str(record["week_time"])[:19], "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning(f"[evaluate] Ошибка парсинга week_time ({record.get('week_time')}): {e}")
                return

            if now >= target_dt:
                logger.info(f"[evaluate] Время текущего цикла недельного режима истекло ({now} >= {target_dt}). Переход к следующему циклу.")
                await self._advance_programmer_week_cycle()

            await self._process_programmer_week()

        elif programmer_mode == "PROGRAMMER_TEMPORARILY_CONST":
            record = await self.repo.get_record_by_id("programmer_temporarily", 1)
            is_expired = False

            temp_time_str = record.get("temporarily_time") if record else None
            if not temp_time_str or str(temp_time_str).strip() in ("", "0", "00:00", "None"):
                is_expired = True
            else:
                try:
                    target_dt = datetime.strptime(str(temp_time_str)[:19], "%Y-%m-%d %H:%M:%S")
                    if now >= target_dt:
                        is_expired = True
                except Exception as e:
                    logger.error(f"[evaluate] Ошибка парсинга target_dt ({temp_time_str}): {e}")
                    is_expired = True

            if is_expired:
                logger.info("[evaluate] Время действия временного режима истекло или не задано. Возврат в PROGRAMMER_CONST.")
                await self.repo.upsert_record(
                    "settings_table",
                    {"id": 1, "programmer_mode": "PROGRAMMER_CONST"},
                    pk_col="id",
                )
                await self._process_programmer_const()
            else:
                logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_CONST активен.")
                await self._process_programmer_temporarily()

        elif programmer_mode == "PROGRAMMER_TEMPORARILY_WEEK":
            record = await self.repo.get_record_by_id("programmer_temporarily", 1)
            is_expired = False
            temp_time_str = record.get("temporarily_time") if record else None

            if not temp_time_str or str(temp_time_str).strip() in ("", "0", "00:00", "None"):
                is_expired = True
            else:
                try:
                    target_dt = datetime.strptime(str(temp_time_str)[:19], "%Y-%m-%d %H:%M:%S")
                    if now >= target_dt:
                        is_expired = True
                except Exception as e:
                    logger.error(f"[evaluate] Ошибка парсинга target_dt в TEMPORARILY_WEEK: {e}")
                    is_expired = True

            if is_expired:
                logger.info("[evaluate] Время действия временного режима истекло. Возврат в PROGRAMMER_WEEK.")
                await self.repo.upsert_record(
                    "settings_table",
                    {"id": 1, "programmer_mode": "PROGRAMMER_WEEK"},
                    pk_col="id",
                )
                record_week = await self.repo.get_record_by_id("programmer_week", 1)
                if not record_week or not record_week.get("week_time"):
                    logger.warning("[evaluate] Запись с id=1 в programmer_week не найдена при переходе из TEMPORARILY_WEEK.")
                    return
                try:
                    target_dt_week = datetime.strptime(str(record_week["week_time"])[:19], "%Y-%m-%d %H:%M:%S")
                    if now >= target_dt_week:
                        await self._advance_programmer_week_cycle()
                except Exception as e:
                    logger.warning(f"[evaluate] Ошибка парсинга week_time при переходе из TEMPORARILY_WEEK: {e}")
                    return

                await self._process_programmer_week()
            else:
                logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_WEEK активен.")
                await self._process_programmer_temporarily()

    async def _advance_programmer_week_cycle(self) -> None:
        """
        Переключение системной строки (id=1) таблицы programmer_week на следующий цикл.
        """
        sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
        if not sys_rec:
            logger.warning("[_advance_programmer_week_cycle] Системная запись с id=1 не найдена в programmer_week.")
            return

        next_id = sys_rec.get("next_id")
        if not next_id:
            logger.warning("[_advance_programmer_week_cycle] Поле next_id не задано в системной строке id=1.")
            return

        next_rec = await self.repo.get_record_by_id("programmer_week", next_id)
        if not next_rec:
            logger.warning(f"[_advance_programmer_week_cycle] Запись с id={next_id} не найдена в programmer_week.")
            return

        after_next_id = next_rec.get("next_id")
        if not after_next_id:
            logger.warning(f"[_advance_programmer_week_cycle] Поле next_id не задано в записи id={next_id}.")
            return

        after_next_rec = await self.repo.get_record_by_id("programmer_week", after_next_id)
        if not after_next_rec or not after_next_rec.get("week_time"):
            logger.warning(f"[_advance_programmer_week_cycle] Запись id={after_next_id} не найдена или не имеет week_time.")
            return

        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        end_time_str = str(after_next_rec["week_time"]).strip()
        target_dt = self._calculate_target_datetime(now_str, end_time_str)

        if not target_dt:
            logger.warning(f"[_advance_programmer_week_cycle] Не удалось рассчитать целевую дату/время для окончания {end_time_str}.")
            return

        update_data = {
            "id": 1,
            "now_id": next_rec.get("id"),
            "next_id": after_next_id,
            "week_mode": next_rec.get("week_mode"),
            "week_day": next_rec.get("week_day"),
            "week_time": target_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "week_temperature": next_rec.get("week_temperature"),
            "updated_at": now_str,
        }

        await self.repo.upsert_record("programmer_week", update_data, pk_col="id")
        logger.debug(f"[_advance_programmer_week_cycle] Системная строка id=1 обновлена: {update_data}")

    async def update_programmer_mode(self, flag_temporarily: bool = False, flag_const: bool = False) -> str:
        """
        Определение и обновление нового режима работы программатора в БД.
        """
        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

        if flag_temporarily:
            if current_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK"):
                new_mode = "PROGRAMMER_TEMPORARILY_WEEK"
            else:
                new_mode = "PROGRAMMER_TEMPORARILY_CONST"
        elif flag_const:
            new_mode = "PROGRAMMER_CONST"
        else:
            new_mode = current_mode if current_mode else "PROGRAMMER_CONST"

        logger.debug(f"[update_programmer_mode] Смена режима: {current_mode} -> {new_mode}")

        await self.repo.upsert_record(
            "settings_table",
            {"id": 1, "programmer_mode": new_mode},
            pk_col="id",
        )
        return new_mode

    async def save_programmer_const(self, const_min: float, const_max: float) -> bool:
        """
        Сохранение настроек постоянного режима (строка id=1).
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "id": 1,
            "const_min": const_min,
            "const_max": const_max,
            "updated_at": now_str,
        }
        logger.debug(f"[save_programmer_const] Запись в programmer_const: {data}")
        await self.repo.upsert_record("programmer_const", data, pk_col="id")
        return True

    async def save_programmer_temporarily(self, temporarily: float, temporarily_time: Optional[str] = None) -> bool:
        """
        Сохранение настроек временного режима (строка id=1) с расчетом и сохранением конечной даты и времени в temporarily_time.
        """
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        target_dt = None
        if temporarily_time and str(temporarily_time).strip() not in ("", "0", "00:00", "None"):
            target_dt = self._calculate_target_datetime(now_str, str(temporarily_time))

        target_time_str = target_dt.strftime("%Y-%m-%d %H:%M:%S") if target_dt else None

        data = {
            "id": 1,
            "temporarily": temporarily,
            "temporarily_time": target_time_str,
            "updated_at": now_str,
        }
        logger.debug(f"[save_programmer_temporarily] Запись в programmer_temporarily: {data}")
        await self.repo.upsert_record("programmer_temporarily", data, pk_col="id")
        return True

    async def _process_programmer_const(self) -> bool:
        logger.debug("[_process_programmer_const] Загрузка настроек постоянного режима из БД.")
        record = await self.repo.get_record_by_id("programmer_const", 1)
        if not record:
            logger.warning("Запись с id=1 в таблице programmer_const не найдена.")
            return False

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        heating_data = {
            "id": 1,
            "temperature_start": record["const_min"],
            "temperature_stop": record["const_max"],
            "updated_at": now_str,
        }
        await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
        logger.debug(f"[_process_programmer_const] Установлены пороги отопления в heating_table: {heating_data}")
        return True

    async def _process_programmer_temporarily(self) -> bool:
        logger.debug("[_process_programmer_temporarily] Загрузка настроек временного режима из БД.")
        record = await self.repo.get_record_by_id("programmer_temporarily", 1)
        if not record or record.get("temporarily") is None:
            logger.warning("Запись с id=1 в таблице programmer_temporarily не найдена.")
            return False

        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
        if hysteresis is None:
            hysteresis = 1.0

        temporarily = float(record["temporarily"])
        temperature_start = round(temporarily - hysteresis / 2, 1)
        temperature_stop = round(temporarily + hysteresis / 2, 1)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        heating_data = {
            "id": 1,
            "temperature_start": temperature_start,
            "temperature_stop": temperature_stop,
            "updated_at": now_str,
        }
        await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
        logger.debug(f"[_process_programmer_temporarily] Установлены пороги отопления в heating_table: {heating_data}")
        return True

    async def _process_programmer_week(self) -> bool:
        logger.debug("[_process_programmer_week] Загрузка настроек недельного режима из системной строки id=1 таблицы programmer_week.")
        record = await self.repo.get_record_by_id("programmer_week", 1)
        if not record or record.get("week_temperature") is None:
            logger.warning("Запись с id=1 в таблице programmer_week не найдена или week_temperature отсутствует.")
            return False

        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
        if hysteresis is None:
            hysteresis = 1.0

        week_temp = float(record["week_temperature"])
        temperature_start = round(week_temp - hysteresis / 2, 1)
        temperature_stop = round(week_temp + hysteresis / 2, 1)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        heating_data = {
            "id": 1,
            "temperature_start": temperature_start,
            "temperature_stop": temperature_stop,
            "updated_at": now_str,
        }
        await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
        logger.debug(f"[_process_programmer_week] Установлены пороги отопления в heating_table: {heating_data}")
        return True



# # app/services/programmer_service.py

# from datetime import datetime, timedelta
# import logging
# from typing import Optional

# from app.db.repository import BaseRepository
# from app.services.heating_service import HeatingController

# logger = logging.getLogger("climat_app.programmer_service")


# class Programmer:
#     """
#     Класс программатора для управления режимами отопления.
#     """

#     def __init__(self, repo: BaseRepository, heating_controller: HeatingController) -> None:
#         self.repo = repo
#         self.heating_controller = heating_controller

#     def _calculate_target_datetime(self, updated_at_str: str, temporarily_time_str: str) -> Optional[datetime]:
#         """
#         Вычисление точной даты и времени окончания временного режима с учетом перехода через сутки.
#         """
#         if not updated_at_str or not temporarily_time_str:
#             logger.debug("[_calculate_target_datetime] Отсутствует время или дата установки для расчета окончания.")
#             return None

#         try:
#             updated_at_dt = datetime.strptime(updated_at_str[:19], "%Y-%m-%d %H:%M:%S")
#             time_parts = temporarily_time_str.strip().split(":")
#             hours = int(time_parts[0])
#             minutes = int(time_parts[1]) if len(time_parts) > 1 else 0

#             target_dt = updated_at_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0)

#             if target_dt <= updated_at_dt:
#                 target_dt += timedelta(days=1)
#                 logger.debug(
#                     f"[_calculate_target_datetime] Переход через сутки: установка {updated_at_dt}, "
#                     f"целевое время {temporarily_time_str} -> окончание {target_dt}"
#                 )
#             else:
#                 logger.debug(
#                     f"[_calculate_target_datetime] Окончание в тот же день: установка {updated_at_dt}, "
#                     f"целевое время {temporarily_time_str} -> окончание {target_dt}"
#                 )

#             return target_dt
#         except Exception as e:
#             logger.error(f"[_calculate_target_datetime] Ошибка расчета target_datetime: {e}")
#             return None

#     async def evaluate(self) -> None:
#         """
#         Основной метод проверки programmer_mode, оценки времени действия уставок и выбора режима.
#         """
#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")
#         logger.debug(f"[evaluate] Старт проверки. Текущий режим программатора: {programmer_mode}")

#         if programmer_mode == "PROGRAMMER_CONST":
#             logger.debug("[evaluate] Выполнение логики ПОСТОЯННОГО режима.")
#             await self._process_programmer_const()

#         elif programmer_mode == "PROGRAMMER_WEEK":
#             logger.debug("[evaluate] Выполнение логики НЕДЕЛЬНОГО режима.")
#             await self._process_programmer_week()

#         elif programmer_mode == "PROGRAMMER_TEMPORARILY_CONST":
#             record = await self.repo.get_record_by_id("programmer_temporarily", 1)
#             now = datetime.now()
#             is_expired = False

#             temp_time_str = record.get("temporarily_time") if record else None
#             if not temp_time_str or str(temp_time_str).strip() in ("", "0", "00:00", "None"):
#                 is_expired = True
#             else:
#                 try:
#                     target_dt = datetime.strptime(str(temp_time_str)[:19], "%Y-%m-%d %H:%M:%S")
#                     if now >= target_dt:
#                         is_expired = True
#                 except Exception as e:
#                     logger.error(f"[evaluate] Ошибка парсинга target_dt ({temp_time_str}): {e}")
#                     is_expired = True

#             if is_expired:
#                 logger.info("[evaluate] Время действия временного режима истекло или не задано. Возврат в PROGRAMMER_CONST.")
#                 await self.repo.upsert_record(
#                     "settings_table",
#                     {"id": 1, "programmer_mode": "PROGRAMMER_CONST"},
#                     pk_col="id",
#                 )
#                 await self._process_programmer_const()
#             else:
#                 logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_CONST активен.")
#                 await self._process_programmer_temporarily()

#         elif programmer_mode == "PROGRAMMER_TEMPORARILY_WEEK":
#             logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_WEEK активен.")
#             await self._process_programmer_temporarily()

#     async def update_programmer_mode(self, flag_temporarily: bool = False, flag_const: bool = False) -> str:
#         """
#         Определение и обновление нового режима работы программатора в БД.
#         """
#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

#         if flag_temporarily:
#             if current_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK"):
#                 new_mode = "PROGRAMMER_TEMPORARILY_WEEK"
#             else:
#                 new_mode = "PROGRAMMER_TEMPORARILY_CONST"
#         elif flag_const:
#             new_mode = "PROGRAMMER_CONST"
#         else:
#             new_mode = current_mode if current_mode else "PROGRAMMER_CONST"

#         logger.debug(f"[update_programmer_mode] Смена режима: {current_mode} -> {new_mode}")

#         await self.repo.upsert_record(
#             "settings_table",
#             {"id": 1, "programmer_mode": new_mode},
#             pk_col="id",
#         )
#         return new_mode

#     async def save_programmer_const(self, const_min: float, const_max: float) -> bool:
#         """
#         Сохранение настроек постоянного режима (строка id=1).
#         """
#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         data = {
#             "id": 1,
#             "const_min": const_min,
#             "const_max": const_max,
#             "updated_at": now_str,
#         }
#         logger.debug(f"[save_programmer_const] Запись в programmer_const: {data}")
#         await self.repo.upsert_record("programmer_const", data, pk_col="id")
#         return True

#     async def save_programmer_temporarily(self, temporarily: float, temporarily_time: Optional[str] = None) -> bool:
#         """
#         Сохранение настроек временного режима (строка id=1) с расчетом и сохранением конечной даты и времени в temporarily_time.
#         """
#         now_dt = datetime.now()
#         now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

#         target_dt = None
#         if temporarily_time and str(temporarily_time).strip() not in ("", "0", "00:00", "None"):
#             target_dt = self._calculate_target_datetime(now_str, str(temporarily_time))

#         target_time_str = target_dt.strftime("%Y-%m-%d %H:%M:%S") if target_dt else None

#         data = {
#             "id": 1,
#             "temporarily": temporarily,
#             "temporarily_time": target_time_str,
#             "updated_at": now_str,
#         }
#         logger.debug(f"[save_programmer_temporarily] Запись в programmer_temporarily: {data}")
#         await self.repo.upsert_record("programmer_temporarily", data, pk_col="id")
#         return True

#     async def _process_programmer_const(self) -> bool:
#         logger.debug("[_process_programmer_const] Загрузка настроек постоянного режима из БД.")
#         record = await self.repo.get_record_by_id("programmer_const", 1)
#         if not record:
#             logger.warning("Запись с id=1 в таблице programmer_const не найдена.")
#             return False

#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         heating_data = {
#             "id": 1,
#             "temperature_start": record["const_min"],
#             "temperature_stop": record["const_max"],
#             "updated_at": now_str,
#         }
#         await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
#         logger.debug(f"[_process_programmer_const] Установлены пороги отопления в heating_table: {heating_data}")
#         return True

#     async def _process_programmer_temporarily(self) -> bool:
#         logger.debug("[_process_programmer_temporarily] Загрузка настроек временного режима из БД.")
#         record = await self.repo.get_record_by_id("programmer_temporarily", 1)
#         if not record or record.get("temporarily") is None:
#             logger.warning("Запись с id=1 в таблице programmer_temporarily не найдена.")
#             return False

#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
#         if hysteresis is None:
#             hysteresis = 1.0

#         temporarily = float(record["temporarily"])
#         temperature_start = round(temporarily - hysteresis / 2, 1)
#         temperature_stop = round(temporarily + hysteresis / 2, 1)

#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         heating_data = {
#             "id": 1,
#             "temperature_start": temperature_start,
#             "temperature_stop": temperature_stop,
#             "updated_at": now_str,
#         }
#         await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
#         logger.debug(f"[_process_programmer_temporarily] Установлены пороги отопления в heating_table: {heating_data}")
#         return True

#     async def _process_programmer_week(self) -> None:
#         logger.debug("[_process_programmer_week] Вызов логики недельного режима (заготовка).")
#         pass
