import os
import matplotlib
matplotlib.use('Agg')  # Фоновый режим без GUI для работы на сервере
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

def sample_points_to_target(data_rows: list, vent_events: list = None, heat_events: list = None, target_min: int = 48, target_max: int = 50) -> list:
    """
    Отбирает из сырого списка строк ровно от 48 до 50 точек.
    Обязательно включает:
    1. Самую первую точку интервала.
    2. Самую ПОСЛЕДНЮЮ точку на момент создания графика (текущий замер).
    3. Точки начала и окончания проветривания и отопления.
    4. Равномерно распределенные промежуточные точки.
    """
    if not data_rows:
        return []
    
    total = len(data_rows)
    if total <= target_min:
        return data_rows

    # Индексация строк по id для быстрого поиска
    id_to_idx = {row['id']: idx for idx, row in enumerate(data_rows) if 'id' in row and row['id'] is not None}

    # 1. Множество обязательных индексов
    mandatory = set()
    mandatory.add(0)           # Первая точка
    mandatory.add(total - 1)   # ПОСЛЕДНЯЯ точка (актуальный замер)

    # Детекция переключения статусов в самих данных датчиков
    prev_v = None
    prev_h = None
    for idx, row in enumerate(data_rows):
        v = row.get('vent_status', 0)
        h = row.get('heat_status', 0)
        if prev_v is not None and v != prev_v:
            mandatory.add(idx)
            mandatory.add(max(0, idx - 1))
        if prev_h is not None and h != prev_h:
            mandatory.add(idx)
            mandatory.add(max(0, idx - 1))
        prev_v = v
        prev_h = h

    # Добавление явных ID старта/стопа из таблиц ventilation_table и heating_table
    if vent_events:
        for ve in vent_events:
            v_start = ve.get('ventilation_start')
            v_stop = ve.get('stop_ventilation')
            if v_start in id_to_idx:
                mandatory.add(id_to_idx[v_start])
            if v_stop in id_to_idx:
                mandatory.add(id_to_idx[v_stop])

    if heat_events:
        for he in heat_events:
            h_start = he.get('heating_start')
            h_stop = he.get('stop_heating')
            if h_start in id_to_idx:
                mandatory.add(id_to_idx[h_start])
            if h_stop in id_to_idx:
                mandatory.add(id_to_idx[h_stop])

    mandatory_indices = sorted(list(mandatory))
    
    # Если обязательных точек больше target_max, прореживаем промежуточные события
    if len(mandatory_indices) > target_max:
        first = mandatory_indices[0]
        last = mandatory_indices[-1]
        middle = mandatory_indices[1:-1]
        step = len(middle) / (target_max - 2)
        pruned_middle = [middle[int(i * step)] for i in range(target_max - 2)]
        selected_indices = sorted(list(set([first] + pruned_middle + [last])))
        return [data_rows[i] for i in selected_indices]

    # Заполнение до target_min (48 точек) равномерной выборкой
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

    # Корректировка количества, чтобы количество было строго в рамках 48 - 50
    if len(final_indices) < target_min and len(final_indices) < total:
        for i in range(total):
            if i not in selected_indices:
                selected_indices.add(i)
                if len(selected_indices) >= target_min or len(selected_indices) >= total:
                    break
        final_indices = sorted(list(selected_indices))

    if len(final_indices) > target_max:
        # Безопасное удаление не-обязательных промежуточных точек
        middle_candidates = [i for i in final_indices if i not in mandatory]
        while len(final_indices) > target_max and middle_candidates:
            rem = middle_candidates.pop(len(middle_candidates) // 2)
            final_indices.remove(rem)

    return [data_rows[i] for i in final_indices]

##########################################################################################
def get_event_spans(events: list, data_rows: list, start_key: str, stop_key: str) -> list:
    """
    Возвращает список временных интервалов (dt_start, dt_end) для закрашивания фона (axvspan)
    строго по фактическим событиям из ventilation_table и heating_table.
    """
    if not data_rows:
        return []

    def parse_dt(ts):
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M")
        return ts

    # Карта id -> datetime из всех доступных точек датчиков
    id_to_dt = {}
    for r in data_rows:
        r_id = r.get('id') if isinstance(r, dict) else r[0]
        r_ts = r.get('timestamp') if isinstance(r, dict) else r[1]
        if r_id is not None and r_ts is not None:
            id_to_dt[r_id] = parse_dt(r_ts)

    if not id_to_dt:
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
            stop_id = ev.get(stop_key, 0)

            if not start_id:
                continue

            # Отсекаем события вне временного окна графика
            if stop_id and stop_id != 0 and stop_id < min_id:
                continue
            if start_id > max_id:
                continue

            # Точка старта
            if start_id in id_to_dt:
                dt_start = id_to_dt[start_id]
            elif start_id < min_id:
                dt_start = min_dt
            else:
                continue

            # Точка стопа (или текущий момент, если процесс еще идет)
            if stop_id and stop_id in id_to_dt:
                dt_end = id_to_dt[stop_id]
            elif stop_id == 0 or stop_id > max_id or not stop_id:
                dt_end = max_dt
            else:
                continue

            if dt_start < dt_end:
                spans.append((dt_start, dt_end))

    return spans


def render_sensor_graphs(data_rows: list, output_dir: str = "static/graphs", vent_events: list = None, heat_events: list = None) -> None:
    """
    Генерирует графики температуры и влажности с числом точек ~48-50,
    подсвечивая последнюю точку, а также фактические циклы проветривания и отопления.
    """
    if not data_rows:
        return

    # Отбор 48–50 точек с гарантированным включением крайних точек и границ событий
    sampled_rows = sample_points_to_target(data_rows, vent_events, heat_events, target_min=48, target_max=50)
    os.makedirs(output_dir, exist_ok=True)

    timestamps = []
    st_temps, bs_temps, fl_temps = [], [], []
    st_hums, bs_hums, fl_hums = [], [], []

    for row in sampled_rows:
        ts = row['timestamp'] if isinstance(row, dict) else row[1]
        if isinstance(ts, str):
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        else:
            dt = ts
            
        timestamps.append(dt)
        st_temps.append(row['street_temp'] if isinstance(row, dict) else row[2])
        bs_temps.append(row['basement_temp'] if isinstance(row, dict) else row[3])
        fl_temps.append(row['floor_temp'] if isinstance(row, dict) else row[4])

        st_hums.append(row['street_humi'] if isinstance(row, dict) else row[5])
        bs_hums.append(row['basement_humi'] if isinstance(row, dict) else row[6])
        fl_hums.append(row['floor_humi'] if isinstance(row, dict) else row[7])

    # Получение интервалов проветривания и отопления strictly из фактических событий таблиц
    vent_spans = get_event_spans(vent_events, data_rows, 'ventilation_start', 'stop_ventilation')
    heat_spans = get_event_spans(heat_events, data_rows, 'heating_start', 'stop_heating')

    start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
    end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")

    date_fmt = mdates.DateFormatter('%d.%m\n%H:%M')
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

    # --- 1. График температуры ---
    fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_temp.suptitle(
        f'График температуры (°C) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}',
        fontsize=12, fontweight='bold'
    )

    ax_st_t.plot(timestamps, st_temps, color='#2ecc71', linewidth=1.8, label='Улица', marker='o', markersize=3)
    ax_st_t.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_t.set_ylabel('°C')

    ax_bs_t.plot(timestamps, bs_temps, color='#2980b9', linewidth=1.8, label='Подвал', marker='o', markersize=3)
    ax_bs_t.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_t.set_ylabel('°C')

    ax_fl_t.plot(timestamps, fl_temps, color='#e74c3c', linewidth=1.8, label='Пол', marker='o', markersize=3)
    ax_fl_t.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
    ax_fl_t.set_ylabel('°C')

    axes_temp = (ax_st_t, ax_bs_t, ax_fl_t)
    temps_list = (st_temps, bs_temps, fl_temps)

    for ax, vals in zip(axes_temp, temps_list):
        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color='#3498db', alpha=0.2, label='Проветривание' if i == 0 else "")

        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color='#e67e22', alpha=0.22, label='Отопление' if i == 0 else "")

        if vals:
            latest_val = vals[-1]
            ax.plot(timestamps[-1], latest_val, marker='*', markersize=9, color='#c0392b', zorder=6)
            ax.annotate(
                f"{latest_val:.1f}°C",
                xy=(timestamps[-1], latest_val),
                xytext=(-15, 8),
                textcoords='offset points',
                fontsize=8,
                fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.2", fc="#ffffff", ec="#7f8c8d", alpha=0.9)
            )

        ax.tick_params(labelbottom=True)
        ax.xaxis.set_major_formatter(date_fmt)
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.tick_params(axis='x', rotation=0, labelsize=8)

    fig_temp.savefig(os.path.join(output_dir, 'temperature.png'), dpi=110, bbox_inches='tight')
    plt.close(fig_temp)

    # --- 2. График влажности ---
    fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_hum.suptitle(
        f'График влажности (%) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}',
        fontsize=12, fontweight='bold'
    )

    ax_st_h.plot(timestamps, st_hums, color='#27ae60', linewidth=1.8, label='Улица', marker='o', markersize=3)
    ax_st_h.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_h.set_ylabel('%')

    ax_bs_h.plot(timestamps, bs_hums, color='#2980b9', linewidth=1.8, label='Подвал', marker='o', markersize=3)
    ax_bs_h.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_h.set_ylabel('%')

    ax_fl_h.plot(timestamps, fl_hums, color='#e74c3c', linewidth=1.8, label='Пол', marker='o', markersize=3)
    ax_fl_h.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
    ax_fl_h.set_ylabel('%')

    axes_hum = (ax_st_h, ax_bs_h, ax_fl_h)
    hums_list = (st_hums, bs_hums, fl_hums)

    for ax, vals in zip(axes_hum, hums_list):
        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color='#3498db', alpha=0.2, label='Проветривание' if i == 0 else "")

        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color='#e67e22', alpha=0.22, label='Отопление' if i == 0 else "")

        if vals:
            latest_val = vals[-1]
            ax.plot(timestamps[-1], latest_val, marker='*', markersize=9, color='#2980b9', zorder=6)
            ax.annotate(
                f"{latest_val:.1f}%",
                xy=(timestamps[-1], latest_val),
                xytext=(-15, 8),
                textcoords='offset points',
                fontsize=8,
                fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.2", fc="#ffffff", ec="#7f8c8d", alpha=0.9)
            )

        ax.tick_params(labelbottom=True)
        ax.xaxis.set_major_formatter(date_fmt)
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.tick_params(axis='x', rotation=0, labelsize=8)

    fig_hum.savefig(os.path.join(output_dir, 'humidity.png'), dpi=110, bbox_inches='tight')
    plt.close(fig_hum)

