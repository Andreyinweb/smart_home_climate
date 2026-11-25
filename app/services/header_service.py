# app/services/header_service.py

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.db import crud as db

work_log = logging.getLogger("climat_app.header_service")

_EMPTY = "—"
_WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def _fmt_time(timestamp: Any) -> str:
    """'2026-11-13 01:40:33' -> 'Fr 01:40:33'. При ошибке разбора — только время или «—»."""
    if not timestamp:
        return _EMPTY
    text = str(timestamp)
    try:
        day = _WEEKDAYS[datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").weekday()]
        return f"{day} {text[11:19]}"
    except ValueError:
        return text[11:19] or _EMPTY


# Кэш шапки. Значения хранятся уже готовыми строками, шаблон ничего не форматирует.
# floor_zone: "ok" | "warn" | "bad" | "critical" | "none" (нет данных или порогов).
_header: Dict[str, Any] = {
    "time": _EMPTY,
    "t_min": _EMPTY,
    "t_now": _EMPTY,
    "t_max": _EMPTY,
    "h_street": _EMPTY,
    "h_basement": _EMPTY,
    "h_floor": _EMPTY,
    "floor_zone": "none",
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


def _to_float(value: Any) -> Optional[float]:
    """Число или None, если значения нет или оно не число."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _floor_zone(
    humidity: Any, minimum: Any, target: Any, dangerous: Any
) -> str:
    """Зона влажности пола по порогам из настроек.

    ok       — ниже minimum_humidity
    warn     — от minimum_humidity до target_rh
    bad      — от target_rh до dangerous_humidity включительно
    critical — выше dangerous_humidity
    none     — нет влажности или порогов
    """
    h = _to_float(humidity)
    t_min = _to_float(minimum)
    t_target = _to_float(target)
    t_danger = _to_float(dangerous)
    if h is None or t_min is None or t_target is None or t_danger is None:
        return "none"
    if h < t_min:
        return "ok"
    if h < t_target:
        return "warn"
    if h <= t_danger:
        return "bad"
    return "critical"


async def _latest(table: str) -> Dict[str, Any]:
    """Последняя запись таблицы или пустой словарь (ошибки не пробрасываются)."""
    try:
        rows = await db.get(
            table, order_col="id", order_asc=False, limit=1, log_to_api=False
        )
        return dict(rows[0]) if rows else {}
    except Exception as e:
        work_log.debug(f"[Шапка] Не удалось прочитать {table}: {e}")
        return {}


async def _humidity_limits() -> Dict[str, Any]:
    """Пороги влажности из настроек. При ошибке — пустые значения (зона «none»)."""
    try:
        # Импорт внутри функции, чтобы не получить циклический импорт при старте.
        from app.core.db_settings import get_settings_db

        sys_settings = await get_settings_db()
        return {
            "minimum": getattr(sys_settings, "minimum_humidity", None),
            "target": getattr(sys_settings, "target_rh", None),
            "dangerous": getattr(sys_settings, "dangerous_humidity", None),
        }
    except Exception as e:
        work_log.debug(f"[Шапка] Не удалось прочитать пороги влажности: {e}")
        return {"minimum": None, "target": None, "dangerous": None}


async def refresh_header() -> None:
    """Перечитывает БД и обновляет кэш шапки. Исключений не бросает."""
    sensor = await _latest("table_sensor_data")
    heat = await _latest("heating_table")
    vent = await _latest("ventilation_table")
    limits = await _humidity_limits()

    timestamp = sensor.get("timestamp")
    floor_humi = sensor.get("floor_humi")
    _header.update(
        {
            "time": _fmt_time(timestamp),
            "t_min": _fmt(heat.get("temperature_start")),
            "t_now": _fmt(sensor.get("basement_temp")),
            "t_max": _fmt(heat.get("temperature_stop")),
            "h_street": _fmt(sensor.get("street_humi"), "%"),
            "h_basement": _fmt(sensor.get("basement_humi"), "%"),
            "h_floor": _fmt(floor_humi, "%"),
            "floor_zone": _floor_zone(
                floor_humi,
                limits["minimum"],
                limits["target"],
                limits["dangerous"],
            ),
            "heating": bool(heat.get("status_heating")),
            "ventilation": bool(vent.get("status_ventilation")),
        }
    )


def get_header_info() -> Dict[str, Any]:
    """Синхронно отдаёт кэш шапки в шаблон (регистрируется в Jinja globals)."""
    return dict(_header)