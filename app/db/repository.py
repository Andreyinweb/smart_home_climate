# app/db/repository.py
import asyncio
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from app.db.connection import get_db_connection
from app.core.config import settings as config_settings
from app.schemas.settings import SystemSettings, SystemSettingsUpdate
from app.schemas.climate import GraphSensorPoint

work_log = logging.getLogger("climat_app.repository")
api_log = logging.getLogger("api_app.repository")


class BaseRepository:
    """Универсальный атомарный репозиторий SQLite."""

    @staticmethod
    def _upsert_sync(
        table_name: str,
        data: Dict[str, Any],
        pk_col: str = "id",
        log_to_api: bool = False
    ) -> bool:
        """
        Выполняет вставку или полную замену записи (INSERT OR REPLACE).
        Внимание: заменяет всю строку, сбрасывая непереданные поля в NULL.
        """
        logger = api_log if log_to_api else work_log
        if not data:
            return False

        cols = list(data.keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        cols_str = ", ".join(cols)
        sql = f"INSERT OR REPLACE INTO {table_name} ({cols_str}) VALUES ({placeholders});"

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


# --- Работа с настройками (через BaseRepository) ---

def _get_or_create_settings_sync(log_to_api: bool = False) -> SystemSettings:
    raw = BaseRepository._get_by_id_sync("settings_table", 1, pk_col="id", log_to_api=log_to_api)
    logger = api_log if log_to_api else work_log
    if raw:
        return SystemSettings.model_validate(raw)

    default_data = {
        "id": 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": config_settings.sensor_mode.value,
        "interval_seconds": config_settings.interval_seconds,
        "max_retries": config_settings.max_retries,
        "website_return_time": config_settings.website_return_time,
        "t_floor_mac_diff": config_settings.t_floor_mac_diff,
        "absolute_humidity_tolerance": config_settings.absolute_humidity_tolerance,
        "minimum_humidity": config_settings.minimum_humidity,
        "target_rh": config_settings.target_rh,
        "dangerous_humidity": config_settings.dangerous_humidity,
        "price_gas": config_settings.price_gas,
        "hot_water_per_hour": config_settings.hot_water_per_hour,
    }
    BaseRepository._upsert_sync("settings_table", default_data, pk_col="id", log_to_api=log_to_api)
    logger.debug("Таблица 'settings_table' заполнена первый раз из конфигурации.")
    return SystemSettings.model_validate(default_data)


def _update_settings_sync(
    update_dto: SystemSettingsUpdate,
    settings_id: int = 1,
    log_to_api: bool = False
) -> Optional[SystemSettings]:
    current = _get_or_create_settings_sync(log_to_api=log_to_api).model_dump()
    new_data = update_dto.model_dump(exclude_unset=True)
    if not new_data:
        return SystemSettings.model_validate(current)

    current.update(new_data)
    current["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current["id"] = settings_id

    BaseRepository._upsert_sync("settings_table", current, pk_col="id", log_to_api=log_to_api)
    return SystemSettings.model_validate(current)


# --- Сложные специфичные запросы (JOIN / CASE) ---

def _get_sensor_data_for_graphs_sync(hours: int = 24, log_to_api: bool = False) -> List[Dict[str, Any]]:
    sql = """
    SELECT
        s.id, s.timestamp, s.street_temp, s.basement_temp, s.floor_temp,
        s.street_humi, s.basement_humi, s.floor_humi,
        CASE WHEN EXISTS (
            SELECT 1 FROM ventilation_table v
            WHERE v.id > 0 AND s.id >= v.id
            AND (v.stop_ventilation = 0 OR v.stop_ventilation IS NULL OR s.id <= v.stop_ventilation)
        ) THEN 1 ELSE 0 END AS vent_status,
        CASE WHEN EXISTS (
            SELECT 1 FROM heating_table h
            WHERE h.id > 0 AND s.id >= h.id
            AND (h.stop_heating = 0 OR h.stop_heating IS NULL OR s.id <= h.stop_heating)
        ) THEN 1 ELSE 0 END AS heat_status
    FROM table_sensor_data s
    WHERE s.timestamp >= datetime((SELECT IFNULL(MAX(timestamp), datetime('now')) FROM table_sensor_data), ?)
    ORDER BY s.timestamp ASC;
    """
    with get_db_connection() as conn:
        return [dict(row) for row in conn.cursor().execute(sql, (f"-{hours} hours",)).fetchall()]


def _get_calibration_data_sync(max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]:
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


# --- Публичный асинхронный API ---

async def get_or_create_settings(log_to_api: bool = False) -> SystemSettings:
    return await asyncio.to_thread(_get_or_create_settings_sync, log_to_api)


async def update_settings(
    update_dto: SystemSettingsUpdate,
    settings_id: int = 1,
    log_to_api: bool = False
) -> Optional[SystemSettings]:
    return await asyncio.to_thread(_update_settings_sync, update_dto, settings_id, log_to_api)


async def upsert_record(
    table_name: str,
    data: Dict[str, Any],
    pk_col: str = "id",
    log_to_api: bool = False
) -> bool:
    return await asyncio.to_thread(BaseRepository._upsert_sync, table_name, data, pk_col, log_to_api)


async def get_record_by_id(
    table_name: str,
    record_id: Any,
    pk_col: str = "id",
    log_to_api: bool = False
) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(BaseRepository._get_by_id_sync, table_name, record_id, pk_col, log_to_api)


async def get_latest_record(
    table_name: str,
    order_by_col: str = "id",
    log_to_api: bool = False
) -> Optional[Dict[str, Any]]:
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
    return await asyncio.to_thread(
        BaseRepository._get_aggregate_sync, table_name, column_name, function, interval_type, target_time, log_to_api
    )


async def delete_record_by_id(
    table_name: str,
    record_id: Any,
    pk_col: str = "id",
    log_to_api: bool = False
) -> bool:
    return await asyncio.to_thread(BaseRepository._delete_by_id_sync, table_name, record_id, pk_col, log_to_api)


async def get_sensor_graph_points(hours: int = 24, log_to_api: bool = False) -> List[GraphSensorPoint]:
    raw = await asyncio.to_thread(_get_sensor_data_for_graphs_sync, hours, log_to_api)
    return [GraphSensorPoint.model_validate(item) for item in raw]


async def get_calibration_data(max_time_diff_seconds: int = 600, log_to_api: bool = False) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_get_calibration_data_sync, max_time_diff_seconds, log_to_api)

async def fetch_by_date(
    table_name: str,
    target_date: str,
    interval_type: str = "month",
    order_asc: bool = True,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(
        BaseRepository._fetch_by_date_sync,
        table_name,
        target_date,
        interval_type,
        order_asc,
        log_to_api,
    )