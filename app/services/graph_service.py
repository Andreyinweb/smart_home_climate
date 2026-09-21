# app/services/graph_service.py

import asyncio
from datetime import datetime
import logging
import os
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # Фоновый режим без GUI
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import app.db.repository as db

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
    """Отбирает из списка замеров от 48 до 50 ключевых и равномерно распределенных точек с сохранением пиков."""
    if not data_rows:
        work_log.debug("[sample_points_to_target] Передан пустой список data_rows.")
        return []

    total = len(data_rows)
    work_log.debug(
        f"[sample_points_to_target] Старт сэмплирования. Всего записей: {total}, "
        f"целевой диапазон: [{target_min}..{target_max}]"
    )

    if total <= target_min:
        work_log.debug(
            f"[sample_points_to_target] Размер данных ({total}) <= target_min ({target_min}). "
            f"Сэмплирование не требуется."
        )
        return data_rows

    id_to_idx = {
        row["id"]: idx
        for idx, row in enumerate(data_rows)
        if "id" in row and row["id"] is not None
    }

    mandatory = set()
    mandatory.add(0)
    mandatory.add(total - 1)

    # 1. Точки переключения статусов (начало/конец процессов)
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

    # 2. Точки из таблиц событий
    if vent_events:
        for ve in vent_events:
            v_start = ve.get("id")
            v_plus = ve.get("stop_vent_plus", 0) or 0
            v_stop = (v_start + v_plus) if (v_start is not None and v_plus > 0) else None
            if v_start is not None and v_start in id_to_idx:
                mandatory.add(id_to_idx[v_start])
            if v_stop is not None and v_stop in id_to_idx:
                mandatory.add(id_to_idx[v_stop])

    if heat_events:
        for he in heat_events:
            h_start = he.get("id")
            h_plus = he.get("stop_heat__plus", 0) or 0
            h_stop = (h_start + h_plus) if (h_start is not None and h_plus > 0) else None
            if h_start is not None and h_start in id_to_idx:
                mandatory.add(id_to_idx[h_start])
            if h_stop is not None and h_stop in id_to_idx:
                mandatory.add(id_to_idx[h_stop])

    # 3. Поиск пиков (min/max) внутри интервалов отопления и проветривания
    sensor_keys = [
        "street_temp", "basement_temp", "floor_temp",
        "street_humi", "basement_humi", "floor_humi"
    ]

    def add_span_extrema(span_indices: List[int]):
        if not span_indices:
            return
        for key in sensor_keys:
            min_i = min(span_indices, key=lambda i: data_rows[i].get(key, 0.0))
            max_i = max(span_indices, key=lambda i: data_rows[i].get(key, 0.0))
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
    work_log.debug(f"[sample_points_to_target] Обязательных точек для сохранения: {len(mandatory_indices)}")

    # 4. Если обязательных точек больше target_max — прореживаем их
    if len(mandatory_indices) > target_max:
        work_log.debug(
            f"[sample_points_to_target] Число обязательных точек ({len(mandatory_indices)}) "
            f"> target_max ({target_max}). Прореживаем."
        )
        first = mandatory_indices[0]
        last = mandatory_indices[-1]
        middle = mandatory_indices[1:-1]
        step = len(middle) / (target_max - 2)
        pruned_middle = [middle[int(i * step)] for i in range(target_max - 2)]
        selected_indices = sorted(list(set([first] + pruned_middle + [last])))
        work_log.debug(f"[sample_points_to_target] Итог прореживания: {len(selected_indices)} точек.")
        return [data_rows[i] for i in selected_indices]

    # 5. Добор промежуточных точек до target_min
    selected_indices = set(mandatory_indices)
    needed = target_min - len(selected_indices)

    if needed > 0:
        work_log.debug(
            f"[sample_points_to_target] Добираем {needed} промежуточных точек "
            f"для достижения target_min ({target_min})."
        )
        candidates = [i for i in range(total) if i not in selected_indices]
        if candidates:
            step = len(candidates) / needed
            for k in range(needed):
                c_idx = candidates[min(int(k * step), len(candidates) - 1)]
                selected_indices.add(c_idx)

    final_indices = sorted(list(selected_indices))

    if len(final_indices) < target_min and len(final_indices) < total:
        for i in range(total):
            if i not in selected_indices:
                selected_indices.add(i)
                if len(selected_indices) >= target_min or len(selected_indices) >= total:
                    break
        final_indices = sorted(list(selected_indices))

    if len(final_indices) > target_max:
        work_log.debug(f"[sample_points_to_target] Корректируем выборку под target_max ({target_max}).")
        middle_candidates = [i for i in final_indices if i not in mandatory]
        while len(final_indices) > target_max and middle_candidates:
            rem = middle_candidates.pop(len(middle_candidates) // 2)
            final_indices.remove(rem)

    work_log.debug(f"[sample_points_to_target] Итоговое количество точек: {len(final_indices)}")
    return [data_rows[i] for i in final_indices]


def get_event_spans(
    events: List[Dict[str, Any]],
    data_rows: List[Dict[str, Any]],
    start_key: str = "id",
    plus_key: str = "stop_vent_plus",
) -> List[tuple]:
    """Формирует список интервалов (dt_start, dt_end) для подсветки активностей."""
    if not data_rows:
        work_log.debug(f"[get_event_spans] [{start_key}] data_rows пуст.")
        return []

    work_log.debug(f"[get_event_spans] Анализ событий ({start_key} -> {plus_key}). Событий: {len(events or [])}")

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
        work_log.debug(f"[get_event_spans] [{start_key}] Не удалось составить карту id -> timestamp.")
        return []

    sorted_ids = sorted(id_to_dt.keys())
    min_id = sorted_ids[0]
    max_id = sorted_ids[-1]
    min_dt = id_to_dt[min_id]
    max_dt = id_to_dt[max_id]

    spans = []
    if events:
        for ev in events:
            start_id = ev.get(start_key)
            plus_val = ev.get(plus_key, 0) or 0
            stop_id = (start_id + plus_val) if (start_id is not None and plus_val > 0) else 0

            if not start_id:
                continue

            if stop_id and stop_id != 0 and stop_id < min_id:
                continue
            if start_id > max_id:
                continue

            if start_id in id_to_dt:
                dt_start = id_to_dt[start_id]
            elif start_id < min_id:
                dt_start = min_dt
            else:
                continue

            if stop_id and stop_id in id_to_dt:
                dt_end = id_to_dt[stop_id]
            elif stop_id == 0 or stop_id > max_id or not stop_id:
                dt_end = max_dt
            else:
                continue

            if dt_start < dt_end:
                spans.append((dt_start, dt_end))

    work_log.debug(f"[get_event_spans] [{start_key}] Сформировано временных интервалов: {len(spans)}")
    return spans


def render_sensor_graphs(
    data_rows: List[Dict[str, Any]],
    output_dir: str = "static/graphs",
    vent_events: Optional[List[Dict[str, Any]]] = None,
    heat_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Отрисовка и сохранение PNG-графиков температуры и влажности."""
    if not data_rows:
        work_log.warning("[render_sensor_graphs] Отмена отрисовки: передан пустой список data_rows.")
        return

    work_log.debug(f"[render_sensor_graphs] Старт отрисовки. Строк: {len(data_rows)}, Директория: {output_dir}")

    sampled_rows = sample_points_to_target(
        data_rows, vent_events, heat_events, target_min=48, target_max=50
    )
    os.makedirs(output_dir, exist_ok=True)

    timestamps = []
    st_temps, bs_temps, fl_temps = [], [], []
    st_hums, bs_hums, fl_hums = [], [], []

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
        st_temps.append(row.get("street_temp", 0.0))
        bs_temps.append(row.get("basement_temp", 0.0))
        fl_temps.append(row.get("floor_temp", 0.0))

        st_hums.append(row.get("street_humi", 0.0))
        bs_hums.append(row.get("basement_humi", 0.0))
        fl_hums.append(row.get("floor_humi", 0.0))

    vent_spans = get_event_spans(
        vent_events or [], data_rows, "id", "stop_vent_plus"
    )
    heat_spans = get_event_spans(
        heat_events or [], data_rows, "id", "stop_heat__plus"
    )

    start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
    end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")
    work_log.debug(f"[render_sensor_graphs] Период: {start_str} - {end_str}. Точек сэмплирования: {len(sampled_rows)}")

    date_fmt = mdates.DateFormatter("%d.%m\n%H:%M")
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

    # --- 1. График температуры ---
    work_log.debug("[render_sensor_graphs] Генерация графика температуры...")
    fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={"hspace": 0.45}
    )
    fig_temp.suptitle(
        f"График температуры (°C) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}",
        fontsize=12,
        fontweight="bold",
    )

    ax_st_t.plot(timestamps, st_temps, color="#2ecc71", linewidth=1.8, label="Улица", marker="o", markersize=3)
    ax_st_t.set_title("Датчик: Улица", fontsize=10, loc="left", color="#27ae60", fontweight="bold")
    ax_st_t.set_ylabel("°C")

    ax_bs_t.plot(timestamps, bs_temps, color="#2980b9", linewidth=1.8, label="Подвал", marker="o", markersize=3)
    ax_bs_t.set_title("Датчик: Подвал", fontsize=10, loc="left", color="#1f618d", fontweight="bold")
    ax_bs_t.set_ylabel("°C")

    ax_fl_t.plot(timestamps, fl_temps, color="#e74c3c", linewidth=1.8, label="Пол", marker="o", markersize=3)
    ax_fl_t.set_title("Датчик: Пол", fontsize=10, loc="left", color="#c0392b", fontweight="bold")
    ax_fl_t.set_ylabel("°C")

    for ax, vals in zip((ax_st_t, ax_bs_t, ax_fl_t), (st_temps, bs_temps, fl_temps)):
        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color="#3498db", alpha=0.2, label="Проветривание" if i == 0 else "")

        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color="#e67e22", alpha=0.22, label="Отопление" if i == 0 else "")

        if vals:
            latest_val = vals[-1]
            ax.plot(timestamps[-1], latest_val, marker="*", markersize=9, color="#c0392b", zorder=6)
            ax.annotate(
                f"{latest_val:.1f}°C",
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

    temp_path = os.path.join(output_dir, "temperature.png")
    temp_tmp = temp_path + ".tmp"
    fig_temp.savefig(temp_tmp, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig_temp)
    os.replace(temp_tmp, temp_path)
    work_log.debug(f"[render_sensor_graphs] Сохранен файл графика температуры: {temp_path}")

    # --- 2. График влажности ---
    work_log.debug("[render_sensor_graphs] Генерация графика влажности...")
    fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={"hspace": 0.45}
    )
    fig_hum.suptitle(
        f"График влажности (%) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}",
        fontsize=12,
        fontweight="bold",
    )

    ax_st_h.plot(timestamps, st_hums, color="#27ae60", linewidth=1.8, label="Улица", marker="o", markersize=3)
    ax_st_h.set_title("Датчик: Улица", fontsize=10, loc="left", color="#27ae60", fontweight="bold")
    ax_st_h.set_ylabel("%")

    ax_bs_h.plot(timestamps, bs_hums, color="#2980b9", linewidth=1.8, label="Подвал", marker="o", markersize=3)
    ax_bs_h.set_title("Датчик: Подвал", fontsize=10, loc="left", color="#1f618d", fontweight="bold")
    ax_bs_h.set_ylabel("%")

    ax_fl_h.plot(timestamps, fl_hums, color="#e74c3c", linewidth=1.8, label="Пол", marker="o", markersize=3)
    ax_fl_h.set_title("Датчик: Пол", fontsize=10, loc="left", color="#c0392b", fontweight="bold")
    ax_fl_h.set_ylabel("%")

    for ax, vals in zip((ax_st_h, ax_bs_h, ax_fl_h), (st_hums, bs_hums, fl_hums)):
        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color="#3498db", alpha=0.2, label="Проветривание" if i == 0 else "")

        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color="#e67e22", alpha=0.22, label="Отопление" if i == 0 else "")

        if vals:
            latest_val = vals[-1]
            ax.plot(timestamps[-1], latest_val, marker="*", markersize=9, color="#2980b9", zorder=6)
            ax.annotate(
                f"{latest_val:.1f}%",
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

    hum_path = os.path.join(output_dir, "humidity.png")
    hum_tmp = hum_path + ".tmp"
    fig_hum.savefig(hum_tmp, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig_hum)
    os.replace(hum_tmp, hum_path)
    work_log.debug(f"[render_sensor_graphs] Сохранен файл графика влажности: {hum_path}")
    work_log.info("[render_sensor_graphs] Генерация графиков успешно завершена.")


async def update_graphs_cache_if_needed() -> bool:
    """Асинхронная проверка появления новых данных или отсутствия файлов и перерисовка графиков."""
    work_log.debug("[update_graphs_cache_if_needed] Проверка необходимости обновления графиков...")
    latest_sensor = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
    if not latest_sensor or "id" not in latest_sensor:
        work_log.debug("[update_graphs_cache_if_needed] Таблица table_sensor_data пуста.")
        return False

    max_sensor_id = latest_sensor["id"]

    latest_api = await db.get_latest_record("api_table", order_by_col="id", log_to_api=False)
    last_processed_id = latest_api.get("last_graph_sensor_id", 0) if latest_api else 0

    temp_file_exists = os.path.exists("static/graphs/temperature.png")
    hum_file_exists = os.path.exists("static/graphs/humidity.png")
    files_missing = not temp_file_exists or not hum_file_exists

    work_log.debug(
        f"[update_graphs_cache_if_needed] max_sensor_id={max_sensor_id}, "
        f"last_processed_id={last_processed_id}, files_missing={files_missing}"
    )

    if max_sensor_id > last_processed_id or files_missing:
        work_log.info(
            f"[update_graphs_cache_if_needed] Запуск генерации графиков "
            f"(новые данные: {max_sensor_id > last_processed_id}, отсутствуют файлы: {files_missing})..."
        )

        sensor_data = (
            await asyncio.to_thread(db._get_sensor_data_for_graphs_sync, 24)
            if hasattr(db, "_get_sensor_data_for_graphs_sync")
            else []
        )

        if not sensor_data:
            work_log.debug("[update_graphs_cache_if_needed] _get_sensor_data_for_graphs_sync вернул пустой результат, пробуем get_sensor_graph_points...")
            points = await db.get_sensor_graph_points(hours=24, log_to_api=False)
            sensor_data = [p.model_dump() for p in points]

        work_log.debug(f"[update_graphs_cache_if_needed] Загружено строк сенсоров: {len(sensor_data)}")

        vent_events = await db.fetch_range("ventilation_table", order_asc=True, log_to_api=False)
        heat_events = await db.fetch_range("heating_table", order_asc=True, log_to_api=False)
        work_log.debug(f"[update_graphs_cache_if_needed] Загружено событий: проветривания={len(vent_events)}, отопления={len(heat_events)}")

        if sensor_data:
            work_log.debug("[update_graphs_cache_if_needed] Запуск render_sensor_graphs во внешнем потоке...")
            await asyncio.to_thread(
                render_sensor_graphs,
                sensor_data,
                "static/graphs",
                vent_events,
                heat_events,
            )

            if latest_api and "id" in latest_api:
                api_record = dict(latest_api)
                api_record["last_graph_sensor_id"] = max_sensor_id
            else:
                api_record = {
                    "id": max_sensor_id,
                    "last_graph_sensor_id": max_sensor_id,
                }

            work_log.debug(
                f"[update_graphs_cache_if_needed] Фиксация last_graph_sensor_id={max_sensor_id} в api_table (id={api_record['id']})"
            )
            await db.upsert_record(
                "api_table",
                api_record,
                pk_col="id",
                log_to_api=False,
            )
            work_log.info(f"Графики успешно обновлены для sensor_id={max_sensor_id}")
            return True
        else:
            work_log.warning("[update_graphs_cache_if_needed] Данные за 24 часа отсутствуют. Отрисовка пропущена.")
    else:
        work_log.debug("[update_graphs_cache_if_needed] Актуальные графики уже сформированы. Изменений нет.")

    return False