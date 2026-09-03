# import os
# import matplotlib
# matplotlib.use('Agg')  # Фоновый режим без GUI
# import matplotlib.pyplot as plt
# import matplotlib.dates as mdates
# from datetime import datetime

# def render_sensor_graphs(data_rows: list, output_dir: str = "static/graphs") -> None:
#     """
#     Принимает список строк/словарей из БД и генерирует 2 файла графиков.
#     data_rows должен содержать:
#     timestamp, street_temp, basement_temp, floor_temp,
#     street_hum, basement_hum, floor_hum
#     """
#     if not data_rows:
#         return

#     os.makedirs(output_dir, exist_ok=True)

#     timestamps = []
#     st_temps, bs_temps, fl_temps = [], [], []
#     st_hums, bs_hums, fl_hums = [], [], []

#     for row in data_rows:
#         # Поддержка обращения как к словарю, так и к sqlite3.Row / tuple
#         ts = row['timestamp'] if isinstance(row, (dict, list)) else getattr(row, 'timestamp', row[1])
#         if isinstance(ts, str):
#             dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
#         else:
#             dt = ts
#         timestamps.append(dt)

#         st_temps.append(row['street_temp'] if isinstance(row, dict) else row[2])
#         bs_temps.append(row['basement_temp'] if isinstance(row, dict) else row[3])
#         fl_temps.append(row['floor_temp'] if isinstance(row, dict) else row[4])

#         st_hums.append(row['street_humi'] if isinstance(row, dict) else row[5])
#         bs_hums.append(row['basement_humi'] if isinstance(row, dict) else row[6])
#         fl_hums.append(row['floor_humi'] if isinstance(row, dict) else row[7])

#     fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
#     fig_temp.suptitle('График температуры (°C)', fontsize=14, fontweight='bold')

#     # 1. Улица (Зеленый / Красный акцент на 0°C)
#     ax_st_t.plot(timestamps, st_temps, color='#2ecc71', linewidth=2, label='Улица')
#     ax_st_t.axhline(0, color='#e74c3c', linestyle='--', linewidth=0.8, alpha=0.7)
#     ax_st_t.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
#     ax_st_t.set_ylabel('°C')
#     ax_st_t.grid(True, linestyle=':', alpha=0.6)

#     # 2. Подвал (Синий)
#     ax_bs_t.plot(timestamps, bs_temps, color='#2980b9', linewidth=2, label='Подвал')
#     ax_bs_t.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
#     ax_bs_t.set_ylabel('°C')
#     ax_bs_t.grid(True, linestyle=':', alpha=0.6)

#     # 3. Пол (Красный)
#     ax_fl_t.plot(timestamps, fl_temps, color='#e74c3c', linewidth=2, label='Пол')
#     ax_fl_t.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
#     ax_fl_t.set_ylabel('°C')
#     ax_fl_t.grid(True, linestyle=':', alpha=0.6)

#     # Форматирование оси X (Только часы)
#     ax_fl_t.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
#     ax_fl_t.xaxis.set_major_locator(mdates.HourLocator(interval=2))
#     fig_temp.autofmt_xdate()
#     fig_temp.tight_layout()

#     # Сохранение температуры
#     temp_file = os.path.join(output_dir, 'temperature.png')
#     fig_temp.savefig(temp_file, dpi=120)
#     plt.close(fig_temp)

#     fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
#     fig_hum.suptitle('График влажности (%)', fontsize=14, fontweight='bold')

#     # 1. Улица (Зеленый)
#     ax_st_h.plot(timestamps, st_hums, color='#27ae60', linewidth=2, label='Улица')
#     ax_st_h.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
#     ax_st_h.set_ylabel('%')
#     ax_st_h.grid(True, linestyle=':', alpha=0.6)

#     # 2. Подвал (Синий)
#     ax_bs_h.plot(timestamps, bs_hums, color='#2980b9', linewidth=2, label='Подвал')
#     ax_bs_h.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
#     ax_bs_h.set_ylabel('%')
#     ax_bs_h.grid(True, linestyle=':', alpha=0.6)

#     # 3. Пол (Красный)
#     ax_fl_h.plot(timestamps, fl_hums, color='#e74c3c', linewidth=2, label='Пол')
#     ax_fl_h.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
#     ax_fl_h.set_ylabel('%')
#     ax_fl_h.grid(True, linestyle=':', alpha=0.6)

#     # Форматирование оси X (Только часы)
#     ax_fl_h.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
#     ax_fl_h.xaxis.set_major_locator(mdates.HourLocator(interval=2))
#     fig_hum.autofmt_xdate()
#     fig_hum.tight_layout()

#     # Сохранение влажности
#     hum_file = os.path.join(output_dir, 'humidity.png')
#     fig_hum.savefig(hum_file, dpi=120)
#     plt.close(fig_hum)

import os
import matplotlib
matplotlib.use('Agg')  # Фоновый режим без GUI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

def render_sensor_graphs(data_rows: list, output_dir: str = "static/graphs") -> None:
    """
    Принимает список строк/словарей из БД и генерирует 2 файла графиков.
    data_rows содержит: timestamp, street_temp, basement_temp, floor_temp, street_humi, basement_humi, floor_humi
    """
    if not data_rows:
        return

    os.makedirs(output_dir, exist_ok=True)

    timestamps = []
    st_temps, bs_temps, fl_temps = [], [], []
    st_hums, bs_hums, fl_hums = [], [], []

    for row in data_rows:
        ts = row['timestamp'] if isinstance(row, (dict, list)) else getattr(row, 'timestamp', row[1])
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

    # Динамический заголовок с диапазоном дат
    start_str = timestamps[0].strftime("%d.%m.%Y %H:%M")
    end_str = timestamps[-1].strftime("%d.%m.%Y %H:%M")

    # Форматирование оси X: дата сверху, часы снизу (напр. "02.09\n14:00")
    date_fmt = mdates.DateFormatter('%d.%m\n%H:%M')
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)

    # -------------------------------------------------------------------------
    # 1. ГРАФИК ТЕМПЕРАТУРЫ (°C)
    # -------------------------------------------------------------------------
    fig_temp, (ax_st_t, ax_bs_t, ax_fl_t) = plt.subplots(
        3, 1, figsize=(12, 10), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_temp.suptitle(f'График температуры (°C)\nПериод: {start_str} — {end_str}', fontsize=13, fontweight='bold')

    # Улица
    ax_st_t.plot(timestamps, st_temps, color='#2ecc71', linewidth=2, label='Улица', marker='o', markersize=2)
    ax_st_t.axhline(0, color='#e74c3c', linestyle='--', linewidth=0.8, alpha=0.7)
    ax_st_t.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_t.set_ylabel('°C')

    # Подвал
    ax_bs_t.plot(timestamps, bs_temps, color='#2980b9', linewidth=2, label='Подвал', marker='o', markersize=2)
    ax_bs_t.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_t.set_ylabel('°C')

    # Пол
    ax_fl_t.plot(timestamps, fl_temps, color='#e74c3c', linewidth=2, label='Пол', marker='o', markersize=2)
    ax_fl_t.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
    ax_fl_t.set_ylabel('°C')

    # Настройка X-оси для ВСЕХ трех графиков
    for ax in (ax_st_t, ax_bs_t, ax_fl_t):
        ax.tick_params(labelbottom=True)  # Показываем часы/даты под каждым графиком
        ax.xaxis.set_major_formatter(date_fmt)
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.tick_params(axis='x', rotation=0, labelsize=9)

    fig_temp.savefig(os.path.join(output_dir, 'temperature.png'), dpi=120, bbox_inches='tight')
    plt.close(fig_temp)

    # -------------------------------------------------------------------------
    # 2. ГРАФИК ВЛАЖНОСТИ (%)
    # -------------------------------------------------------------------------
    fig_hum, (ax_st_h, ax_bs_h, ax_fl_h) = plt.subplots(
        3, 1, figsize=(12, 10), sharex=True, gridspec_kw={'hspace': 0.45}
    )
    fig_hum.suptitle(f'График влажности (%)\nПериод: {start_str} — {end_str}', fontsize=13, fontweight='bold')

    # Улица
    ax_st_h.plot(timestamps, st_hums, color='#27ae60', linewidth=2, label='Улица', marker='o', markersize=2)
    ax_st_h.set_title('Датчик: Улица', fontsize=10, loc='left', color='#27ae60', fontweight='bold')
    ax_st_h.set_ylabel('%')

    # Подвал
    ax_bs_h.plot(timestamps, bs_hums, color='#2980b9', linewidth=2, label='Подвал', marker='o', markersize=2)
    ax_bs_h.set_title('Датчик: Подвал', fontsize=10, loc='left', color='#1f618d', fontweight='bold')
    ax_bs_h.set_ylabel('%')

    # Пол
    ax_fl_h.plot(timestamps, fl_hums, color='#e74c3c', linewidth=2, label='Пол', marker='o', markersize=2)
    ax_fl_h.set_title('Датчик: Пол', fontsize=10, loc='left', color='#c0392b', fontweight='bold')
    ax_fl_h.set_ylabel('%')

    # Настройка X-оси для ВСЕХ трех графиков
    for ax in (ax_st_h, ax_bs_h, ax_fl_h):
        ax.tick_params(labelbottom=True)  # Показываем часы/даты под каждым графиком
        ax.xaxis.set_major_formatter(date_fmt)
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.tick_params(axis='x', rotation=0, labelsize=9)

    fig_hum.savefig(os.path.join(output_dir, 'humidity.png'), dpi=120, bbox_inches='tight')
    plt.close(fig_hum)