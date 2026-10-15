# app/db/queries.py

"""
Нестандартные SQL-запросы приложения.

Единственное место, которое знает схему БД для сложных запросов (JOIN,
подзапросы, вычисляемые признаки). Простой CRUD сюда не выносится:
он делается через app/db/crud.py (get, upsert, delete).

Использование:
    from app.db import crud, queries
    rows = await crud.query(queries.SENSOR_GRAPH_POINTS, (f"-{hours} hours",))

Значения передаются только плейсхолдерами "?", тексты запросов живут только в коде.
"""

# Показания датчиков с признаками проветривания и отопления для графиков.
# Параметры: (modifier,) — модификатор времени SQLite относительно последней записи,
#            например "-24 hours".
# Возвращает: id, timestamp, street_temp, basement_temp, floor_temp,
#             street_humi, basement_humi, floor_humi, vent_status (0/1), heat_status (0/1).
SENSOR_GRAPH_POINTS = """
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

# Данные уличного датчика и сайта погоды для калибровки коэффициентов.
# Параметры: (max_time_diff_seconds,) — допустимое расхождение timestamp в секундах.
# Возвращает: hour_val, street_temp, street_humi, site_temp, site_ah.
CALIBRATION_DATA = """
SELECT
    CAST(strftime('%H', s.timestamp) AS INTEGER) AS hour_val,
    s.street_temp, s.street_humi, w.site_temp, w.site_ah
FROM table_sensor_data s
JOIN weather_site_table w
    ON ABS(strftime('%s', s.timestamp) - strftime('%s', w.timestamp)) <= ?
WHERE s.sensor_or_calc_street = 1 AND s.street_temp IS NOT NULL AND s.street_humi IS NOT NULL;
"""

# TODO УДАЛИТЬ после рефакторинга.
# Среднее значение разницы температур по всей таблице датчиков.
# Параметры: нет.
# Возвращает: одну строку с колонкой res (None, если таблица пуста).
AVG_DIFFERENCE_TEMP = "SELECT AVG(difference_temp) AS res FROM table_sensor_data;"