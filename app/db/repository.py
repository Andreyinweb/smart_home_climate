# app/db/repository.py

"""
Модуль репозитория баз данных приложения климат-контроля.

Предоставляет асинхронные и синхронные методы для взаимодействия с СУБД SQLite,
включая атомарные CRUD-операции, агрегацию климатических показателей,
управление системными настройками и учет показаний газа.

Публичный интерфейс репозитория (BaseRepository):
- get_settings(log_to_api: bool = False) -> SystemSettings: Получение системных настроек из базы данных.
- get_settings_db(log_to_api: bool = False) -> SystemSettings: Алиас для получения системных настроек из базы данных.
- update_settings(update_dto: SystemSettingsUpdate, settings_id: int = 1, log_to_api: bool = False) -> Optional[SystemSettings]: Обновление системных настроек приложения.
- upsert_record(table_name: str, data: Dict[str, Any], pk_col: str = "id", log_to_api: bool = False) -> bool: Вставка или обновление записи в указанной таблице.
- get_record_by_id(table_name: str, record_id: Any, pk_col: str = "id", log_to_api: bool = False) -> Optional[Dict[str, Any]]: Извлечение записи из таблицы по первичному ключу.
- get_latest_record(table_name: str, order_by_col: str = "id", log_to_api: bool = False) -> Optional[Dict[str, Any]]: Извлечение последней записи из таблицы.
- fetch_range(table_name: str, filter_col: str = "id", start_val: Any = None, stop_val: Any = None, limit: Optional[int] = None, order_asc: bool = True, log_to_api: bool = False) -> List[Dict[str, Any]]: Выборка записей из таблицы по диапазону значений.
- get_aggregate(table_name: str, column_name: str, function: str = "AVG", interval_type: Optional[str] = None, target_time: Optional[str] = None, log_to_api: bool = False) -> Optional[float]: Расчет агрегатной функции (AVG, SUM, MIN, MAX) по колонке.
- delete_record_by_id(table_name: str, record_id: Any, pk_col: str = "id", log_to_api: bool = False) -> bool: Удаление записи из таблицы по первичному ключу.
- get_sensor_graph_points(hours: int = 24, log_to_api: bool = False) -> List[GraphSensorPoint]: Получение данных датчиков и статусов оборудования для построения графиков.
- get_calibration_data(max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]: Получение данных для калибровки датчиков температуры и влажности.
- fetch_by_date(table_name: str, target_date: str, interval_type: str = "month", order_asc: bool = True, log_to_api: bool = False) -> List[Dict[str, Any]]: Выборка записей из таблицы за указанную дату или интервал.
- get_latest_gas_record() -> Optional[Dict[str, Any]]: Получение последней записи из таблицы учета газа.
- save_gas_record(timestamp: Any, gas_meter: float, gas_difference: Optional[float] = None, price_gas: Optional[float] = None, cost_of_gas: Optional[float] = None, **extra_fields) -> Dict[str, Any]: Сохранение новой записи показаний счетчика газа.
- get_gas_records(start_date: Optional[Any] = None, end_date: Optional[Any] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]: Выборка записей учета газа с фильтрацией по датам и пагинацией.
"""

import asyncio
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from app.db.connection import get_db_connection
from app.core.config import settings as config_settings
from app.schemas.settings_schema import SystemSettings, SystemSettingsUpdate
from app.schemas.climate_schema import GraphSensorPoint

work_log = logging.getLogger("climat_app.repository")
api_log = logging.getLogger("api_app.repository")


class BaseRepository:
    """
    Универсальный атомарный репозиторий SQLite.

    Отвечает за абстракцию доступа к данным SQLite, предоставляя низкоуровневые
    синхронные методы работы с SQL и асинхронные интерфейсные обертки для сервисного слоя.
    """

    @staticmethod
    def _upsert_sync(
        table_name: str,
        data: Dict[str, Any],
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> bool:
        """
        Синхронно выполняет вставку или обновление (UPSERT) записи в таблице.

        :param table_name: Название целевой таблицы в базе данных.
        :param data: Словарь данных для записи (ключ — колонка, значение — значение).
        :param pk_col: Колонка первичного ключа для определения конфликтов.
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: True, если SQL-запрос успешно выполнен, False при пустых данных.
        """
        logger = api_log if log_to_api else work_log
        if not data:
            return False

        cols = list(data.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        cols_str = ", ".join(cols)

        update_cols = [c for c in cols if c != pk_col]
        if update_cols:
            update_str = ", ".join([f"{c} = excluded.{c}" for c in update_cols])
            sql = (
                f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders}) "
                f"ON CONFLICT({pk_col}) DO UPDATE SET {update_str};"
            )
        else:
            sql = (
                f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders}) "
                f"ON CONFLICT({pk_col}) DO NOTHING;"
            )

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, data)
            logger.debug(f"UPSERT в '{table_name}' выполнен.")
            return True

    @staticmethod
    def _get_by_id_sync(
        table_name: str,
        record_id: Any,
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Синхронно извлекает одну запись из таблицы по ее первичному ключу.

        :param table_name: Название таблицы в базе данных.
        :param record_id: Значение первичного ключа искомой записи.
        :param pk_col: Название колонки первичного ключа.
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: Словарь с полями найденной записи или None.
        """
        sql = f"SELECT * FROM {table_name} WHERE {pk_col} = ?;"
        with get_db_connection() as conn:
            row = conn.cursor().execute(sql, (record_id,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _get_latest_sync(
        table_name: str,
        order_by_col: str = "id",
        log_to_api: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Синхронно извлекает последнюю запись таблицы при сортировке DESC.

        :param table_name: Название таблицы в базе данных.
        :param order_by_col: Имя колонки для сортировки DESC.
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: Словарь с полями последней записи или None.
        """
        sql = f"SELECT * FROM {table_name} ORDER BY {order_by_col} DESC LIMIT 1;"
        with get_db_connection() as conn:
            row = conn.cursor().execute(sql).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _fetch_range_sync(
        table_name: str,
        filter_col: str = "id",
        start_val: Any = None,
        stop_val: Any = None,
        limit: Optional[int] = None,
        order_asc: bool = True,
        log_to_api: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Синхронно выбирает список записей с фильтрацией по диапазону значений.

        :param table_name: Название таблицы в базе данных.
        :param filter_col: Колонка для фильтрации и сортировки.
        :param start_val: Нижняя граница диапазона (включительно).
        :param stop_val: Верхняя граница диапазона (включительно).
        :param limit: Ограничение количества возвращаемых строк.
        :param order_asc: Флаг направления сортировки (True — ASC, False — DESC).
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: Список словарей с записями.
        """
        query = f"SELECT * FROM {table_name}"
        params: List[Any] = []
        where: List[str] = []

        if start_val is not None and stop_val is not None:
            if start_val == stop_val:
                where.append(f"{filter_col} = ?")
                params.append(start_val)
            else:
                where.append(f"{filter_col} >= ? AND {filter_col} <= ?")
                params.extend([start_val, stop_val])
        elif start_val is not None:
            where.append(f"{filter_col} >= ?")
            params.append(start_val)
        elif stop_val is not None:
            where.append(f"{filter_col} <= ?")
            params.append(stop_val)

        if where:
            query += " WHERE " + " AND ".join(where)

        query += f" ORDER BY {filter_col} {'ASC' if order_asc else 'DESC'}"
        if limit:
            query += f" LIMIT {limit}"

        with get_db_connection() as conn:
            return [dict(r) for r in conn.cursor().execute(query, tuple(params)).fetchall()]

    @staticmethod
    def _get_aggregate_sync(
        table_name: str,
        column_name: str,
        function: str = "AVG",
        interval_type: Optional[str] = None,
        target_time: Optional[str] = None,
        log_to_api: bool = False
    ) -> Optional[float]:
        """
        Синхронно рассчитывает агрегатное значение SQL по колонке таблицы.

        :param table_name: Название таблицы в базе данных.
        :param column_name: Колонка для вычисления агрегата.
        :param function: Имя агрегатной функции SQL (AVG, SUM, MIN, MAX).
        :param interval_type: Тип интервала времени ('hour', 'day', 'month').
        :param target_time: Целевое время для фильтрации записи по префиксу timestamp.
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: Округленное до 2 знаков значение агрегата или None.
        """
        logger = api_log if log_to_api else work_log
        params: List[Any] = []
        func = function.upper()

        if target_time and interval_type:
            clean_time = str(target_time).strip()
            norm = str(interval_type).strip().lower()
            if norm in ("hour", "час"):
                query = f"SELECT {func}({column_name}) AS res FROM {table_name} WHERE strftime('%Y-%m-%d %H', timestamp) = ?;"
                params.append(clean_time[:13])
            elif norm in ("day", "день"):
                query = f"SELECT {func}({column_name}) AS res FROM {table_name} WHERE strftime('%Y-%m-%d', timestamp) = ?;"
                params.append(clean_time[:10])
            elif norm in ("month", "месяц"):
                query = f"SELECT {func}({column_name}) AS res FROM {table_name} WHERE strftime('%Y-%m', timestamp) = ?;"
                params.append(clean_time[:7])
            else:
                return None
        elif interval_type:
            interval_map = {
                "hour": "-1 hour",
                "час": "-1 hour",
                "day": "-1 day",
                "день": "-1 day",
                "month": "-1 month",
                "месяц": "-1 month",
            }
            modifier = interval_map.get(str(interval_type).strip().lower(), "-1 hour")
            query = f"SELECT {func}({column_name}) AS res FROM {table_name} WHERE timestamp >= datetime('now', ?);"
            params.append(modifier)
        else:
            query = f"SELECT {func}({column_name}) AS res FROM {table_name};"

        with get_db_connection() as conn:
            row = conn.cursor().execute(query, tuple(params)).fetchone()
            if row and row["res"] is not None:
                val = round(float(row["res"]), 2)
                logger.debug(f"Агрегат {func}({column_name}) = {val} в '{table_name}'.")
                return val
            return None

    @staticmethod
    def _delete_by_id_sync(
        table_name: str,
        record_id: Any,
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> bool:
        """
        Синхронно удаляет запись из таблицы по ее первичному ключу.

        :param table_name: Название таблицы в базе данных.
        :param record_id: Значение первичного ключа удаляемой записи.
        :param pk_col: Колонка первичного ключа.
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: True, если удаление затронуло строки, иначе False.
        """
        sql = f"DELETE FROM {table_name} WHERE {pk_col} = ?;"
        with get_db_connection() as conn:
            return conn.cursor().execute(sql, (record_id,)).rowcount > 0

    @staticmethod
    def _fetch_by_date_sync(
        table_name: str,
        target_date: str,
        interval_type: str = "month",
        order_asc: bool = True,
        log_to_api: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Синхронно выбирает записи из таблицы по префиксу даты timestamp.

        :param table_name: Название таблицы в базе данных.
        :param target_date: Строка целевой даты.
        :param interval_type: Тип интервала ('month', 'day', 'hour').
        :param order_asc: Направление сортировки по id (True — ASC, False — DESC).
        :param log_to_api: Флаг использования api_log (True) или work_log (False).
        :return: Список словарей с найденными записями.
        """
        logger = api_log if log_to_api else work_log
        length_map = {"month": 7, "day": 10, "hour": 13}
        str_len = length_map.get(interval_type, 7)
        prefix = target_date[:str_len]

        order = "ASC" if order_asc else "DESC"
        sql = f"SELECT * FROM {table_name} WHERE substr(timestamp, 1, ?) = ? ORDER BY id {order};"

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (str_len, prefix))
                rows = cursor.fetchall()
                results = [dict(row) for row in rows]
                logger.debug(f"[fetch_by_date] Найдено {len(results)} записей в '{table_name}' за '{prefix}' ({interval_type}).")
                return results
        except Exception as e:
            logger.error(f"[fetch_by_date] Ошибка выполнения запроса к '{table_name}': {e}")
            return []

    # --- Публичные асинхронные методы класса BaseRepository ---

    async def get_settings(self, log_to_api: bool = False) -> SystemSettings:
        """
        Асинхронно получает системные настройки из базы данных.

        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Объект Pydantic-схемы SystemSettings.
        """
        return await get_settings(log_to_api=log_to_api)

    async def get_settings_db(self, log_to_api: bool = False) -> SystemSettings:
        """
        Асинхронно получает системные настройки из базы данных (алиас get_settings).

        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Объект Pydantic-схемы SystemSettings.
        """
        return await get_settings_db(log_to_api=log_to_api)

    async def update_settings(
        self,
        update_dto: SystemSettingsUpdate,
        settings_id: int = 1,
        log_to_api: bool = False
    ) -> Optional[SystemSettings]:
        """
        Асинхронно обновляет системные настройки в базе данных.

        :param update_dto: Объект с изменениями настроек.
        :param settings_id: Идентификатор записи настроек (по умолчанию 1).
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Обновленный объект SystemSettings или None.
        """
        return await update_settings(update_dto=update_dto, settings_id=settings_id, log_to_api=log_to_api)

    async def upsert_record(
        self,
        table_name: str,
        data: Dict[str, Any],
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> bool:
        """
        Асинхронно выполняет вставку или обновление (UPSERT) записи.

        :param table_name: Название таблицы в базе данных.
        :param data: Словарь данных записи.
        :param pk_col: Первичный ключ.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: True при успешном выполнении, иначе False.
        """
        return await upsert_record(table_name=table_name, data=data, pk_col=pk_col, log_to_api=log_to_api)

    async def get_record_by_id(
        self,
        table_name: str,
        record_id: Any,
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Асинхронно получает запись из таблицы по первичному ключу.

        :param table_name: Название таблицы в базе данных.
        :param record_id: Идентификатор записи.
        :param pk_col: Первичный ключ.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Словарь полей записи или None.
        """
        return await get_record_by_id(table_name=table_name, record_id=record_id, pk_col=pk_col, log_to_api=log_to_api)

    async def get_latest_record(
        self,
        table_name: str,
        order_by_col: str = "id",
        log_to_api: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Асинхронно извлекает последнюю запись таблицы.

        :param table_name: Название таблицы в базе данных.
        :param order_by_col: Колонка сортировки DESC.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Словарь с последней записью или None.
        """
        return await get_latest_record(table_name=table_name, order_by_col=order_by_col, log_to_api=log_to_api)

    async def fetch_range(
        self,
        table_name: str,
        filter_col: str = "id",
        start_val: Any = None,
        stop_val: Any = None,
        limit: Optional[int] = None,
        order_asc: bool = True,
        log_to_api: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Асинхронно извлекает выборку записей по диапазону значений.

        :param table_name: Название таблицы в базе данных.
        :param filter_col: Колонка фильтрации и сортировки.
        :param start_val: Начальное значение.
        :param stop_val: Конечное значение.
        :param limit: Лимит строк.
        :param order_asc: Порядок сортировки (True — ASC, False — DESC).
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Список словарей записей.
        """
        return await fetch_range(
            table_name=table_name, filter_col=filter_col, start_val=start_val, stop_val=stop_val, limit=limit, order_asc=order_asc, log_to_api=log_to_api
        )

    async def get_aggregate(
        self,
        table_name: str,
        column_name: str,
        function: str = "AVG",
        interval_type: Optional[str] = None,
        target_time: Optional[str] = None,
        log_to_api: bool = False
    ) -> Optional[float]:
        """
        Асинхронно рассчитывает агрегатное значение по колонке.

        :param table_name: Название таблицы в базе данных.
        :param column_name: Колонка для вычисления.
        :param function: Имя SQL-функции (AVG, SUM, MIN, MAX).
        :param interval_type: Временной интервал ('hour', 'day', 'month').
        :param target_time: Целевое время фильтрации.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Вычисленное числовое значение или None.
        """
        return await get_aggregate(
            table_name=table_name, column_name=column_name, function=function, interval_type=interval_type, target_time=target_time, log_to_api=log_to_api
        )

    async def delete_record_by_id(
        self,
        table_name: str,
        record_id: Any,
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> bool:
        """
        Асинхронно удаляет запись из таблицы по первичному ключу.

        :param table_name: Название таблицы в базе данных.
        :param record_id: Идентификатор записи.
        :param pk_col: Первичный ключ.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: True при успешном удалении, иначе False.
        """
        return await delete_record_by_id(table_name=table_name, record_id=record_id, pk_col=pk_col, log_to_api=log_to_api)

    async def get_sensor_graph_points(self, hours: int = 24, log_to_api: bool = False) -> List[GraphSensorPoint]:
        """
        Асинхронно получает точки климатических данных для графиков.

        :param hours: Охват времени в часах (по умолчанию 24).
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Список объектов GraphSensorPoint.
        """
        return await get_sensor_graph_points(hours=hours, log_to_api=log_to_api)

    async def get_calibration_data(self, max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]:
        """
        Асинхронно получает сопоставленные данные для калибровки датчиков.

        :param max_time_diff_seconds: Допустимое расхождение во времени в секундах.
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Список словарей с калибровочными данными.
        """
        return await get_calibration_data(max_time_diff_seconds=max_time_diff_seconds, log_to_api=log_to_api)

    async def fetch_by_date(
        self,
        table_name: str,
        target_date: str,
        interval_type: str = "month",
        order_asc: bool = True,
        log_to_api: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Асинхронно извлекает записи за указанную дату или временной интервал.

        :param table_name: Название таблицы в базе данных.
        :param target_date: Строка целевой даты.
        :param interval_type: Тип интервала ('month', 'day', 'hour').
        :param order_asc: Порядок сортировки по id (True — ASC, False — DESC).
        :param log_to_api: Флаг логирования (True — api_log, False — work_log).
        :return: Список словарей с записями.
        """
        return await fetch_by_date(
            table_name=table_name, target_date=target_date, interval_type=interval_type, order_asc=order_asc, log_to_api=log_to_api
        )

    # --- Методы работы с показаниями газа ---

    async def get_latest_gas_record(self) -> Optional[Dict[str, Any]]:
        """
        Асинхронно запрашивает последнюю запись из таблицы показаний газа.

        :return: Словарь с полями последней записи показаний газа или None.
        """
        return await get_latest_gas_record()

    async def save_gas_record(
        self,
        timestamp: Any,
        gas_meter: float,
        gas_difference: Optional[float] = None,
        price_gas: Optional[float] = None,
        cost_of_gas: Optional[float] = None,
        **extra_fields
    ) -> Dict[str, Any]:
        """
        Асинхронно сохраняет новую запись показаний счетчика газа.

        :param timestamp: Метка времени измерения.
        :param gas_meter: Показания счетчика газа.
        :param gas_difference: Разница показаний с прошлым значением.
        :param price_gas: Тариф на газ.
        :param cost_of_gas: Рассчитанная стоимость.
        :param extra_fields: Дополнительные произвольные поля.
        :return: Словарь с сохраненной записью из базы данных.
        """
        return await save_gas_record(
            timestamp=timestamp,
            gas_meter=gas_meter,
            gas_difference=gas_difference,
            price_gas=price_gas,
            cost_of_gas=cost_of_gas,
            **extra_fields
        )

    async def get_gas_records(
        self,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Асинхронно получает список записей показаний газа с фильтрацией и пагинацией.

        :param start_date: Фильтр начальной даты.
        :param end_date: Фильтр конечной даты.
        :param limit: Количество записей в ответе (по умолчанию 100).
        :param offset: Смещение выборки (по умолчанию 0).
        :return: Список словарей с записями показаний газа.
        """
        return await get_gas_records(start_date=start_date, end_date=end_date, limit=limit, offset=offset)


# --- Синхронные хелперы для чтения настроек и запросов ---

def _get_settings_sync(log_to_api: bool = False) -> SystemSettings:
    """
    Синхронно читает настройки из 'settings_table' по id=1.

    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Объект SystemSettings с настройками.
    """
    raw = BaseRepository._get_by_id_sync("settings_table", 1, pk_col="id", log_to_api=log_to_api)
    logger = api_log if log_to_api else work_log
    if raw:
        return SystemSettings.model_validate(raw)

    logger.warning("Запись настроек id=1 в 'settings_table' не найдена.")
    return SystemSettings()


def _update_settings_sync(
    update_dto: SystemSettingsUpdate,
    settings_id: int = 1,
    log_to_api: bool = False
) -> Optional[SystemSettings]:
    """
    Синхронно обновляет данные системных настроек в базе.

    :param update_dto: DTO объект с полями для обновления.
    :param settings_id: Идентификатор записи настроек (по умолчанию 1).
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Обновленный объект SystemSettings.
    """
    current_settings = _get_settings_sync(log_to_api=log_to_api)
    current = current_settings.model_dump()
    new_data = update_dto.model_dump(exclude_unset=True)
    if not new_data:
        return SystemSettings.model_validate(current)

    current.update(new_data)
    current["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current["id"] = settings_id

    BaseRepository._upsert_sync("settings_table", current, pk_col="id", log_to_api=log_to_api)
    return SystemSettings.model_validate(current)


def _get_sensor_data_for_graphs_sync(hours: int = 24, log_to_api: bool = False) -> List[Dict[str, Any]]:
    """
    Синхронно делает выборку показаний климатических датчиков и статусов реле для графиков.

    :param hours: Глубина выборки данных в часах.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список словарей со сырыми данными из БД.
    """
    sql = """
    SELECT
        s.id, s.timestamp, s.street_temp, s.basement_temp, s.floor_temp,
        s.street_humi, s.basement_humi, s.floor_humi,
        CASE WHEN EXISTS (
            SELECT 1 FROM ventilation_table v
            WHERE v.id > 0 AND s.id >= v.id
            AND (v.stop_vent_plus = 0 OR v.stop_vent_plus IS NULL OR s.id <= v.id + v.stop_vent_plus)
        ) THEN 1 ELSE 0 END AS vent_status,
        CASE WHEN EXISTS (
            SELECT 1 FROM history_of_heating h
            WHERE h.id > 0 AND s.id >= h.id
            AND (h.stop_heat_plus = 0 OR h.stop_heat_plus IS NULL OR s.id <= h.id + h.stop_heat_plus)
        ) THEN 1 ELSE 0 END AS heat_status
    FROM table_sensor_data s
    WHERE s.timestamp >= datetime((SELECT IFNULL(MAX(timestamp), datetime('now')) FROM table_sensor_data), ?)
    ORDER BY s.timestamp ASC;
    """
    with get_db_connection() as conn:
        return [dict(row) for row in conn.cursor().execute(sql, (f"-{hours} hours",)).fetchall()]


def _get_calibration_data_sync(max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]:
    """
    Синхронно запрашивает данные сенсоров и сайта погоды для калибровки коэффициентов.

    :param max_time_diff_seconds: Допустимая разница timestamps в секундах.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список словарей с данными сопоставимых замеров.
    """
    sql = """
    SELECT
        CAST(strftime('%H', s.timestamp) AS INTEGER) AS hour_val,
        s.street_temp, s.street_humi, w.site_temp, w.site_ah
    FROM table_sensor_data s
    JOIN weather_site_table w
        ON ABS(strftime('%s', s.timestamp) - strftime('%s', w.timestamp)) <= ?
    WHERE s.sensor_or_calc_street = 1 AND s.street_temp IS NOT NULL AND s.street_humi IS NOT NULL;
    """
    with get_db_connection() as conn:
        return [dict(row) for row in conn.cursor().execute(sql, (max_time_diff_seconds,)).fetchall()]


# --- Синхронные хелперы для gas_table ---

def _get_latest_gas_record_sync() -> Optional[Dict[str, Any]]:
    """
    Синхронно выбирает последнюю запись из таблицы показаний газа.

    :return: Словарь полей записи или None, если таблица пуста.
    """
    sql = "SELECT * FROM gas_table ORDER BY timestamp DESC, id DESC LIMIT 1;"
    with get_db_connection() as conn:
        row = conn.cursor().execute(sql).fetchone()
        return dict(row) if row else None


def _save_gas_record_sync(
    timestamp: Any,
    gas_meter: float,
    gas_difference: Optional[float] = None,
    price_gas: Optional[float] = None,
    cost_of_gas: Optional[float] = None,
    **extra_fields
) -> Dict[str, Any]:
    """
    Синхронно создает запись в table_sensor_data и сохраняет данные в gas_table.

    :param timestamp: Метка времени записи.
    :param gas_meter: Показания газового счетчика.
    :param gas_difference: Расход газа за интервал.
    :param price_gas: Тариф на газ.
    :param cost_of_gas: Стоимость газа.
    :param extra_fields: Дополнительные произвольные поля.
    :return: Словарь созданной записи в gas_table.
    """
    str_ts = str(timestamp)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("INSERT INTO table_sensor_data (timestamp) VALUES (?);", (str_ts,))
        sensor_id = cursor.lastrowid

        data = {
            "id": sensor_id,
            "timestamp": str_ts,
            "gas_meter": gas_meter,
            "gas_difference": gas_difference,
            "price_gas": price_gas,
            "cost_of_gas": cost_of_gas,
            **{k: v for k, v in extra_fields.items() if v is not None}
        }

        cols = list(data.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        cols_str = ", ".join(cols)
        sql_insert = f"INSERT INTO gas_table ({cols_str}) VALUES ({placeholders});"
        cursor.execute(sql_insert, data)
        conn.commit()

        row = cursor.execute("SELECT * FROM gas_table WHERE id = ?;", (sensor_id,)).fetchone()
        return dict(row) if row else {}


def _get_gas_records_sync(
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Синхронно считывает список записей газа с фильтрацией по диапазону дат и пагинацией.

    :param start_date: Фильтр даты от.
    :param end_date: Фильтр даты до.
    :param limit: Ограничение количества строк.
    :param offset: Смещение пагинации.
    :return: Список словарей записей учета газа.
    """
    query = "SELECT * FROM gas_table"
    params: List[Any] = []
    where: List[str] = []

    if start_date:
        where.append("timestamp >= ?")
        params.append(str(start_date))
    if end_date:
        where.append("timestamp <= ?")
        params.append(str(end_date))

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        rows = conn.cursor().execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]


# --- Модульные асинхронные функции ---

async def get_settings(log_to_api: bool = False) -> SystemSettings:
    """
    Асинхронная функция получения системных настроек.

    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Объект SystemSettings.
    """
    return await asyncio.to_thread(_get_settings_sync, log_to_api)


async def get_settings_db(log_to_api: bool = False) -> SystemSettings:
    """
    Асинхронная функция получения системных настроек из БД (алиас get_settings).

    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Объект SystemSettings.
    """
    return await get_settings(log_to_api=log_to_api)


async def update_settings(
    update_dto: SystemSettingsUpdate,
    settings_id: int = 1,
    log_to_api: bool = False
) -> Optional[SystemSettings]:
    """
    Асинхронная функция обновления системных настроек.

    :param update_dto: DTO с обновленными полями настроек.
    :param settings_id: Идентификатор записи настроек (по умолчанию 1).
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Обновленный объект SystemSettings или None.
    """
    return await asyncio.to_thread(_update_settings_sync, update_dto, settings_id, log_to_api)


async def upsert_record(
    table_name: str,
    data: Dict[str, Any],
    pk_col: str = "id",
    log_to_api: bool = False
) -> bool:
    """
    Асинхронная функция вставки или обновления (UPSERT) записи.

    :param table_name: Название таблицы базы данных.
    :param data: Словарь с данными для сохранения.
    :param pk_col: Имя колонки первичного ключа.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: True при успешном выполнении, иначе False.
    """
    return await asyncio.to_thread(BaseRepository._upsert_sync, table_name, data, pk_col, log_to_api)


async def get_record_by_id(
    table_name: str,
    record_id: Any,
    pk_col: str = "id",
    log_to_api: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Асинхронная функция получения записи по первичному ключу.

    :param table_name: Название таблицы базы данных.
    :param record_id: Значение первичного ключа записи.
    :param pk_col: Название колонки первичного ключа.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Словарь полей записи или None.
    """
    return await asyncio.to_thread(BaseRepository._get_by_id_sync, table_name, record_id, pk_col, log_to_api)


async def get_latest_record(
    table_name: str,
    order_by_col: str = "id",
    log_to_api: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Асинхронная функция получения последней записи из таблицы.

    :param table_name: Название таблицы базы данных.
    :param order_by_col: Колонка сортировки DESC.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Словарь с полями записи или None.
    """
    return await asyncio.to_thread(BaseRepository._get_latest_sync, table_name, order_by_col, log_to_api)


async def fetch_range(
    table_name: str,
    filter_col: str = "id",
    start_val: Any = None,
    stop_val: Any = None,
    limit: Optional[int] = None,
    order_asc: bool = True,
    log_to_api: bool = False
) -> List[Dict[str, Any]]:
    """
    Асинхронная функция выборки записей по диапазону значений.

    :param table_name: Название таблицы базы данных.
    :param filter_col: Колонка фильтрации и сортировки.
    :param start_val: Начальное значение.
    :param stop_val: Конечное значение.
    :param limit: Ограничение выборки.
    :param order_asc: Порядок сортировки (True — ASC, False — DESC).
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список словарей с найденными записями.
    """
    return await asyncio.to_thread(
        BaseRepository._fetch_range_sync, table_name, filter_col, start_val, stop_val, limit, order_asc, log_to_api
    )


async def get_aggregate(
    table_name: str,
    column_name: str,
    function: str = "AVG",
    interval_type: Optional[str] = None,
    target_time: Optional[str] = None,
    log_to_api: bool = False
) -> Optional[float]:
    """
    Асинхронная функция расчета агрегата по колонке.

    :param table_name: Название таблицы базы данных.
    :param column_name: Имя колонки.
    :param function: Имя агрегатной функции SQL.
    :param interval_type: Временной интервал.
    :param target_time: Целевая метка времени.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Числовое значение агрегата или None.
    """
    return await asyncio.to_thread(
        BaseRepository._get_aggregate_sync, table_name, column_name, function, interval_type, target_time, log_to_api
    )


async def delete_record_by_id(
    table_name: str,
    record_id: Any,
    pk_col: str = "id",
    log_to_api: bool = False
) -> bool:
    """
    Асинхронная функция удаления записи по первичному ключу.

    :param table_name: Название таблицы базы данных.
    :param record_id: Идентификатор удаляемой записи.
    :param pk_col: Первичный ключ.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: True при успешном удалении, иначе False.
    """
    return await asyncio.to_thread(BaseRepository._delete_by_id_sync, table_name, record_id, pk_col, log_to_api)


async def get_sensor_graph_points(hours: int = 24, log_to_api: bool = False) -> List[GraphSensorPoint]:
    """
    Асинхронная функция получения климатических данных для графиков.

    :param hours: Временной интервал выборки в часах.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список объектов GraphSensorPoint.
    """
    raw = await asyncio.to_thread(_get_sensor_data_for_graphs_sync, hours, log_to_api)
    return [GraphSensorPoint.model_validate(item) for item in raw]


async def get_calibration_data(max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]:
    """
    Асинхронная функция получения данных для калибровки датчиков.

    :param max_time_diff_seconds: Максимальное расхождение timestamps в секундах.
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список словарей с данными замеров.
    """
    return await asyncio.to_thread(_get_calibration_data_sync, max_time_diff_seconds, log_to_api)


async def fetch_by_date(
    table_name: str,
    target_date: str,
    interval_type: str = "month",
    order_asc: bool = True,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    """
    Асинхронная функция получения записей за указанную дату или интервал.

    :param table_name: Название таблицы базы данных.
    :param target_date: Строка целевой даты.
    :param interval_type: Тип интервала ('month', 'day', 'hour').
    :param order_asc: Порядок сортировки по id (True — ASC, False — DESC).
    :param log_to_api: Флаг логирования (True — api_log, False — work_log).
    :return: Список словарей с найденными записями.
    """
    return await asyncio.to_thread(
        BaseRepository._fetch_by_date_sync,
        table_name,
        target_date,
        interval_type,
        order_asc,
        log_to_api,
    )


async def get_latest_gas_record() -> Optional[Dict[str, Any]]:
    """
    Асинхронная функция получения последней записи из таблицы показаний газа.

    :return: Словарь полей записи или None.
    """
    return await asyncio.to_thread(_get_latest_gas_record_sync)


async def save_gas_record(
    timestamp: Any,
    gas_meter: float,
    gas_difference: Optional[float] = None,
    price_gas: Optional[float] = None,
    cost_of_gas: Optional[float] = None,
    **extra_fields
) -> Dict[str, Any]:
    """
    Асинхронная функция сохранения новой записи показаний счетчика газа.

    :param timestamp: Метка времени записи.
    :param gas_meter: Показания счетчика газа.
    :param gas_difference: Разница показаний с прошлым значением.
    :param price_gas: Тариф на газ.
    :param cost_of_gas: Рассчитанная стоимость.
    :param extra_fields: Дополнительные произвольные поля.
    :return: Словарь сохраненной записи из базы данных.
    """
    return await asyncio.to_thread(
        _save_gas_record_sync,
        timestamp,
        gas_meter,
        gas_difference,
        price_gas,
        cost_of_gas,
        **extra_fields
    )


async def get_gas_records(
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Асинхронная функция выборки списка записей учета газа с пагинацией.

    :param start_date: Фильтр даты от.
    :param end_date: Фильтр даты до.
    :param limit: Количество результатов в ответе.
    :param offset: Смещение выборки.
    :return: Список словарей с записями показаний газа.
    """
    return await asyncio.to_thread(_get_gas_records_sync, start_date, end_date, limit, offset)


def get_repository() -> BaseRepository:
    """
    Фабрика для создания и получения экземпляра `BaseRepository`.

    :return: Экземпляр класса BaseRepository.
    """
    return BaseRepository()