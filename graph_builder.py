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

def get_event_spans(data_rows: list, status_key: str):
    """
    Возвращает список временных интервалов (dt_start, dt_end) активных режимов.
    """
    spans = []
    start_dt = None
    
    for row in data_rows:
        ts = row['timestamp']
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if isinstance(ts, str) and len(ts) >= 19 else datetime.strptime(ts, "%Y-%m-%d %H:%M") if isinstance(ts, str) else ts
        is_active = bool(row.get(status_key, 0))
        
        if is_active and start_dt is None:
            start_dt = dt
        elif not is_active and start_dt is not None:
            spans.append((start_dt, dt))
            start_dt = None
            
    if start_dt is not None and data_rows:
        ts_last = data_rows[-1]['timestamp']
        dt_last = datetime.strptime(ts_last, "%Y-%m-%d %H:%M:%S") if isinstance(ts_last, str) and len(ts_last) >= 19 else ts_last
        spans.append((start_dt, dt_last))
        
    return spans

def render_sensor_graphs(data_rows: list, output_dir: str = "static/graphs", vent_events: list = None, heat_events: list = None) -> None:
    """
    Генерирует графики температуры и влажности с числом точек ~48-50,
    подсвечивая последнюю точку, проветривание и отопление.
    Оптимизировано под слабый/старый ПК.
    """
    if not data_rows:
        return

    # Отбор строго 48–50 точек с гарантированным включением последней точки и событий
    sampled_rows = sample_points_to_target(data_rows, vent_events, heat_events, target_min=48, target_max=50)
    os.makedirs(output_dir, exist_ok=True)

    timestamps = []
    st_temps, bs_temps, fl_temps = [], [], []
    st_hums, bs_hums, fl_hums = [], [], []
    vent_flags, heat_flags = [], []

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

        vent_flags.append(row.get('vent_status', 0) if isinstance(row, dict) else 0)
        heat_flags.append(row.get('heat_status', 0) if isinstance(row, dict) else 0)

    # Интервалы проветривания и отопления
    vent_spans = get_event_spans(sampled_rows, 'vent_status')
    heat_spans = get_event_spans(sampled_rows, 'heat_status')

    start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
    end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")
    
    date_fmt = mdates.DateFormatter('%d.%m\n%H:%M')
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

    fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_temp.suptitle(
        f'График температуры (°C) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}',
        fontsize=12, fontweight='bold'
    )

    # 1. Улица
    ax_st_t.plot(timestamps, st_temps, color='#2ecc71', linewidth=1.8, label='Улица', marker='o', markersize=3)
    ax_st_t.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_t.set_ylabel('°C')

    # 2. Подвал
    ax_bs_t.plot(timestamps, bs_temps, color='#2980b9', linewidth=1.8, label='Подвал', marker='o', markersize=3)
    ax_bs_t.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_t.set_ylabel('°C')

    # 3. Пол
    ax_fl_t.plot(timestamps, fl_temps, color='#e74c3c', linewidth=1.8, label='Пол', marker='o', markersize=3)
    ax_fl_t.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
    ax_fl_t.set_ylabel('°C')

    axes_temp = (ax_st_t, ax_bs_t, ax_fl_t)
    temps_list = (st_temps, bs_temps, fl_temps)

    for ax, vals in zip(axes_temp, temps_list):
        # Отображение интервалов проветривания (голубая заливка)
        for i, (v_start, v_end) in enumerate(vent_spans):
            ax.axvspan(v_start, v_end, color='#3498db', alpha=0.2, label='Проветривание' if i == 0 else "")

        # Отображение интервалов отопления (оранжевая заливка)
        for i, (h_start, h_end) in enumerate(heat_spans):
            ax.axvspan(h_start, h_end, color='#e67e22', alpha=0.22, label='Отопление' if i == 0 else "")

        # ПОСЛЕДНЯЯ ТОЧКА (Актуальный замер)
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

    fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_hum.suptitle(
        f'График влажности (%) [{len(sampled_rows)} точек]\nПериод: {start_str} — {end_str}',
        fontsize=12, fontweight='bold'
    )

    # 1. Улица
    ax_st_h.plot(timestamps, st_hums, color='#27ae60', linewidth=1.8, label='Улица', marker='o', markersize=3)
    ax_st_h.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_h.set_ylabel('%')

    # 2. Подвал
    ax_bs_h.plot(timestamps, bs_hums, color='#2980b9', linewidth=1.8, label='Подвал', marker='o', markersize=3)
    ax_bs_h.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_h.set_ylabel('%')

    # 3. Пол
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

        # ПОСЛЕДНЯЯ ТОЧКА (Актуальный замер)
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





# import os
# import matplotlib
# matplotlib.use('Agg')  # Фоновый режим без GUI
# import matplotlib.pyplot as plt
# import matplotlib.dates as mdates
# from datetime import datetime

# def render_sensor_graphs(data_rows: list, output_dir: str = "static/graphs") -> None:
#     """
#     Принимает список строк/словарей из БД и генерирует 2 файла графиков.
#     data_rows содержит: timestamp, street_temp, basement_temp, floor_temp, street_humi, basement_humi, floor_humi
#     """
#     if not data_rows:
#         return
    
#     data_rows = data_rows[::max(1, len(data_rows) // 25)] # Снижение количества точек до 25 для графиков
#     os.makedirs(output_dir, exist_ok=True)

#     timestamps = []
#     st_temps, bs_temps, fl_temps = [], [], []
#     st_hums, bs_hums, fl_hums = [], [], []

#     for row in data_rows:
#         ts = row['timestamp'] if isinstance(row, (dict, list)) else getattr(row, 'timestamp', row[1])
#         if isinstance(ts, str):
#             try:
#                 dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
#             except ValueError:
#                 dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
#         else:
#             dt = ts
#         timestamps.append(dt)

#         st_temps.append(row['street_temp'] if isinstance(row, dict) else row[2])
#         bs_temps.append(row['basement_temp'] if isinstance(row, dict) else row[3])
#         fl_temps.append(row['floor_temp'] if isinstance(row, dict) else row[4])

#         st_hums.append(row['street_humi'] if isinstance(row, dict) else row[5])
#         bs_hums.append(row['basement_humi'] if isinstance(row, dict) else row[6])
#         fl_hums.append(row['floor_humi'] if isinstance(row, dict) else row[7])

#     # Динамический заголовок с диапазоном дат
#     start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
#     end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")

#     # Форматирование оси X: дата сверху, часы снизу (напр. "02.09\n14:00")
#     date_fmt = mdates.DateFormatter('%d.%m\n%H:%M')
#     locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

#     # -------------------------------------------------------------------------
#     # 1. ГРАФИК ТЕМПЕРАТУРЫ (°C)
#     # -------------------------------------------------------------------------
#     fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(
#         3, 1, figsize=(12, 10), sharex=True, gridspec_kw={'hspace': 0.45}
#     )
#     fig_temp.suptitle(f'График температуры (°C)\nПериод: {start_str} — {end_str}', fontsize=13, fontweight='bold')

#     # Улица
#     ax_st_t.plot(timestamps, st_temps, color='#2ecc71', linewidth=2, label='Улица', marker='o', markersize=2)
#     # ax_st_t.axhline(0, color='#e74c3c', linestyle='--', linewidth=0.8, alpha=0.7)
#     ax_st_t.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
#     ax_st_t.set_ylabel('°C')

#     # Подвал
#     ax_bs_t.plot(timestamps, bs_temps, color='#2980b9', linewidth=2, label='Подвал', marker='o', markersize=2)
#     ax_bs_t.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
#     ax_bs_t.set_ylabel('°C')

#     # Пол
#     ax_fl_t.plot(timestamps, fl_temps, color='#e74c3c', linewidth=2, label='Пол', marker='o', markersize=2)
#     ax_fl_t.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
#     ax_fl_t.set_ylabel('°C')

#     # Настройка X-оси для ВСЕХ трех графиков
#     for ax in (ax_st_t, ax_bs_t, ax_fl_t):
#         ax.tick_params(labelbottom=True)  # Показываем часы/даты под каждым графиком
#         ax.xaxis.set_major_formatter(date_fmt)
#         ax.xaxis.set_major_locator(locator)
#         ax.grid(True, linestyle=':', alpha=0.6)
#         ax.tick_params(axis='x', rotation=0, labelsize=9)

#     fig_temp.savefig(os.path.join(output_dir, 'temperature.png'), dpi=120, bbox_inches='tight')
#     plt.close(fig_temp)

#     # -------------------------------------------------------------------------
#     # 2. ГРАФИК ВЛАЖНОСТИ (%)
#     # -------------------------------------------------------------------------
#     fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(
#         3, 1, figsize=(12, 10), sharex=True, gridspec_kw={'hspace': 0.45}
#     )
#     fig_hum.suptitle(f'График влажности (%)\nПериод: {start_str} — {end_str}', fontsize=13, fontweight='bold')

#     # Улица
#     ax_st_h.plot(timestamps, st_hums, color='#27ae60', linewidth=2, label='Улица', marker='o', markersize=2)
#     ax_st_h.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
#     ax_st_h.set_ylabel('%')

#     # Подвал
#     ax_bs_h.plot(timestamps, bs_hums, color='#2980b9', linewidth=2, label='Подвал', marker='o', markersize=2)
#     ax_bs_h.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
#     ax_bs_h.set_ylabel('%')

#     # Пол
#     ax_fl_h.plot(timestamps, fl_hums, color='#e74c3c', linewidth=2, label='Пол', marker='o', markersize=2)
#     ax_fl_h.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
#     ax_fl_h.set_ylabel('%')

#     # Настройка X-оси для ВСЕХ трех графиков
#     for ax in (ax_st_h, ax_bs_h, ax_fl_h):
#         ax.tick_params(labelbottom=True)  # Показываем часы/даты под каждым графиком
#         ax.xaxis.set_major_formatter(date_fmt)
#         ax.xaxis.set_major_locator(locator)
#         ax.grid(True, linestyle=':', alpha=0.6)
#         ax.tick_params(axis='x', rotation=0, labelsize=9)

#     fig_hum.savefig(os.path.join(output_dir, 'humidity.png'), dpi=120, bbox_inches='tight')
#     plt.close(fig_hum)