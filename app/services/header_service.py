# app/services/header_service.py

import logging
from typing import Any, Dict

from app.db import crud as db

work_log = logging.getLogger("climat_app.header_service")

_EMPTY = "—"

# Кэш шапки. Значения хранятся уже готовыми строками, шаблон ничего не форматирует.
_header: Dict[str, Any] = {
    "time": _EMPTY,
    "t_min": _EMPTY,
    "t_now": _EMPTY,
    "t_max": _EMPTY,
    "h_basement": _EMPTY,
    "h_floor": _EMPTY,
    "heating": False,
    "ventilation": False,
}


def _fmt(value: Any, suffix: str = "") -> str:
    """Число с одним знаком после запятой или «—», если значения нет."""
    if value is None:
        return _EMPTY
    try:
        return f"{float(value):.1f}{suffix}"
    except (TypeError, ValueError):
        return _EMPTY


async def _latest(table: str) -> Dict[str, Any]:
    """Последняя запись таблицы или пустой словарь (ошибки не пробрасываются)."""
    try:
        rows = await db.get(table, order_col="id", order_asc=False, limit=1, log_to_api=False)
        return dict(rows[0]) if rows else {}
    except Exception as e:
        work_log.debug(f"[Шапка] Не удалось прочитать {table}: {e}")
        return {}


async def refresh_header() -> None:
    """Перечитывает БД и обновляет кэш шапки. Исключений не бросает."""
    sensor = await _latest("table_sensor_data")
    heat = await _latest("heating_table")
    vent = await _latest("ventilation_table")

    timestamp = sensor.get("timestamp")
    _header.update(
        {
            "time": str(timestamp)[11:19] if timestamp else _EMPTY,
            "t_min": _fmt(heat.get("temperature_start")),
            "t_now": _fmt(sensor.get("basement_temp")),
            "t_max": _fmt(heat.get("temperature_stop")),
            "h_basement": _fmt(sensor.get("basement_humi"), "%"),
            "h_floor": _fmt(sensor.get("floor_humi"), "%"),
            "heating": bool(heat.get("status_heating")),
            "ventilation": bool(vent.get("status_ventilation")),
        }
    )


def get_header_info() -> Dict[str, Any]:
    """Синхронно отдаёт кэш шапки в шаблон (регистрируется в Jinja globals)."""
    return dict(_header)