# app/services/programmer_service.py

from datetime import datetime, timedelta, time as dtime
import logging
from typing import List, Optional

from app.core.config import settings
from app.db.repository import BaseRepository
from app.services.heating_service import HeatingController

logger = logging.getLogger("climat_app.programmer_service")

# Порядок дней недели соответствует datetime.weekday(): Mo=0 ... Su=6
WEEK_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

# Поля системной строки id=1, которые нельзя задавать извне
SYSTEM_FIELDS = ("id", "now_id", "next_id", "week_time", "week_temperature", "updated_at")


class Programmer:
    """
    Класс программатора для управления режимами отопления.
    """

    def __init__(self, repo: BaseRepository, heating_controller: HeatingController) -> None:
        self.repo = repo
        self.heating_controller = heating_controller

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

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

    async def _get_mode_records(self, week_mode: str) -> List[dict]:
        """
        Получение всех записей расписания (id > 1) для указанного режима, отсортированных по week_time.
        """
        records = await self.repo.fetch_range(
            "programmer_week",
            filter_col="week_mode",
            start_val=week_mode,
            stop_val=week_mode,
        )
        mode_records = [r for r in records if r.get("id", 0) > 1]
        mode_records.sort(key=lambda x: str(x.get("week_time", "")))
        return mode_records

    @staticmethod
    def _week_day_indices(week_day: str) -> set:
        """
        Преобразует значение week_day в набор индексов дней недели (Mo=0 ... Su=6).
        Поддерживаются диапазоны ('Mo_Fr', 'Sa_Su', 'Mo_Su', переход через воскресенье, например 'Sa_Mo')
        и одиночные дни ('Mo'). Неизвестное значение трактуется как "каждый день".
        """
        value = str(week_day or "").strip()

        if "_" in value:
            start_s, end_s = value.split("_", 1)
            if start_s in WEEK_DAYS and end_s in WEEK_DAYS:
                i, j = WEEK_DAYS.index(start_s), WEEK_DAYS.index(end_s)
                if i <= j:
                    return set(range(i, j + 1))
                return set(range(i, 7)) | set(range(0, j + 1))
        elif value in WEEK_DAYS:
            return {WEEK_DAYS.index(value)}

        logger.warning(f"[_week_day_indices] Неизвестное значение week_day='{value}', используются все дни недели.")
        return set(range(7))

    def _select_week_records(self, mode_records: List[dict], now: datetime):
        """
        Выбор активной и следующей записи расписания с учетом дня недели и времени.
        Возвращает (now_rec, next_rec, next_dt) или None, если выбрать не из чего.
        next_dt - точные дата и время наступления следующей записи.
        """
        events = []  # (datetime события, id записи, запись)

        for rec in mode_records:
            try:
                parts = str(rec.get("week_time", "")).strip().split(":")
                rec_time = dtime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except (ValueError, IndexError):
                logger.warning(f"[_select_week_records] Некорректное week_time у записи id={rec.get('id')}, пропуск.")
                continue

            day_indices = self._week_day_indices(rec.get("week_day"))

            # Каждая запись повторяется минимум раз в неделю, поэтому окна
            # [-7; +7] дней достаточно, чтобы найти и прошлое, и будущее событие.
            for offset in range(-7, 8):
                day = now.date() + timedelta(days=offset)
                if day.weekday() in day_indices:
                    events.append((datetime.combine(day, rec_time), rec.get("id", 0), rec))

        if not events:
            return None

        events.sort(key=lambda e: (e[0], e[1]))

        past = [e for e in events if e[0] <= now]
        future = [e for e in events if e[0] > now]
        if not past or not future:
            return None

        now_rec = past[-1][2]
        next_dt, _, next_rec = future[0]
        return now_rec, next_rec, next_dt

    async def _set_week_system_row(self, week_mode: str, mode_records: List[dict]) -> bool:
        """
        Запись в системную строку id=1 активной/следующей записи для режима week_mode.
        """
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        selected = self._select_week_records(mode_records, now)
        if not selected:
            logger.warning(f"[_set_week_system_row] Не удалось выбрать активную запись для режима '{week_mode}'.")
            return False

        now_rec, next_rec, next_dt = selected

        update_data = {
            "id": 1,
            "now_id": now_rec.get("id"),
            "next_id": next_rec.get("id"),
            "week_mode": week_mode,
            "week_day": now_rec.get("week_day"),
            "week_time": next_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "week_temperature": now_rec.get("week_temperature"),
            "updated_at": now_str,
        }

        await self.repo.upsert_record("programmer_week", update_data, pk_col="id")
        logger.debug(f"[_set_week_system_row] Системная строка id=1 обновлена: {update_data}")
        return True

    async def _refresh_week_system_row(self) -> bool:
        """
        Пересчет системной строки id=1 для режима, который в ней сейчас записан.
        Вызывается после изменения расписания, чтобы now_id/next_id не указывали на удаленные строки.
        """
        sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
        week_mode = sys_rec.get("week_mode") if sys_rec else None
        if week_mode not in settings.days_week_mode:
            week_mode = "week"

        mode_records = await self._get_mode_records(week_mode)
        if not mode_records:
            logger.warning(f"[_refresh_week_system_row] Записи для режима '{week_mode}' отсутствуют.")
            return False

        return await self._set_week_system_row(week_mode, mode_records)

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

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
            is_expired = self._is_temporarily_expired(record, now)

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
            is_expired = self._is_temporarily_expired(record, now)

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

    @staticmethod
    def _is_temporarily_expired(record: Optional[dict], now: datetime) -> bool:
        """
        Проверка, истекло ли время временного режима. Пустое или нулевое время считается истекшим.
        """
        temp_time_str = record.get("temporarily_time") if record else None
        if not temp_time_str or str(temp_time_str).strip() in ("", "0", "00:00", "None"):
            return True
        try:
            target_dt = datetime.strptime(str(temp_time_str)[:19], "%Y-%m-%d %H:%M:%S")
            return now >= target_dt
        except Exception as e:
            logger.error(f"[_is_temporarily_expired] Ошибка парсинга temporarily_time ({temp_time_str}): {e}")
            return True

    async def _advance_programmer_week_cycle(self) -> None:
        """
        Переключение системной строки (id=1) таблицы programmer_week на следующую запись
        с учетом дня недели и времени.
        """
        sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
        if not sys_rec:
            logger.warning("[_advance_programmer_week_cycle] Системная запись с id=1 не найдена в programmer_week.")
            return

        week_mode = sys_rec.get("week_mode")
        if not week_mode:
            logger.warning("[_advance_programmer_week_cycle] Поле week_mode не задано в системной строке id=1.")
            return

        mode_records = await self._get_mode_records(week_mode)
        if not mode_records:
            logger.warning(f"[_advance_programmer_week_cycle] Записи для режима '{week_mode}' не найдены.")
            return

        await self._set_week_system_row(week_mode, mode_records)

    async def update_programmer_mode(
        self, flag_temporarily: bool = False, flag_const: bool = False, flag_week: bool = False
    ) -> str:
        """
        Определение и обновление нового режима работы программатора в БД.
        """
        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

        # Определяем базовый режим (по неделе или постоянно)
        if flag_week:
            is_week = True
        elif flag_const:
            is_week = False
        else:
            is_week = current_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK")

        # Определяем итоговый режим с учетом временного
        if flag_temporarily:
            new_mode = "PROGRAMMER_TEMPORARILY_WEEK" if is_week else "PROGRAMMER_TEMPORARILY_CONST"
        else:
            new_mode = "PROGRAMMER_WEEK" if is_week else "PROGRAMMER_CONST"

        logger.debug(f"[update_programmer_mode] Смена режима: {current_mode} -> {new_mode}")

        await self.repo.upsert_record(
            "settings_table",
            {"id": 1, "programmer_mode": new_mode},
            pk_col="id",
        )
        return new_mode

    async def update_week_mode(self, week_mode: str) -> bool:
        """
        Обновление системной строки (id=1) таблицы programmer_week при смене week_mode
        с учетом текущего дня недели и времени.
        """
        mode_records = await self._get_mode_records(week_mode)
        if not mode_records:
            logger.debug(
                f"[update_week_mode] Записи для режима '{week_mode}' отсутствуют в programmer_week. Строка id=1 не изменена."
            )
            return False

        return await self._set_week_system_row(week_mode, mode_records)

    # ------------------------------------------------------------------
    # Сохранение настроек
    # ------------------------------------------------------------------

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
        Если время не задано, временный режим действует до конца текущего цикла недельного режима.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        target_time_str = None
        if temporarily_time and str(temporarily_time).strip() not in ("", "0", "00:00", "None"):
            target_dt = self._calculate_target_datetime(now_str, str(temporarily_time))
            target_time_str = target_dt.strftime("%Y-%m-%d %H:%M:%S") if target_dt else None
        else:
            sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
            target_time_str = sys_rec.get("week_time") if sys_rec else None

        data = {
            "id": 1,
            "temporarily": temporarily,
            "temporarily_time": target_time_str,
            "updated_at": now_str,
        }
        logger.debug(f"[save_programmer_temporarily] Запись в programmer_temporarily: {data}")
        await self.repo.upsert_record("programmer_temporarily", data, pk_col="id")
        return True

    async def save_programmer_week(
        self,
        week_ids: List[int],
        week_days: List[str],
        week_times: List[str],
        week_temps: List[Optional[float]],
    ) -> bool:
        """
        Сохранение изменений строк таблицы programmer_week (для id > 1), удаление дубликатов
        и пересчет системной строки id=1.
        Дубликат - запись, у которой одновременно совпадают week_mode, week_day и week_time.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_modes = set()

        for w_id, w_day, w_time, w_temp in zip(week_ids, week_days, week_times, week_temps):
            if w_id <= 1 or w_temp is None:
                continue

            rec = await self.repo.get_record_by_id("programmer_week", w_id)
            if not rec:
                logger.warning(f"[save_programmer_week] Запись id={w_id} не найдена, пропуск.")
                continue
            if rec.get("week_mode"):
                updated_modes.add(rec["week_mode"])

            data = {
                "id": w_id,
                "week_day": w_day,
                "week_time": w_time,
                "week_temperature": w_temp,
                "updated_at": now_str,
            }
            logger.debug(f"[save_programmer_week] Обновление строки {w_id} в programmer_week: {data}")
            await self.repo.upsert_record("programmer_week", data, pk_col="id")

        # Удаление дубликатов в пределах каждого измененного week_mode
        for week_mode in updated_modes:
            mode_records = await self._get_mode_records(week_mode)

            groups = {}
            for r in mode_records:
                key = (str(r["week_mode"]).strip(), str(r["week_day"]).strip(), str(r["week_time"]).strip())
                groups.setdefault(key, []).append(r)

            for (g_mode, g_day, g_time), group in groups.items():
                if len(group) < 2:
                    continue
                group.sort(key=lambda x: x.get("id", 0))
                # Оставляем запись с меньшим id, остальные удаляем
                for dup_rec in group[1:]:
                    logger.info(
                        f"[save_programmer_week] Удаление дубликата записи id={dup_rec.get('id')} "
                        f"с week_mode='{g_mode}', week_day='{g_day}', week_time='{g_time}'"
                    )
                    await self.delete_programmer_week_row(dup_rec["id"])

        # Пересчет системной строки: её now_id/next_id могли измениться или указывать на удаленную строку
        if updated_modes:
            await self._refresh_week_system_row()

        return True

    async def add_programmer_week_row(self, new_record: dict) -> bool:
        """
        Добавление новой строки в расписание programmer_week (id > 1).
        Системные поля (id, now_id, next_id, week_time, week_temperature) задаются не извне.
        """
        if not new_record.get("id"):
            max_rec = await self.repo.get_latest_record("programmer_week", order_by_col="id")
            new_id = (max_rec.get("id", 1) if max_rec else 1) + 1
        else:
            new_id = new_record["id"]

        record = {k: v for k, v in new_record.items() if k not in ("now_id", "next_id")}
        record["id"] = new_id

        logger.debug(f"[add_programmer_week_row] Вставка записи в programmer_week: {record}")
        await self.repo.upsert_record("programmer_week", record, pk_col="id")
        await self._refresh_week_system_row()
        return True

    async def delete_programmer_week_row(self, row_id: int) -> bool:
        """
        Удаление строки из расписания programmer_week по row_id (системная строка id=1 не удаляется).
        """
        if row_id <= 1:
            logger.warning(f"[delete_programmer_week_row] Попытка удалить системную строку id={row_id} заблокирована.")
            return False

        rec = await self.repo.get_record_by_id("programmer_week", row_id)
        if not rec:
            logger.warning(f"[delete_programmer_week_row] Запись с id={row_id} не найдена в programmer_week.")
            return False

        logger.debug(f"[delete_programmer_week_row] Удаление строки id={row_id} из programmer_week")
        await self.repo.delete_record_by_id("programmer_week", row_id, pk_col="id")
        await self._refresh_week_system_row()
        return True

    # ------------------------------------------------------------------
    # Применение уставок к heating_table
    # ------------------------------------------------------------------

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

        return await self._apply_heating_thresholds(float(record["temporarily"]), "_process_programmer_temporarily")

    async def _process_programmer_week(self) -> bool:
        logger.debug("[_process_programmer_week] Загрузка настроек недельного режима из системной строки id=1 таблицы programmer_week.")
        record = await self.repo.get_record_by_id("programmer_week", 1)
        if not record or record.get("week_temperature") is None:
            logger.warning("Запись с id=1 в таблице programmer_week не найдена или week_temperature отсутствует.")
            return False

        return await self._apply_heating_thresholds(float(record["week_temperature"]), "_process_programmer_week")

    async def _apply_heating_thresholds(self, target_temp: float, caller: str) -> bool:
        """
        Расчет порогов включения/выключения отопления от целевой температуры и запись в heating_table.
        """
        sys_settings = await self.repo.get_settings_db(log_to_api=False)
        hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
        if hysteresis is None:
            hysteresis = 1.0

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        heating_data = {
            "id": 1,
            "temperature_start": round(target_temp - hysteresis / 2, 1),
            "temperature_stop": round(target_temp + hysteresis / 2, 1),
            "updated_at": now_str,
        }
        await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
        logger.debug(f"[{caller}] Установлены пороги отопления в heating_table: {heating_data}")
        return True





# # app/services/programmer_service.py

# from datetime import datetime, timedelta, time as dtime
# import logging
# from typing import List, Optional

# from app.core.config import settings
# from app.db.repository import BaseRepository
# from app.services.heating_service import HeatingController

# logger = logging.getLogger("climat_app.programmer_service")

# # Порядок дней недели соответствует datetime.weekday(): Mo=0 ... Su=6
# WEEK_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

# # Поля системной строки id=1, которые нельзя задавать извне
# SYSTEM_FIELDS = ("id", "now_id", "next_id", "week_time", "week_temperature", "updated_at")


# class Programmer:
#     """
#     Класс программатора для управления режимами отопления.
#     """

#     def __init__(self, repo: BaseRepository, heating_controller: HeatingController) -> None:
#         self.repo = repo
#         self.heating_controller = heating_controller

#     # ------------------------------------------------------------------
#     # Вспомогательные методы
#     # ------------------------------------------------------------------

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

#     async def _get_mode_records(self, week_mode: str) -> List[dict]:
#         """
#         Получение всех записей расписания (id > 1) для указанного режима, отсортированных по week_time.
#         """
#         records = await self.repo.fetch_range(
#             "programmer_week",
#             filter_col="week_mode",
#             start_val=week_mode,
#             stop_val=week_mode,
#         )
#         mode_records = [r for r in records if r.get("id", 0) > 1]
#         mode_records.sort(key=lambda x: str(x.get("week_time", "")))
#         return mode_records

#     @staticmethod
#     def _week_day_indices(week_day: str) -> set:
#         """
#         Преобразует значение week_day в набор индексов дней недели (Mo=0 ... Su=6).
#         Поддерживаются диапазоны ('Mo_Fr', 'Sa_Su', 'Mo_Su', переход через воскресенье, например 'Sa_Mo')
#         и одиночные дни ('Mo'). Неизвестное значение трактуется как "каждый день".
#         """
#         value = str(week_day or "").strip()

#         if "_" in value:
#             start_s, end_s = value.split("_", 1)
#             if start_s in WEEK_DAYS and end_s in WEEK_DAYS:
#                 i, j = WEEK_DAYS.index(start_s), WEEK_DAYS.index(end_s)
#                 if i <= j:
#                     return set(range(i, j + 1))
#                 return set(range(i, 7)) | set(range(0, j + 1))
#         elif value in WEEK_DAYS:
#             return {WEEK_DAYS.index(value)}

#         logger.warning(f"[_week_day_indices] Неизвестное значение week_day='{value}', используются все дни недели.")
#         return set(range(7))

#     def _select_week_records(self, mode_records: List[dict], now: datetime):
#         """
#         Выбор активной и следующей записи расписания с учетом дня недели и времени.
#         Возвращает (now_rec, next_rec, next_dt) или None, если выбрать не из чего.
#         next_dt - точные дата и время наступления следующей записи.
#         """
#         events = []  # (datetime события, id записи, запись)

#         for rec in mode_records:
#             try:
#                 parts = str(rec.get("week_time", "")).strip().split(":")
#                 rec_time = dtime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
#             except (ValueError, IndexError):
#                 logger.warning(f"[_select_week_records] Некорректное week_time у записи id={rec.get('id')}, пропуск.")
#                 continue

#             day_indices = self._week_day_indices(rec.get("week_day"))

#             # Каждая запись повторяется минимум раз в неделю, поэтому окна
#             # [-7; +7] дней достаточно, чтобы найти и прошлое, и будущее событие.
#             for offset in range(-7, 8):
#                 day = now.date() + timedelta(days=offset)
#                 if day.weekday() in day_indices:
#                     events.append((datetime.combine(day, rec_time), rec.get("id", 0), rec))

#         if not events:
#             return None

#         events.sort(key=lambda e: (e[0], e[1]))

#         past = [e for e in events if e[0] <= now]
#         future = [e for e in events if e[0] > now]
#         if not past or not future:
#             return None

#         now_rec = past[-1][2]
#         next_dt, _, next_rec = future[0]
#         return now_rec, next_rec, next_dt

#     async def _set_week_system_row(self, week_mode: str, mode_records: List[dict]) -> bool:
#         """
#         Запись в системную строку id=1 активной/следующей записи для режима week_mode.
#         """
#         now = datetime.now()
#         now_str = now.strftime("%Y-%m-%d %H:%M:%S")

#         selected = self._select_week_records(mode_records, now)
#         if not selected:
#             logger.warning(f"[_set_week_system_row] Не удалось выбрать активную запись для режима '{week_mode}'.")
#             return False

#         now_rec, next_rec, next_dt = selected

#         update_data = {
#             "id": 1,
#             "now_id": now_rec.get("id"),
#             "next_id": next_rec.get("id"),
#             "week_mode": week_mode,
#             "week_day": now_rec.get("week_day"),
#             "week_time": next_dt.strftime("%Y-%m-%d %H:%M:%S"),
#             "week_temperature": now_rec.get("week_temperature"),
#             "updated_at": now_str,
#         }

#         await self.repo.upsert_record("programmer_week", update_data, pk_col="id")
#         logger.debug(f"[_set_week_system_row] Системная строка id=1 обновлена: {update_data}")
#         return True

#     async def _refresh_week_system_row(self) -> bool:
#         """
#         Пересчет системной строки id=1 для режима, который в ней сейчас записан.
#         Вызывается после изменения расписания, чтобы now_id/next_id не указывали на удаленные строки.
#         """
#         sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
#         week_mode = sys_rec.get("week_mode") if sys_rec else None
#         if week_mode not in settings.days_week_mode:
#             week_mode = "week"

#         mode_records = await self._get_mode_records(week_mode)
#         if not mode_records:
#             logger.warning(f"[_refresh_week_system_row] Записи для режима '{week_mode}' отсутствуют.")
#             return False

#         return await self._set_week_system_row(week_mode, mode_records)

#     # ------------------------------------------------------------------
#     # Основная логика
#     # ------------------------------------------------------------------

#     async def evaluate(self) -> None:
#         """
#         Основной метод проверки programmer_mode, оценки времени действия уставок и выбора режима.
#         """
#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         programmer_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")
#         logger.debug(f"[evaluate] Старт проверки. Текущий режим программатора: {programmer_mode}")

#         now = datetime.now()

#         if programmer_mode == "PROGRAMMER_CONST":
#             logger.debug("[evaluate] Выполнение логики ПОСТОЯННОГО режима.")
#             await self._process_programmer_const()

#         elif programmer_mode == "PROGRAMMER_WEEK":
#             logger.debug("[evaluate] Выполнение логики НЕДЕЛЬНОГО режима.")
#             record = await self.repo.get_record_by_id("programmer_week", 1)
#             if not record or not record.get("week_time"):
#                 logger.warning("[evaluate] Запись с id=1 в programmer_week не найдена или отсутствует week_time.")
#                 return

#             try:
#                 target_dt = datetime.strptime(str(record["week_time"])[:19], "%Y-%m-%d %H:%M:%S")
#             except Exception as e:
#                 logger.warning(f"[evaluate] Ошибка парсинга week_time ({record.get('week_time')}): {e}")
#                 return

#             if now >= target_dt:
#                 logger.info(f"[evaluate] Время текущего цикла недельного режима истекло ({now} >= {target_dt}). Переход к следующему циклу.")
#                 await self._advance_programmer_week_cycle()

#             await self._process_programmer_week()

#         elif programmer_mode == "PROGRAMMER_TEMPORARILY_CONST":
#             record = await self.repo.get_record_by_id("programmer_temporarily", 1)
#             is_expired = self._is_temporarily_expired(record, now)

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
#             record = await self.repo.get_record_by_id("programmer_temporarily", 1)
#             is_expired = self._is_temporarily_expired(record, now)

#             if is_expired:
#                 logger.info("[evaluate] Время действия временного режима истекло. Возврат в PROGRAMMER_WEEK.")
#                 await self.repo.upsert_record(
#                     "settings_table",
#                     {"id": 1, "programmer_mode": "PROGRAMMER_WEEK"},
#                     pk_col="id",
#                 )
#                 record_week = await self.repo.get_record_by_id("programmer_week", 1)
#                 if not record_week or not record_week.get("week_time"):
#                     logger.warning("[evaluate] Запись с id=1 в programmer_week не найдена при переходе из TEMPORARILY_WEEK.")
#                     return
#                 try:
#                     target_dt_week = datetime.strptime(str(record_week["week_time"])[:19], "%Y-%m-%d %H:%M:%S")
#                     if now >= target_dt_week:
#                         await self._advance_programmer_week_cycle()
#                 except Exception as e:
#                     logger.warning(f"[evaluate] Ошибка парсинга week_time при переходе из TEMPORARILY_WEEK: {e}")
#                     return

#                 await self._process_programmer_week()
#             else:
#                 logger.debug("[evaluate] Режим PROGRAMMER_TEMPORARILY_WEEK активен.")
#                 await self._process_programmer_temporarily()

#     @staticmethod
#     def _is_temporarily_expired(record: Optional[dict], now: datetime) -> bool:
#         """
#         Проверка, истекло ли время временного режима. Пустое или нулевое время считается истекшим.
#         """
#         temp_time_str = record.get("temporarily_time") if record else None
#         if not temp_time_str or str(temp_time_str).strip() in ("", "0", "00:00", "None"):
#             return True
#         try:
#             target_dt = datetime.strptime(str(temp_time_str)[:19], "%Y-%m-%d %H:%M:%S")
#             return now >= target_dt
#         except Exception as e:
#             logger.error(f"[_is_temporarily_expired] Ошибка парсинга temporarily_time ({temp_time_str}): {e}")
#             return True

#     async def _advance_programmer_week_cycle(self) -> None:
#         """
#         Переключение системной строки (id=1) таблицы programmer_week на следующую запись
#         с учетом дня недели и времени.
#         """
#         sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
#         if not sys_rec:
#             logger.warning("[_advance_programmer_week_cycle] Системная запись с id=1 не найдена в programmer_week.")
#             return

#         week_mode = sys_rec.get("week_mode")
#         if not week_mode:
#             logger.warning("[_advance_programmer_week_cycle] Поле week_mode не задано в системной строке id=1.")
#             return

#         mode_records = await self._get_mode_records(week_mode)
#         if not mode_records:
#             logger.warning(f"[_advance_programmer_week_cycle] Записи для режима '{week_mode}' не найдены.")
#             return

#         await self._set_week_system_row(week_mode, mode_records)

#     async def update_programmer_mode(
#         self, flag_temporarily: bool = False, flag_const: bool = False, flag_week: bool = False
#     ) -> str:
#         """
#         Определение и обновление нового режима работы программатора в БД.
#         """
#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         current_mode = getattr(sys_settings, "programmer_mode", "PROGRAMMER_CONST")

#         # Определяем базовый режим (по неделе или постоянно)
#         if flag_week:
#             is_week = True
#         elif flag_const:
#             is_week = False
#         else:
#             is_week = current_mode in ("PROGRAMMER_WEEK", "PROGRAMMER_TEMPORARILY_WEEK")

#         # Определяем итоговый режим с учетом временного
#         if flag_temporarily:
#             new_mode = "PROGRAMMER_TEMPORARILY_WEEK" if is_week else "PROGRAMMER_TEMPORARILY_CONST"
#         else:
#             new_mode = "PROGRAMMER_WEEK" if is_week else "PROGRAMMER_CONST"

#         logger.debug(f"[update_programmer_mode] Смена режима: {current_mode} -> {new_mode}")

#         await self.repo.upsert_record(
#             "settings_table",
#             {"id": 1, "programmer_mode": new_mode},
#             pk_col="id",
#         )
#         return new_mode

#     async def update_week_mode(self, week_mode: str) -> bool:
#         """
#         Обновление системной строки (id=1) таблицы programmer_week при смене week_mode
#         с учетом текущего дня недели и времени.
#         """
#         mode_records = await self._get_mode_records(week_mode)
#         if not mode_records:
#             logger.debug(
#                 f"[update_week_mode] Записи для режима '{week_mode}' отсутствуют в programmer_week. Строка id=1 не изменена."
#             )
#             return False

#         return await self._set_week_system_row(week_mode, mode_records)

#     # ------------------------------------------------------------------
#     # Сохранение настроек
#     # ------------------------------------------------------------------

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
#         Сохранение настроек временного режима (строка id=1).
#         Если время не задано, временный режим действует до конца текущего цикла недельного режима.
#         """
#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#         target_time_str = None
#         if temporarily_time and str(temporarily_time).strip() not in ("", "0", "00:00", "None"):
#             target_dt = self._calculate_target_datetime(now_str, str(temporarily_time))
#             target_time_str = target_dt.strftime("%Y-%m-%d %H:%M:%S") if target_dt else None
#         else:
#             sys_rec = await self.repo.get_record_by_id("programmer_week", 1)
#             target_time_str = sys_rec.get("week_time") if sys_rec else None

#         data = {
#             "id": 1,
#             "temporarily": temporarily,
#             "temporarily_time": target_time_str,
#             "updated_at": now_str,
#         }
#         logger.debug(f"[save_programmer_temporarily] Запись в programmer_temporarily: {data}")
#         await self.repo.upsert_record("programmer_temporarily", data, pk_col="id")
#         return True

#     async def save_programmer_week(
#         self,
#         week_ids: List[int],
#         week_days: List[str],
#         week_times: List[str],
#         week_temps: List[Optional[float]],
#     ) -> bool:
#         """
#         Сохранение изменений строк таблицы programmer_week (для id > 1), удаление дубликатов
#         и пересчет системной строки id=1.
#         Дубликат - запись, у которой одновременно совпадают week_mode, week_day и week_time.
#         """
#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         updated_modes = set()

#         for w_id, w_day, w_time, w_temp in zip(week_ids, week_days, week_times, week_temps):
#             if w_id <= 1 or w_temp is None:
#                 continue

#             rec = await self.repo.get_record_by_id("programmer_week", w_id)
#             if not rec:
#                 logger.warning(f"[save_programmer_week] Запись id={w_id} не найдена, пропуск.")
#                 continue
#             if rec.get("week_mode"):
#                 updated_modes.add(rec["week_mode"])

#             data = {
#                 "id": w_id,
#                 "week_day": w_day,
#                 "week_time": w_time,
#                 "week_temperature": w_temp,
#                 "updated_at": now_str,
#             }
#             logger.debug(f"[save_programmer_week] Обновление строки {w_id} в programmer_week: {data}")
#             await self.repo.upsert_record("programmer_week", data, pk_col="id")

#         # Удаление дубликатов в пределах каждого измененного week_mode
#         for week_mode in updated_modes:
#             mode_records = await self._get_mode_records(week_mode)

#             groups = {}
#             for r in mode_records:
#                 key = (str(r["week_mode"]).strip(), str(r["week_day"]).strip(), str(r["week_time"]).strip())
#                 groups.setdefault(key, []).append(r)

#             for (g_mode, g_day, g_time), group in groups.items():
#                 if len(group) < 2:
#                     continue
#                 group.sort(key=lambda x: x.get("id", 0))
#                 # Оставляем запись с меньшим id, остальные удаляем
#                 for dup_rec in group[1:]:
#                     logger.info(
#                         f"[save_programmer_week] Удаление дубликата записи id={dup_rec.get('id')} "
#                         f"с week_mode='{g_mode}', week_day='{g_day}', week_time='{g_time}'"
#                     )
#                     await self.delete_programmer_week_row(dup_rec["id"])

#         # Пересчет системной строки: её now_id/next_id могли измениться или указывать на удаленную строку
#         if updated_modes:
#             await self._refresh_week_system_row()

#         return True

#     async def add_programmer_week_row(self, new_record: dict) -> bool:
#         """
#         Добавление новой строки в расписание programmer_week (id > 1).
#         Системные поля (id, now_id, next_id, week_time, week_temperature) задаются не извне.
#         """
#         if not new_record.get("id"):
#             max_rec = await self.repo.get_latest_record("programmer_week", order_by_col="id")
#             new_id = (max_rec.get("id", 1) if max_rec else 1) + 1
#         else:
#             new_id = new_record["id"]

#         record = {k: v for k, v in new_record.items() if k not in ("now_id", "next_id")}
#         record["id"] = new_id

#         logger.debug(f"[add_programmer_week_row] Вставка записи в programmer_week: {record}")
#         await self.repo.upsert_record("programmer_week", record, pk_col="id")
#         await self._refresh_week_system_row()
#         return True

#     async def delete_programmer_week_row(self, row_id: int) -> bool:
#         """
#         Удаление строки из расписания programmer_week по row_id (системная строка id=1 не удаляется).
#         """
#         if row_id <= 1:
#             logger.warning(f"[delete_programmer_week_row] Попытка удалить системную строку id={row_id} заблокирована.")
#             return False

#         rec = await self.repo.get_record_by_id("programmer_week", row_id)
#         if not rec:
#             logger.warning(f"[delete_programmer_week_row] Запись с id={row_id} не найдена в programmer_week.")
#             return False

#         logger.debug(f"[delete_programmer_week_row] Удаление строки id={row_id} из programmer_week")
#         await self.repo.delete_record_by_id("programmer_week", row_id, pk_col="id")
#         await self._refresh_week_system_row()
#         return True

#     # ------------------------------------------------------------------
#     # Применение уставок к heating_table
#     # ------------------------------------------------------------------

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

#         return await self._apply_heating_thresholds(float(record["temporarily"]), "_process_programmer_temporarily")

#     async def _process_programmer_week(self) -> bool:
#         logger.debug("[_process_programmer_week] Загрузка настроек недельного режима из системной строки id=1 таблицы programmer_week.")
#         record = await self.repo.get_record_by_id("programmer_week", 1)
#         if not record or record.get("week_temperature") is None:
#             logger.warning("Запись с id=1 в таблице programmer_week не найдена или week_temperature отсутствует.")
#             return False

#         return await self._apply_heating_thresholds(float(record["week_temperature"]), "_process_programmer_week")

#     async def _apply_heating_thresholds(self, target_temp: float, caller: str) -> bool:
#         """
#         Расчет порогов включения/выключения отопления от целевой температуры и запись в heating_table.
#         """
#         sys_settings = await self.repo.get_settings_db(log_to_api=False)
#         hysteresis = getattr(sys_settings, "hysteresis_temperature", 1.0)
#         if hysteresis is None:
#             hysteresis = 1.0

#         now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         heating_data = {
#             "id": 1,
#             "temperature_start": round(target_temp - hysteresis / 2, 1),
#             "temperature_stop": round(target_temp + hysteresis / 2, 1),
#             "updated_at": now_str,
#         }
#         await self.repo.upsert_record("heating_table", heating_data, pk_col="id")
#         logger.debug(f"[{caller}] Установлены пороги отопления в heating_table: {heating_data}")
#         return True