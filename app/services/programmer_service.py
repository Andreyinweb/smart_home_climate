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

        elif programmer_mode == "PROGRAMMER_TEMPORARILY_CONST":
            record = await self.repo.get_record_by_id("programmer_temporarily", 1)
            is_expired = False

            if record and record.get("updated_at") and record.get("temporarily_time"):
                target_dt = self._calculate_target_datetime(
                    str(record["updated_at"]),
                    str(record["temporarily_time"])
                )
                if target_dt and now >= target_dt:
                    is_expired = True
                    logger.info(
                        f"[evaluate] Время действия временного режима истекло ({now} >= {target_dt}). "
                        f"Автоматический возврат в PROGRAMMER_CONST."
                    )

            if is_expired:
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
            temp_time = record.get("temporarily_time") if record else None

            if record and record.get("updated_at") and temp_time and str(temp_time).strip() not in ("", "00:00", "0"):
                target_dt = self._calculate_target_datetime(
                    str(record["updated_at"]),
                    str(temp_time)
                )
                if target_dt and now >= target_dt:
                    is_expired = True
                    logger.info(
                        f"[evaluate] Время действия временного режима истекло ({now} >= {target_dt}). "
                        f"Автоматический возврат в PROGRAMMER_WEEK."
                    )

            if is_expired:
                await self.repo.upsert_record(
                    "settings_table",
                    {"id": 1, "programmer_mode": "PROGRAMMER_WEEK"},
                    pk_col="id",
                )
                await self._process_programmer_week()
            else:
                logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_WEEK активен.")
                await self._process_programmer_temporarily()

        elif programmer_mode == "PROGRAMMER_WEEK":
            logger.debug("[evaluate] Выполнение логики НЕДЕЛЬНОГО режима.")
            await self._process_programmer_week()

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
        Сохранение настроек временного режима (строка id=1).
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "id": 1,
            "temporarily": temporarily,
            "temporarily_time": temporarily_time,
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

    async def _process_programmer_week(self) -> None:
        logger.debug("[_process_programmer_week] Вызов логики недельного режима (заготовка).")
        pass