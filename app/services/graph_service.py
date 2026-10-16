# app/services/graph_service.py

import asyncio
from datetime import datetime
import logging
import os
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import app.db.crud as db
from app.core.db_settings import get_settings_db
from app.db import queries

work_log = logging.getLogger("climat_app.services.graph_service")
api_log = logging.getLogger("api_app.services.graph_service")

_graph_lock = asyncio.Lock()


def sample_points_to_target(
    data_rows: List[Dict[str, Any]],
    vent_events: Optional[List[Dict[str, Any]]] = None,
    heat_events: Optional[List[Dict[str, Any]]] = None,
    target_min: int = 48,
    target_max: int = 50,
) -> List[Dict[str, Any]]:
    if not data_rows:
        return []

    total = len(data_rows)
    if total <= target_min:
        return data_rows

    id_to_idx = {
        row["id"]: idx
        for idx, row in enumerate(data_rows)
        if "id" in row and row["id"] is not None
    }

    mandatory = {0, total - 1}

    prev_v = None
    prev_h = None
    for idx, row in enumerate(data_rows):
        v = row.get("vent_status", 0)
        h = row.get("heat_status", 0)
        if prev_v is not None and v != prev_v:
            mandatory.add(idx)
            mandatory.add(max(0, idx - 1))
        if prev_h is not None and h != prev_h:
            mandatory.add(idx)
            mandatory.add(max(0, idx - 1))
        prev_v = v
        prev_h = h

    if vent_events:
        for ve in vent_events:
            v_start = ve.get("id")
            v_plus = ve.get("stop_vent_plus", 0) or 0
            v_stop = (v_start + v_plus) if (v_start is not None and v_plus > 0) else None
            if v_start in id_to_idx:
                mandatory.add(id_to_idx[v_start])
            if v_stop in id_to_idx:
                mandatory.add(id_to_idx[v_stop])

    if heat_events:
        for he in heat_events:
            h_start = he.get("id")
            h_plus = he.get("stop_heat_plus", 0) or 0
            h_stop = (h_start + h_plus) if (h_start is not None and h_plus > 0) else None
            if h_start in id_to_idx:
                mandatory.add(id_to_idx[h_start])
            if h_stop in id_to_idx:
                mandatory.add(id_to_idx[h_stop])

    sensor_keys = [
        "street_temp", "basement_temp", "floor_temp",
        "street_humi", "basement_humi", "floor_humi",
        "a_street_humi", "a_basement_humi", "a_floor_humi",
        "gas_per_hour", "coefficient_gas"
    ]

    def add_span_extrema(span_indices: List[int]):
        if not span_indices:
            return
        for key in sensor_keys:
            if any(key in data_rows[i] for i in span_indices):
                min_i = min(span_indices, key=lambda i: data_rows[i].get(key, 0.0) or 0.0)
                max_i = max(span_indices, key=lambda i: data_rows[i].get(key, 0.0) or 0.0)
                mandatory.add(min_i)
                mandatory.add(max_i)

    current_span = []
    for idx, row in enumerate(data_rows):
        is_active = row.get("vent_status", 0) != 0 or row.get("heat_status", 0) != 0
        if is_active:
            current_span.append(idx)
        else:
            if current_span:
                add_span_extrema(current_span)
                current_span = []

    if current_span:
        add_span_extrema(current_span)

    mandatory_indices = sorted(list(mandatory))

    if len(mandatory_indices) > target_max:
        first = mandatory_indices[0]
        last = mandatory_indices[-1]
        middle = mandatory_indices[1:-1]
        step = len(middle) / (target_max - 2) if len(middle) > 0 else 1
        pruned_middle = [middle[int(i * step)] for i in range(target_max - 2)]
        return [data_rows[i] for i in sorted(list(set([first] + pruned_middle + [last])))]

    selected_indices = set(mandatory_indices)
    needed = target_min - len(selected_indices)

    if needed > 0:
        candidates = [i for i in range(total) if i not in selected_indices]
        if candidates:
            step = len(candidates) / needed
            for k in range(needed):
                c_idx = candidates[min(int(k * step), len(candidates) - 1)]
                selected_indices.add(c_idx)

    final_indices = sorted(list(selected_indices))

    if len(final_indices) > target_max:
        middle_candidates = [i for i in final_indices if i not in mandatory]
        while len(final_indices) > target_max and middle_candidates:
            rem = middle_candidates.pop(len(middle_candidates) // 2)
            final_indices.remove(rem)

    return [data_rows[i] for i in final_indices]


def get_event_spans(
    events: List[Dict[str, Any]],
    data_rows: List[Dict[str, Any]],
    start_key: str = "id",
    plus_key: str = "stop_vent_plus",
) -> List[tuple]:
    """Формирует список интервалов (dt_start, dt_end) с устойчивым поиском по ID."""
    if not data_rows or not events:
        return []

    def parse_dt(ts: Any) -> datetime:
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M")
        return datetime.now()

    id_to_dt = {}
    for r in data_rows:
        r_id = r.get("id")
        r_ts = r.get("timestamp")
        if r_id is not None and r_ts is not None:
            id_to_dt[r_id] = parse_dt(r_ts)

    if not id_to_dt:
        return []

    sorted_ids = sorted(id_to_dt.keys())
    min_id = sorted_ids[0]
    max_id = sorted_ids[-1]
    min_dt = id_to_dt[min_id]
    max_dt = id_to_dt[max_id]

    def get_dt(target_id: int) -> datetime:
        if target_id in id_to_dt:
            return id_to_dt[target_id]
        if target_id <= min_id:
            return min_dt
        if target_id >= max_id:
            return max_dt
        # Находим ближайший ID в словаре
        closest_id = min(sorted_ids, key=lambda x: abs(x - target_id))
        return id_to_dt[closest_id]

    spans = []
    for ev in events:
        start_id = ev.get(start_key)
        plus_val = ev.get(plus_key, 0) or 0
        stop_id = (start_id + plus_val) if (start_id is not None and plus_val > 0) else 0

        if start_id is None:
            continue

        if stop_id and stop_id < min_id:
            continue
        if start_id > max_id:
            continue

        dt_start = get_dt(start_id)
        dt_end = get_dt(stop_id) if stop_id else max_dt

        if dt_start < dt_end:
            spans.append((dt_start, dt_end))

    return spans


def render_metric_graph(
    data_rows: List[Dict[str, Any]],
    metrics_config: List[Dict[str, Any]],
    title_main: str,
    output_path: str,
    vent_events: Optional[List[Dict[str, Any]]] = None,
    heat_events: Optional[List[Dict[str, Any]]] = None,
    target_lines: Optional[Dict[str, float]] = None,
) -> None:
    if not data_rows:
        work_log.warning(f"[render_metric_graph] Отмена отрисовки '{title_main}': передан пустой список данных.")
        return

    sampled_rows = sample_points_to_target(
        data_rows, vent_events, heat_events, target_min=200, target_max=210
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    timestamps = []
    for row in sampled_rows:
        ts = row.get("timestamp")
        if isinstance(ts, str):
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.now()
        timestamps.append(dt)

    vent_spans = get_event_spans(vent_events or [], data_rows, "id", "stop_vent_plus")
    heat_spans = get_event_spans(heat_events or [], data_rows, "id", "stop_heat_plus")

    start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
    end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")

    n_panels = len(metrics_config)
    fig, axes = plt.subplots(
        n_panels, 1, figsize=(11, 3 * n_panels), sharex=True, gridspec_kw={"hspace": 0.45}
    )
    if n_panels == 1:
        axes = [axes]

    fig.suptitle(
        f"{title_main} [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}",
        fontsize=12,
        fontweight="bold",
    )

    date_fmt = mdates.DateFormatter("%d.%m\n%H:%M")
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

    for ax, config in zip(axes, metrics_config):
        key = config.get("key")
        label = config.get("label", key)
        color = config.get("color", "#2980b9")
        unit = config.get("unit", "")

        values = [row.get(key, 0.0) or 0.0 for row in sampled_rows]
        ax.plot(timestamps, values, color=color, linewidth=1.8, label=label, marker="o", markersize=3)
        ax.set_title(f"Метрика: {label}", fontsize=10, loc="left", color=color, fontweight="bold")
        if unit:
            ax.set_ylabel(unit)

        if target_lines and key in target_lines:
            ax.axhline(
                y=target_lines[key],
                color="#8e44ad",
                linestyle="--",
                linewidth=1.8,
                zorder=5,
            )

        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color="#3498db", alpha=0.2, label="Проветривание" if i == 0 else "")

        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color="#e67e22", alpha=0.22, label="Отопление" if i == 0 else "")

        if values:
            latest_val = values[-1]
            ax.plot(timestamps[-1], latest_val, marker="*", markersize=9, color=color, zorder=6)
            ax.annotate(
                f"{latest_val:.1f}{unit}",
                xy=(timestamps[-1], latest_val),
                xytext=(-15, 8),
                textcoords="offset points",
                fontsize=8,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", fc="#ffffff", ec="#7f8c8d", alpha=0.9),
            )

        ax.tick_params(labelbottom=True)
        ax.xaxis.set_major_formatter(date_fmt)
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.tick_params(axis="x", rotation=0, labelsize=8)

    tmp_path = output_path + ".tmp"
    fig.savefig(tmp_path, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    os.replace(tmp_path, output_path)
    work_log.info(f"[render_metric_graph] Сохранен график: {output_path}")


async def update_graph_cache_if_needed(
    graph_type: str,
    output_filename: str,
    title: str,
    metrics_config: List[Dict[str, Any]],
    id_field: Optional[str] = None,
    target_date: Optional[str] = None,
    target_month: Optional[str] = None,
) -> Optional[bool]:
    if _graph_lock.locked():
        return None

    async with _graph_lock:
        try:
            if target_date:
                base_name, ext = os.path.splitext(output_filename)
                current_filename = f"{base_name}_{target_date}{ext}"
            elif target_month:
                base_name, ext = os.path.splitext(output_filename)
                current_filename = f"{base_name}_{target_month}{ext}"
            else:
                current_filename = output_filename

            file_path = os.path.join("static/graphs", current_filename)
            file_exists = os.path.exists(file_path)

            if (target_date or target_month) and file_exists:
                return False

            latest_sensor_rows = await db.get("table_sensor_data", order_col="id", limit=1, log_to_api=False)
            if not latest_sensor_rows:
                return False
            max_sensor_id = latest_sensor_rows[0]["id"]

            last_processed_id = 0
            latest_api = None
            if id_field:
                latest_api_rows = await db.get("api_table", order_col="id", limit=1, log_to_api=False)
                if latest_api_rows and id_field in latest_api_rows[0]:
                    latest_api = latest_api_rows[0]
                    raw_id = latest_api.get(id_field)
                    last_processed_id = raw_id if raw_id is not None else 0

            if max_sensor_id > last_processed_id or not file_exists or target_date or target_month:
                if target_date:
                    sensor_rows = await db.query(queries.SENSOR_RECORDS_BY_DATE, (f"{target_date}%",), log_to_api=False)
                elif target_month:
                    sensor_rows = await db.query(queries.SENSOR_RECORDS_BY_DATE, (f"{target_month}%",), log_to_api=False)
                else:
                    sensor_rows = await db.query(queries.SENSOR_GRAPH_POINTS, ("-24 hours",), log_to_api=False)

                if not sensor_rows and not target_date and not target_month and hasattr(db, "get_sensor_graph_points"):
                    points = await db.get_sensor_graph_points(hours=24, log_to_api=False)
                    sensor_rows = [p.model_dump() for p in points]

                # Получение событий вентиляции и отопления по диапазону ID (от и до)
                if sensor_rows:
                    min_id = sensor_rows[0]["id"]
                    max_id = sensor_rows[-1]["id"]
                    vent_events = await db.get("ventilation_table", start=min_id - 1000, stop=max_id, order_col="id", order_asc=True, log_to_api=False)
                    heat_events = await db.get("history_of_heating", start=min_id - 1000, stop=max_id, order_col="id", order_asc=True, log_to_api=False)
                else:
                    vent_events = []
                    heat_events = []

                target_lines = {}
                if graph_type == "humidity":
                    sys_settings = await get_settings_db()
                    if sys_settings:
                        val = getattr(sys_settings, "target_rh", None) or (sys_settings.get("target_rh") if isinstance(sys_settings, dict) else None)
                        if val is not None:
                            try:
                                target_lines["floor_humi"] = float(val)
                            except (ValueError, TypeError):
                                pass

                if sensor_rows:
                    await asyncio.to_thread(
                        render_metric_graph,
                        sensor_rows,
                        metrics_config,
                        title,
                        file_path,
                        vent_events,
                        heat_events,
                        target_lines,
                    )

                    if not target_date and not target_month and id_field and latest_api:
                        api_record = dict(latest_api)
                        api_record[id_field] = max_sensor_id
                        await db.upsert("api_table", [api_record], pk_col="id", log_to_api=False)

                    return True
            return False
        except Exception as e:
            work_log.exception(f"[update_graph_cache_if_needed] Ошибка для {graph_type}: {e}")
            return False


async def update_temperature_graph_cache_if_needed(target_date: Optional[str] = None, target_month: Optional[str] = None) -> Optional[bool]:
    metrics = [
        {"key": "street_temp", "label": "Улица", "color": "#2ecc71", "unit": "°C"},
        {"key": "basement_temp", "label": "Подвал", "color": "#2980b9", "unit": "°C"},
        {"key": "floor_temp", "label": "Пол", "color": "#e74c3c", "unit": "°C"},
    ]
    return await update_graph_cache_if_needed("temperature", "temperature.png", "График температуры (°C)", metrics, "last_graph_temperature_id", target_date, target_month)


async def update_humidity_graph_cache_if_needed(target_date: Optional[str] = None, target_month: Optional[str] = None) -> Optional[bool]:
    metrics = [
        {"key": "street_humi", "label": "Улица (отн.)", "color": "#27ae60", "unit": "%"},
        {"key": "basement_humi", "label": "Подвал (отн.)", "color": "#2980b9", "unit": "%"},
        {"key": "floor_humi", "label": "Пол (отн.)", "color": "#e74c3c", "unit": "%"},
    ]
    return await update_graph_cache_if_needed("humidity", "humidity.png", "График влажности (%)", metrics, "last_graph_humidity_id", target_date, target_month)


async def update_abs_humidity_graph_cache_if_needed(target_date: Optional[str] = None, target_month: Optional[str] = None) -> Optional[bool]:
    metrics = [
        {"key": "a_street_humi", "label": "Улица (абс.)", "color": "#16a085", "unit": "г/м³"},
        {"key": "a_basement_humi", "label": "Подвал (абс.)", "color": "#2980b9", "unit": "г/м³"},
        {"key": "a_floor_humi", "label": "Пол (абс.)", "color": "#d35400", "unit": "г/м³"},
    ]
    return await update_graph_cache_if_needed("abs_humidity", "abs_humidity.png", "График абсолютной влажности (г/м³)", metrics, None, target_date, target_month)


async def update_gas_graph_cache_if_needed(target_date: Optional[str] = None, target_month: Optional[str] = None) -> Optional[bool]:
    """Генерация графика потребления газа (расход в час и коэффициент) из gas_table с кэшированием."""
    if target_date:
        file_path = os.path.join("static/graphs", f"gas_{target_date}.png")
    elif target_month:
        file_path = os.path.join("static/graphs", f"gas_{target_month}.png")
    else:
        file_path = os.path.join("static/graphs", "gas.png")

    os.makedirs("static/graphs", exist_ok=True)

    if (target_date or target_month) and os.path.exists(file_path):
        return False

    if target_date:
        rows = await db.query(queries.GAS_RECORDS_BY_MONTH, (f"{target_date}%",), log_to_api=False)
    elif target_month:
        rows = await db.query(queries.GAS_RECORDS_BY_MONTH, (f"{target_month}%",), log_to_api=False)
    else:
        rows = await db.get("gas_table", limit=100, order_col="id", order_asc=False, log_to_api=False)
        rows.reverse()

    if not rows:
        return False

    metrics = [
        {"key": "gas_per_hour", "label": "Расход газа в час", "color": "#e67e22", "unit": "м³/ч"},
        {"key": "coefficient_gas", "label": "Коэффициент газа", "color": "#2980b9", "unit": ""},
    ]
    await asyncio.to_thread(
        render_metric_graph,
        rows,
        metrics,
        "Графики расхода и коэффициента газа",
        file_path,
    )
    return True