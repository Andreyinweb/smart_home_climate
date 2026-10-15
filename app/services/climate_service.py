# app/services/climate_service.py

"""
Расчёты микроклимата и подготовка записей для таблиц 'table_sensor_data' и 'api_table'.

Восстановление данных датчиков подвала и пола (build_sensor_record):

- Датчик считается рабочим, только если пришли и температура, и влажность.
- Пропал один датчик: восстанавливаем разницу diff = подвал - пол по истории
  реальных пар (оба датчика реальные, оба флага sensor_or_calc_* = 1, значения не NULL).
  Источник diff выбирается по приоритету: свежая пара, медиана последних пар того же
  состояния, статистика завершённых периодов (проветривание/отопление), плавный переход
  после периода (хвост), медиана покоя за 24 часа, константа t_floor_mac_diff.
- Состояние (покой / проветривание / отопление / оба / хвост) определяется по фактическим
  таблицам ventilation_table и history_of_heating для следующей записи после последней в БД.
- Восстановленная температура ограничена по скорости изменения относительно предыдущей записи.
- Влажность переносится через абсолютную влажность живого датчика и медиану a_floor / a_basement.
- Пропали оба датчика: копия предыдущей записи, оба флага False.
- В режимах без датчика пола (BASEMENT_STREET и др.) пол считается только по t_floor_mac_diff.

Статистика периодов (diff_before, diff_median, diff_end, real_pairs, basement_street_start,
ah_ratio_median, для отопления ещё floor_temp_rise) считается лениво при восстановлении
(refresh_period_stats) и записывается в таблицы периодов.

Внимание: при восстановлении функции обращаются к БД (синхронное ядро app.db.crud).
В асинхронном коде вызывайте build_sensor_record через asyncio.to_thread.
"""

import logging
import math
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, NamedTuple, Optional, Tuple

from app.db import crud
from app.db.connection import get_db_connection

work_log = logging.getLogger("climat_app.climate")


# --- Константы алгоритма (стартовые значения, подбираются по реальным данным) ---

# Режимы, в которых есть реальный датчик пола.
FLOOR_SENSOR_MODES = ("BASEMENT_STREET_FLOOR", "BASEMENT_FLOOR")

# Состояния системы.
STATE_REST = "rest"
STATE_VENT = "vent"
STATE_HEAT = "heat"
STATE_BOTH = "both"
STATE_TAIL = "tail"

MIN_PAIRS = 3                    # минимум реальных пар, которым доверяем
FRESH_PAIR_MINUTES = 10          # свежая пара: берём diff как есть
RECENT_PAIRS_MINUTES = 60        # окно для медианы последних пар того же состояния
RECENT_PAIRS_MAX = 6             # максимум пар в этой медиане
REST_WINDOW_MINUTES = 24 * 60    # окно медианы покоя
TAIL_RECORDS = 6                 # длина хвоста после периода (записей)
HISTORY_LIMIT = 600              # сколько последних реальных пар читаем (около 2 суток)
PERIODS_LIMIT = 200              # сколько последних периодов читаем из каждой таблицы
PERIODS_FOR_STATS = 5            # сколько последних периодов с статистикой усредняем
STATS_REFRESH_LIMIT = 20         # сколько периодов досчитываем за один вызов
BEFORE_PAIRS = 6                 # пар перед стартом периода для diff_before
NOMINAL_STEP_MINUTES = 5         # период опроса датчиков
RATIO_MIN, RATIO_MAX = 0.5, 2.0  # допустимое отношение a_floor / a_basement
STEP_PERCENTILE = 95             # перцентиль реальных шагов для ограничителя скорости
STEP_MIN_SAMPLES = 20            # минимум шагов для расчёта порога по истории
STEP_MIN_LIMIT = 0.3             # минимальный порог шага, °C
DEFAULT_STEP_LIMITS = {          # пороги шага за 5 минут, если истории мало, °C
    STATE_REST: 0.5,
    STATE_VENT: 1.5,
    STATE_HEAT: 1.5,
    STATE_BOTH: 2.0,
    STATE_TAIL: 1.0,
}

# Таблицы периодов: тип -> (таблица, колонка статуса, колонка длительности).
_PERIOD_TABLES = {
    STATE_VENT: ("ventilation_table", "status_ventilation", "stop_vent_plus"),
    STATE_HEAT: ("history_of_heating", "status_heating", "stop_heat_plus"),
}

_REAL_FLAGS = {"sensor_or_calc_basement": 1, "sensor_or_calc_floor": 1}


# --- Базовые расчёты влажности ---

def _abs_humi(temp: float | None, humi: float | None) -> Optional[float]:
    """Абсолютная влажность (г/м³) или None, если рассчитать нельзя."""
    if temp is None or humi is None:
        return None
    try:
        es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
        e = es * (humi / 100.0)
        return round((216.7 * e) / (temp + 273.15), 2)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _rel_humi(temp: float | None, ah: float | None) -> Optional[float]:
    """Относительная влажность (%) по абсолютной или None, если рассчитать нельзя."""
    if temp is None or ah is None or temp <= -273.15 or ah <= 0:
        return None
    try:
        es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
        if es == 0:
            return None
        e = (ah * (temp + 273.15)) / 216.7
        rh = (e / es) * 100.0
        return min(100.0, max(0.0, round(rh, 2)))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def calculate_absolute_humidity(temp: float | None, humi: float | None) -> float:
    """Расчет абсолютной влажности (г/м³). При невозможности расчёта 0.0."""
    value = _abs_humi(temp, humi)
    return 0.0 if value is None else value


def calculate_dew_point(temp: float | None, humi: float | None) -> float:
    """Расчет точки росы (°C)."""
    if temp is None or humi is None or humi <= 0:
        return 0.0
    try:
        a = 17.27
        b = 237.7
        alpha = ((a * temp) / (b + temp)) + math.log(humi / 100.0)
        dp = (b * alpha) / (a - alpha)
        return round(dp, 2)
    except Exception:
        return 0.0


def calculate_relative_humidity(temp: float | None, ah: float | None) -> float:
    """Обратный расчет относительной влажности (%). При невозможности расчёта 0.0."""
    value = _rel_humi(temp, ah)
    return 0.0 if value is None else value


def calculating_temperature_from_humidity(temp: float, ah: float, target_rh: float) -> Tuple[float, float]:
    """Расчет догрева воздуха (°C) для достижения target_rh."""
    temp_heated = round(temp, 1)
    delta = 0.0
    for _ in range(300):
        rh = calculate_relative_humidity(temp_heated, ah)
        if rh <= target_rh:
            break
        temp_heated += 0.1
        delta += 0.1
    return round(temp_heated, 1), round(delta, 1)


# --- Внутренние структуры и помощники восстановления ---

class _Pair(NamedTuple):
    """Реальная пара показаний подвал/пол из истории."""
    id: int
    ts: Any
    b_temp: float
    f_temp: float
    diff: float                    # подвал - пол
    ratio: Optional[float]         # a_floor / a_basement
    state: str = STATE_REST
    tail_step: int = 0


class _Period(NamedTuple):
    """Период проветривания или отопления. end=None, если период открыт."""
    id: int
    end: Optional[int]
    kind: str
    row: Dict[str, Any]


class _Choice(NamedTuple):
    """Выбранные для восстановления разница температур и отношение абсолютных влажностей."""
    diff: float
    ratio: float
    source: str


@contextmanager
def _connection(conn: Optional[sqlite3.Connection]) -> Generator[sqlite3.Connection, None, None]:
    """Отдаёт переданное соединение или открывает своё."""
    if conn is not None:
        yield conn
    else:
        with get_db_connection() as own_conn:
            yield own_conn


def _to_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _minutes_between(later: Any, earlier: Any) -> Optional[float]:
    """Минуты между двумя метками времени или None, если их нельзя сравнить."""
    a, b = _to_dt(later), _to_dt(earlier)
    if a is None or b is None:
        return None
    try:
        return (a - b).total_seconds() / 60.0
    except TypeError:  # смесь naive и aware
        return None


def _age_minutes(now_ts: Any, ts: Any) -> float:
    """Возраст записи в минутах; если неизвестен, считается бесконечным."""
    minutes = _minutes_between(now_ts, ts)
    return float("inf") if minutes is None else minutes


def _median_or(values: List[Optional[float]], default: float) -> float:
    clean = [v for v in values if v is not None]
    return float(statistics.median(clean)) if clean else default


def _median_ratio(pairs: List[_Pair]) -> float:
    return _median_or([p.ratio for p in pairs], 1.0)


def _percentile(values: List[float], pct: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _pair_from_row(row: Dict[str, Any]) -> Optional[_Pair]:
    """Строит пару из строки table_sensor_data. None, если есть пропуски значений."""
    b_t, f_t = row.get("basement_temp"), row.get("floor_temp")
    b_h, f_h = row.get("basement_humi"), row.get("floor_humi")
    if b_t is None or f_t is None or b_h is None or f_h is None:
        return None
    ah_b, ah_f = _abs_humi(b_t, b_h), _abs_humi(f_t, f_h)
    ratio = None
    if ah_b and ah_f:
        r = ah_f / ah_b
        if RATIO_MIN <= r <= RATIO_MAX:
            ratio = r
    return _Pair(row["id"], row.get("timestamp"), b_t, f_t, b_t - f_t, ratio)


def _load_periods(c: sqlite3.Connection) -> List[_Period]:
    """
    Читает последние периоды обеих таблиц.

    Открытый период (статус True) заканчивается перед стартом следующего периода того же
    типа, если такой есть (защита от «зависшего» периода после перезапуска программы).
    """
    periods: List[_Period] = []
    for kind, (table, status_col, stop_col) in _PERIOD_TABLES.items():
        rows = crud.get_sync(table, limit=PERIODS_LIMIT, conn=c)
        rows = sorted((r for r in rows if r.get("id") and r["id"] > 0), key=lambda r: r["id"])
        for i, row in enumerate(rows):
            start = row["id"]
            if row.get(status_col):
                end = rows[i + 1]["id"] - 1 if i + 1 < len(rows) else None
            else:
                end = start + int(row.get(stop_col) or 0)
            periods.append(_Period(start, end, kind, row))
    return periods


def _state_at(rec_id: int, periods: List[_Period]) -> Tuple[str, int, Optional[_Period]]:
    """
    Состояние системы на записи rec_id.

    :return: (состояние, шаг хвоста, последний завершившийся период). Шаг и период
             заполнены только для STATE_TAIL.
    """
    in_vent = in_heat = False
    last_ended: Optional[_Period] = None
    for p in periods:
        if p.id > rec_id:
            continue
        if p.end is None or rec_id <= p.end:
            if p.kind == STATE_VENT:
                in_vent = True
            else:
                in_heat = True
        elif last_ended is None or p.end > last_ended.end:
            last_ended = p
    if in_vent and in_heat:
        return STATE_BOTH, 0, None
    if in_vent:
        return STATE_VENT, 0, None
    if in_heat:
        return STATE_HEAT, 0, None
    if last_ended is not None:
        step = rec_id - last_ended.end
        if 1 <= step <= TAIL_RECORDS:
            return STATE_TAIL, step, last_ended
    return STATE_REST, 0, None


def _load_pairs(c: sqlite3.Connection, periods: List[_Period]) -> List[_Pair]:
    """Последние реальные пары (от старых к новым) с определённым состоянием."""
    rows = crud.get_sync(
        "table_sensor_data", where=_REAL_FLAGS, order_asc=False, limit=HISTORY_LIMIT, conn=c
    )
    pairs: List[_Pair] = []
    for row in reversed(rows):
        pair = _pair_from_row(row)
        if pair is None:
            continue
        state, tail_step, _ = _state_at(pair.id, periods)
        pairs.append(pair._replace(state=state, tail_step=tail_step))
    return pairs


def _stats_rows(periods: List[_Period], kind: str) -> List[Dict[str, Any]]:
    """Последние завершённые периоды типа kind с готовой статистикой (новые первыми)."""
    result: List[Dict[str, Any]] = []
    for p in sorted(periods, key=lambda x: x.id, reverse=True):
        if p.kind != kind or p.end is None:
            continue
        row = p.row
        if (row.get("real_pairs") or 0) >= MIN_PAIRS and row.get("diff_median") is not None:
            result.append(row)
            if len(result) >= PERIODS_FOR_STATS:
                break
    return result


def _rest_choice(pairs: List[_Pair], now_ts: Any) -> Optional[_Choice]:
    rest = [p for p in pairs
            if p.state == STATE_REST and _age_minutes(now_ts, p.ts) <= REST_WINDOW_MINUTES]
    if not rest:
        return None
    return _Choice(float(statistics.median([p.diff for p in rest])), _median_ratio(rest), "rest_24h")


def _choose_diff(
    pairs: List[_Pair],
    periods: List[_Period],
    state: str,
    tail_step: int,
    last_ended: Optional[_Period],
    now_ts: Any,
    fallback_diff: float,
) -> _Choice:
    """Выбирает разницу подвал-пол и отношение абсолютных влажностей по приоритетам."""
    same = [p for p in pairs if p.state == state]
    if same:
        last = same[-1]
        if _age_minutes(now_ts, last.ts) <= FRESH_PAIR_MINUTES:
            return _Choice(last.diff, last.ratio or 1.0, "fresh_pair")
        recent = [p for p in same if _age_minutes(now_ts, p.ts) <= RECENT_PAIRS_MINUTES]
        recent = recent[-RECENT_PAIRS_MAX:]
        if len(recent) >= MIN_PAIRS:
            return _Choice(float(statistics.median([p.diff for p in recent])),
                           _median_ratio(recent), "recent_pairs")

    base = _rest_choice(pairs, now_ts) or _Choice(fallback_diff, 1.0, "constant")

    if state in (STATE_VENT, STATE_HEAT):
        rows = _stats_rows(periods, state)
        if rows:
            return _Choice(
                float(statistics.median([r["diff_median"] for r in rows])),
                _median_or([r.get("ah_ratio_median") for r in rows], 1.0),
                "period_stats",
            )
    elif state == STATE_TAIL and last_ended is not None:
        row = last_ended.row
        if (row.get("real_pairs") or 0) >= MIN_PAIRS and row.get("diff_end") is not None:
            w = tail_step / TAIL_RECORDS
            end_ratio = row.get("ah_ratio_median") or base.ratio
            return _Choice(
                row["diff_end"] + (base.diff - row["diff_end"]) * w,
                end_ratio + (base.ratio - end_ratio) * w,
                "tail_blend",
            )
    return base


def _step_limits(pairs: List[_Pair], target: str) -> Dict[str, float]:
    """Пороги изменения температуры за шаг по состояниям (по реальным шагам в истории)."""
    steps: Dict[str, List[float]] = {s: [] for s in DEFAULT_STEP_LIMITS}
    for prev, cur in zip(pairs, pairs[1:]):
        if cur.id - prev.id != 1:
            continue
        a, b = (prev.f_temp, cur.f_temp) if target == "floor" else (prev.b_temp, cur.b_temp)
        steps[cur.state].append(abs(b - a))
    limits: Dict[str, float] = {}
    for state, default in DEFAULT_STEP_LIMITS.items():
        vals = steps[state]
        if len(vals) >= STEP_MIN_SAMPLES:
            limits[state] = max(_percentile(vals, STEP_PERCENTILE), STEP_MIN_LIMIT)
        else:
            limits[state] = default
    return limits


def _limit_step(new: float, prev: Optional[float], limit: float, steps: int) -> float:
    """Ограничивает отклонение new от prev величиной limit * steps."""
    if prev is None:
        return new
    max_delta = limit * max(1, steps)
    return min(max(new, prev - max_delta), prev + max_delta)


# --- Статистика периодов ---

def _period_stats(c: sqlite3.Connection, kind: str, start: int, end: int) -> Dict[str, Any]:
    """Считает поля статистики завершённого периода [start, end] только по реальным парам."""
    rows = crud.get_sync("table_sensor_data", where=_REAL_FLAGS, start=start, stop=end, conn=c)
    pairs = [p for p in (_pair_from_row(r) for r in rows) if p is not None]

    stats: Dict[str, Any] = {
        "real_pairs": len(pairs),
        "diff_before": None,
        "diff_median": None,
        "diff_end": None,
        "basement_street_start": None,
        "ah_ratio_median": None,
    }
    if kind == STATE_HEAT:
        stats["floor_temp_rise"] = None
    if len(pairs) < MIN_PAIRS:
        return stats

    stats["diff_median"] = round(float(statistics.median([p.diff for p in pairs])), 2)
    stats["diff_end"] = round(pairs[-1].diff, 2)
    ratios = [p.ratio for p in pairs if p.ratio is not None]
    if ratios:
        stats["ah_ratio_median"] = round(float(statistics.median(ratios)), 3)

    before_rows = crud.get_sync(
        "table_sensor_data", where=_REAL_FLAGS, stop=start - 1,
        order_asc=False, limit=BEFORE_PAIRS * 3, conn=c,
    )
    before = [p for p in (_pair_from_row(r) for r in before_rows) if p is not None][:BEFORE_PAIRS]
    if before:
        stats["diff_before"] = round(float(statistics.median([p.diff for p in before])), 2)

    start_rows = crud.get_sync("table_sensor_data", pk=start, conn=c)
    if start_rows:
        s_t, b_t = start_rows[0].get("street_temp"), start_rows[0].get("basement_temp")
        if s_t is not None and b_t is not None:
            stats["basement_street_start"] = round(b_t - s_t, 2)

    if kind == STATE_HEAT:
        floors = [p.f_temp for p in pairs]
        stats["floor_temp_rise"] = round(max(floors) - floors[0], 2)
    return stats


def refresh_period_stats(conn: Optional[sqlite3.Connection] = None, limit: int = STATS_REFRESH_LIMIT) -> int:
    """
    Досчитывает статистику завершённых периодов, у которых real_pairs ещё NULL.

    Сначала обрабатываются новые периоды. За один вызов не больше `limit` периодов
    на таблицу, поэтому для разового заполнения истории вызывайте функцию в цикле,
    пока она не вернёт 0. Если колонок статистики в таблицах ещё нет (миграция не
    выполнена), пишет предупреждение и возвращает 0.

    :return: Сколько периодов обработано.
    """
    done = 0
    try:
        with _connection(conn) as c:
            last = crud.get_sync("table_sensor_data", conn=c)
            last_id = last[0]["id"] if last else 0
            for kind, (table, status_col, stop_col) in _PERIOD_TABLES.items():
                rows = crud.get_sync(
                    table, where={status_col: 0, "real_pairs": None},
                    order_asc=False, limit=limit, conn=c,
                )
                for row in rows:
                    start = row["id"]
                    if start <= 0:
                        continue
                    end = start + int(row.get(stop_col) or 0)
                    if end > last_id:
                        continue
                    stats = _period_stats(c, kind, start, end)
                    crud.upsert_sync(table, [{"id": start, **stats}], conn=c)
                    done += 1
    except sqlite3.OperationalError as exc:
        work_log.warning(f"Статистика периодов не обновлена (выполнена ли миграция?): {exc}")
        return 0
    return done


# --- Восстановление данных датчиков ---

def _sensor_alive(raw: Dict[str, Any], name: str) -> bool:
    """Датчик рабочий, если пришли и температура, и влажность."""
    return raw.get(f"{name}_temp") is not None and raw.get(f"{name}_humi") is not None


def _plan_restore(
    c: sqlite3.Connection, now_ts: Any, target: str, fallback_diff: float
) -> Tuple[_Choice, str, Optional[float], Optional[Dict[str, Any]]]:
    """
    Подбирает параметры восстановления по истории в БД.

    :return: (выбор diff и ratio, состояние, порог шага, предыдущая запись или None).
    """
    refresh_period_stats(c)
    last_rows = crud.get_sync("table_sensor_data", conn=c)
    prev = last_rows[0] if last_rows else None
    if prev is None:
        return _Choice(fallback_diff, 1.0, "constant_no_history"), STATE_REST, None, None

    periods = _load_periods(c)
    pairs = _load_pairs(c, periods)
    state, tail_step, last_ended = _state_at(prev["id"] + 1, periods)
    choice = _choose_diff(pairs, periods, state, tail_step, last_ended, now_ts, fallback_diff)
    limit = _step_limits(pairs, target)[state]
    return choice, state, limit, prev


def _restore_missing(
    data: Dict[str, Any],
    target: str,
    has_floor_sensor: bool,
    fallback_diff: float,
    now_ts: Any,
    conn: Optional[sqlite3.Connection],
) -> None:
    """
    Восстанавливает датчик `target` ("floor" или "basement") по живому датчику.

    Изменяет data на месте: температура, влажность, напряжение и флаги.
    """
    alive = "basement" if target == "floor" else "floor"
    t_alive, h_alive = data[f"{alive}_temp"], data[f"{alive}_humi"]

    if has_floor_sensor:
        with _connection(conn) as c:
            choice, state, limit, prev = _plan_restore(c, now_ts, target, fallback_diff)
    else:
        choice, state, limit, prev = _Choice(fallback_diff, 1.0, "constant_mode"), STATE_REST, None, None

    # diff = подвал - пол
    temp = t_alive - choice.diff if target == "floor" else t_alive + choice.diff
    if prev is not None and limit is not None:
        minutes = _minutes_between(now_ts, prev.get("timestamp"))
        steps = round(minutes / NOMINAL_STEP_MINUTES) if minutes is not None and minutes > 0 else 1
        temp = _limit_step(temp, prev.get(f"{target}_temp"), limit, steps)
    temp = round(temp, 2)

    humi = None
    ah_alive = _abs_humi(t_alive, h_alive)
    if ah_alive is not None:
        # ratio = a_floor / a_basement
        ah_target = ah_alive * choice.ratio if target == "floor" else ah_alive / choice.ratio
        humi = _rel_humi(temp, ah_target)
    if humi is None and prev is not None:
        humi = prev.get(f"{target}_humi")

    data[f"{target}_temp"] = temp
    data[f"{target}_humi"] = humi
    data[f"{target}_voltage"] = 0.0
    data[f"sensor_or_calc_{target}"] = False
    data[f"sensor_or_calc_{alive}"] = True
    work_log.debug(
        f"Восстановлен {target}: состояние={state}, источник={choice.source}, "
        f"diff={choice.diff:.2f}, ratio={choice.ratio:.3f}, temp={temp}"
    )


def _fill_from_previous(data: Dict[str, Any], conn: Optional[sqlite3.Connection]) -> None:
    """Оба датчика пропали: повторяем предыдущую запись, оба флага False."""
    with _connection(conn) as c:
        rows = crud.get_sync("table_sensor_data", conn=c)
    prev = rows[0] if rows else None
    for key in ("basement_temp", "basement_humi", "floor_temp", "floor_humi"):
        data[key] = prev.get(key) if prev else None
    data["basement_voltage"] = 0.0
    data["floor_voltage"] = 0.0
    data["sensor_or_calc_basement"] = False
    data["sensor_or_calc_floor"] = False
    work_log.warning("Пропали оба датчика (подвал и пол): повторена предыдущая запись.")


def build_sensor_record(
    raw_ble_data: Dict[str, Any],
    sys_settings: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Формирует запись строго под схему таблицы 'table_sensor_data'.

    Проверяет значения с датчиков и при пропаже подвала или пола восстанавливает их
    по истории из БД (см. описание модуля). Улица не обрабатывается: её данные
    восстанавливаются в другом месте.

    :param raw_ble_data: Сырые данные опроса датчиков.
    :param sys_settings: Настройки системы (mode, t_floor_mac_diff).
    :param conn: Соединение с БД для чтения истории (если не передано, открывается своё).
    :return: Словарь значений для записи в table_sensor_data.
    """
    mode = getattr(sys_settings, "mode", "BASEMENT_STREET_FLOOR")
    t_floor_mac_diff = getattr(sys_settings, "t_floor_mac_diff", 0.0) or 0.0
    has_floor_sensor = mode in FLOOR_SENSOR_MODES
    now_ts = raw_ble_data.get("timestamp") or datetime.now()

    data: Dict[str, Any] = {
        "timestamp": raw_ble_data.get("timestamp"),
        "street_temp": raw_ble_data.get("street_temp"),
        "basement_temp": None,
        "floor_temp": None,
        "street_humi": raw_ble_data.get("street_humi"),
        "basement_humi": None,
        "floor_humi": None,
        "street_voltage": raw_ble_data.get("street_voltage", 0.0),
        "basement_voltage": 0.0,
        "floor_voltage": 0.0,
        "sensor_or_calc_street": raw_ble_data.get("sensor_or_calc_street", True),
        "sensor_or_calc_basement": False,
        "sensor_or_calc_floor": False,
    }

    # Без датчика пола в конфигурации его показания игнорируются: пол всегда расчётный.
    b_ok = _sensor_alive(raw_ble_data, "basement")
    f_ok = has_floor_sensor and _sensor_alive(raw_ble_data, "floor")

    for name, ok in (("basement", b_ok), ("floor", f_ok)):
        if ok:
            data[f"{name}_temp"] = raw_ble_data[f"{name}_temp"]
            data[f"{name}_humi"] = raw_ble_data[f"{name}_humi"]
            data[f"{name}_voltage"] = raw_ble_data.get(f"{name}_voltage", 0.0)
            data[f"sensor_or_calc_{name}"] = True

    if not b_ok and not f_ok:
        _fill_from_previous(data, conn)
    elif not f_ok:
        _restore_missing(data, "floor", has_floor_sensor, t_floor_mac_diff, now_ts, conn)
    elif not b_ok:
        _restore_missing(data, "basement", has_floor_sensor, t_floor_mac_diff, now_ts, conn)

    data["a_street_humi"] = _abs_humi(data["street_temp"], data["street_humi"])
    data["a_basement_humi"] = _abs_humi(data["basement_temp"], data["basement_humi"])
    data["a_floor_humi"] = _abs_humi(data["floor_temp"], data["floor_humi"])

    return data


def build_api_record(
    sensor_data: Dict[str, Any],
    row_id: int,
    sys_settings: Any
) -> Dict[str, Any]:
    """Формирует запись строго под схему таблицы 'api_table'."""
    abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)
    target_rh = getattr(sys_settings, "target_rh", 60.0)

    s_temp = sensor_data.get("street_temp", 0.0) or 0.0
    s_humi = sensor_data.get("street_humi", 0.0) or 0.0
    b_temp = sensor_data.get("basement_temp", 0.0) or 0.0
    b_humi = sensor_data.get("basement_humi", 0.0) or 0.0
    f_temp = sensor_data.get("floor_temp", 0.0) or 0.0
    f_humi = sensor_data.get("floor_humi", 0.0) or 0.0

    # TODO Удали после рефакторинга
    a_street = calculate_absolute_humidity(s_temp, s_humi)
    a_basement = calculate_absolute_humidity(b_temp, b_humi)
    a_floor = calculate_absolute_humidity(f_temp, f_humi)

    dp_street = calculate_dew_point(s_temp, s_humi)
    dp_basement = calculate_dew_point(b_temp, b_humi)
    dp_floor = calculate_dew_point(f_temp, f_humi)

    humidity_diff = round(a_basement - a_street, 2)

    if humidity_diff >= abs_tolerance:
        vent_status = True
        temp_diff = abs(b_temp - s_temp)
        vent_time_val = round(10.4 / math.sqrt(temp_diff)) if temp_diff > 0 else 0
    else:
        vent_status = False
        vent_time_val = 0

    sim_a_basement_humi = a_street
    sim_basement_humi = calculate_relative_humidity(b_temp, sim_a_basement_humi)
    sim_floor_humi = calculate_relative_humidity(f_temp, sim_a_basement_humi)

    if vent_status and sim_floor_humi > target_rh:
        floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_street, target_rh)
        heat_status = True
        basement_temp_heated = round(b_temp + heating_delta, 1)
        basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_street)
        a_basement_humi_heated = a_street
        floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_street)
        a_floor_humi_heated = a_street
    elif not vent_status and f_humi > target_rh:
        floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_floor, target_rh)
        heat_status = True
        basement_temp_heated = round(b_temp + heating_delta, 1)
        basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_basement)
        a_basement_humi_heated = a_basement
        floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_basement)
        a_floor_humi_heated = a_basement
    else:
        heat_status = False
        heating_delta = 0.0
        floor_temp_heated = f_temp
        basement_temp_heated = b_temp
        basement_humi_heated = b_humi
        a_basement_humi_heated = a_basement
        floor_humi_heated = f_humi
        a_floor_humi_heated = a_floor

    return {
        "id": row_id,
        "timestamp": sensor_data.get("timestamp"),
        "a_floor_humi": a_floor,
        "dp_floor": dp_floor,
        "a_street_humi": a_street,
        "dp_street": dp_street,
        "a_basement_humi": a_basement,
        "dp_basement": dp_basement,
        "humidity_difference": humidity_diff,
        "vent_status": vent_status,
        "vent_time_val": vent_time_val,
        "sim_a_basement_humi": sim_a_basement_humi,
        "sim_basement_humi": sim_basement_humi,
        "sim_floor_humi": sim_floor_humi,
        "heating_delta": heating_delta,
        "heat_status": heat_status,
        "floor_temp_heated": floor_temp_heated,
        "basement_temp_heated": basement_temp_heated,
        "basement_humi_heated": basement_humi_heated,
        "a_basement_humi_heated": a_basement_humi_heated,
        "floor_humi_heated": floor_humi_heated,
        "a_floor_humi_heated": a_floor_humi_heated
    }



# # app/services/climate_service.py

# import math
# from typing import Dict, Any, Tuple


# def calculate_absolute_humidity(temp: float | None, humi: float | None) -> float:
#     """Расчет абсолютной влажности (г/м³)."""
#     if temp is None or humi is None:
#         return 0.0
#     try:
#         es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
#         e = es * (humi / 100.0)
#         ah = (216.7 * e) / (temp + 273.15)
#         return round(ah, 2)
#     except Exception:
#         return 0.0


# def calculate_dew_point(temp: float | None, humi: float | None) -> float:
#     """Расчет точки росы (°C)."""
#     if temp is None or humi is None or humi <= 0:
#         return 0.0
#     try:
#         a = 17.27
#         b = 237.7
#         alpha = ((a * temp) / (b + temp)) + math.log(humi / 100.0)
#         dp = (b * alpha) / (a - alpha)
#         return round(dp, 2)
#     except Exception:
#         return 0.0


# def calculate_relative_humidity(temp: float | None, ah: float | None) -> float:
#     """Обратный расчет относительной влажности (%)."""
#     if temp is None or ah is None or temp <= -273.15 or ah <= 0:
#         return 0.0
#     try:
#         es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
#         if es == 0:
#             return 0.0
#         e = (ah * (temp + 273.15)) / 216.7
#         rh = (e / es) * 100.0
#         return min(100.0, max(0.0, round(rh, 2)))
#     except Exception:
#         return 0.0


# def calculating_temperature_from_humidity(temp: float, ah: float, target_rh: float) -> Tuple[float, float]:
#     """Расчет догрева воздуха (°C) для достижения target_rh."""
#     temp_heated = round(temp, 1)
#     delta = 0.0
#     for _ in range(300):
#         rh = calculate_relative_humidity(temp_heated, ah)
#         if rh <= target_rh:
#             break
#         temp_heated += 0.1
#         delta += 0.1
#     return round(temp_heated, 1), round(delta, 1)


# def build_sensor_record(
#     raw_ble_data: Dict[str, Any],
#     sys_settings: Any,
#     avg_diff_temp: float = 0.0
# ) -> Dict[str, Any]:
#     """Формирует запись строго под схему таблицы 'table_sensor_data'."""
#     mode = getattr(sys_settings, "mode", "BASEMENT_STREET_FLOOR")
#     t_floor_mac_diff = getattr(sys_settings, "t_floor_mac_diff", 0.0)

#     data = {
#         "timestamp": raw_ble_data.get("timestamp"),
#         "street_temp": raw_ble_data.get("street_temp"),
#         "basement_temp": raw_ble_data.get("basement_temp"),
#         "floor_temp": raw_ble_data.get("floor_temp"),
#         "street_humi": raw_ble_data.get("street_humi"),
#         "basement_humi": raw_ble_data.get("basement_humi"),
#         "floor_humi": raw_ble_data.get("floor_humi"),
#         "street_voltage": raw_ble_data.get("street_voltage", 0.0),
#         "basement_voltage": raw_ble_data.get("basement_voltage", 0.0),
#         "floor_voltage": raw_ble_data.get("floor_voltage", 0.0),
#         "sensor_or_calc_street": raw_ble_data.get("sensor_or_calc_street", True),
#         "sensor_or_calc_basement": raw_ble_data.get("sensor_or_calc_basement", True),
#         "sensor_or_calc_floor": raw_ble_data.get("sensor_or_calc_floor", True),
#         "difference_temp": 0.0,
#         "average_temp": avg_diff_temp
#     }

#     b_temp = data["basement_temp"]
#     b_humi = data["basement_humi"]

#     # TODO: Доделать обработку отсутствия датчиков подвала и пола (подстановка предыдущих значений из базы)
#     if b_temp is None and data["floor_temp"] is None:
#         data["sensor_or_calc_basement"] = False
#         data["sensor_or_calc_floor"] = False
#         return data

#     if mode == "BASEMENT_STREET":
#         if b_temp is not None and b_humi is not None:
#             data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
#             abs_b = calculate_absolute_humidity(b_temp, b_humi)
#             data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
#             data["floor_voltage"] = 0.0
#             data["difference_temp"] = t_floor_mac_diff
#             data["sensor_or_calc_basement"] = True
#             data["sensor_or_calc_floor"] = False

#     elif mode in ["BASEMENT_STREET_FLOOR", "BASEMENT_FLOOR"]:
#         if b_temp is not None and data["floor_temp"] is not None:
#             data["difference_temp"] = round(b_temp - data["floor_temp"], 2)
#             data["sensor_or_calc_basement"] = True
#             data["sensor_or_calc_floor"] = True
#         elif b_temp is not None:
#             data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
#             abs_b = calculate_absolute_humidity(b_temp, b_humi)
#             data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
#             data["floor_voltage"] = 0.0
#             data["difference_temp"] = round(b_temp - data["floor_temp"], 2)
#             data["sensor_or_calc_basement"] = True
#             data["sensor_or_calc_floor"] = False

#     else:  # BASEMENT
#         if b_temp is not None and b_humi is not None:
#             data["floor_temp"] = round(b_temp - t_floor_mac_diff, 2)
#             abs_b = calculate_absolute_humidity(b_temp, b_humi)
#             data["floor_humi"] = calculate_relative_humidity(data["floor_temp"], abs_b)
#             data["floor_voltage"] = 0.0
#             data["difference_temp"] = t_floor_mac_diff
#             data["average_temp"] = t_floor_mac_diff
#             data["sensor_or_calc_basement"] = True
#             data["sensor_or_calc_floor"] = False

#     data["a_street_humi"] = calculate_absolute_humidity(data["street_temp"], data["street_humi"])
#     data["a_basement_humi"] = calculate_absolute_humidity(data["basement_temp"], data["basement_humi"])
#     data["a_floor_humi"] = calculate_absolute_humidity(data["floor_temp"], data["floor_humi"])

#     return data


# def build_api_record(
#     sensor_data: Dict[str, Any],
#     row_id: int,
#     sys_settings: Any
# ) -> Dict[str, Any]:
#     """Формирует запись строго под схему таблицы 'api_table'."""
#     abs_tolerance = getattr(sys_settings, "absolute_humidity_tolerance", 0.5)
#     target_rh = getattr(sys_settings, "target_rh", 60.0)

#     s_temp = sensor_data.get("street_temp", 0.0) or 0.0
#     s_humi = sensor_data.get("street_humi", 0.0) or 0.0
#     b_temp = sensor_data.get("basement_temp", 0.0) or 0.0
#     b_humi = sensor_data.get("basement_humi", 0.0) or 0.0
#     f_temp = sensor_data.get("floor_temp", 0.0) or 0.0
#     f_humi = sensor_data.get("floor_humi", 0.0) or 0.0

#     # TODO Удали после рефакторинга
#     a_street = calculate_absolute_humidity(s_temp, s_humi)
#     a_basement = calculate_absolute_humidity(b_temp, b_humi)
#     a_floor = calculate_absolute_humidity(f_temp, f_humi)

#     dp_street = calculate_dew_point(s_temp, s_humi)
#     dp_basement = calculate_dew_point(b_temp, b_humi)
#     dp_floor = calculate_dew_point(f_temp, f_humi)

#     humidity_diff = round(a_basement - a_street, 2)

#     if humidity_diff >= abs_tolerance:
#         vent_status = True
#         temp_diff = abs(b_temp - s_temp)
#         vent_time_val = round(10.4 / math.sqrt(temp_diff)) if temp_diff > 0 else 0
#     else:
#         vent_status = False
#         vent_time_val = 0

#     sim_a_basement_humi = a_street
#     sim_basement_humi = calculate_relative_humidity(b_temp, sim_a_basement_humi)
#     sim_floor_humi = calculate_relative_humidity(f_temp, sim_a_basement_humi)

#     if vent_status and sim_floor_humi > target_rh:
#         floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_street, target_rh)
#         heat_status = True
#         basement_temp_heated = round(b_temp + heating_delta, 1)
#         basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_street)
#         a_basement_humi_heated = a_street
#         floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_street)
#         a_floor_humi_heated = a_street
#     elif not vent_status and f_humi > target_rh:
#         floor_temp_heated, heating_delta = calculating_temperature_from_humidity(f_temp, a_floor, target_rh)
#         heat_status = True
#         basement_temp_heated = round(b_temp + heating_delta, 1)
#         basement_humi_heated = calculate_relative_humidity(basement_temp_heated, a_basement)
#         a_basement_humi_heated = a_basement
#         floor_humi_heated = calculate_relative_humidity(floor_temp_heated, a_basement)
#         a_floor_humi_heated = a_basement
#     else:
#         heat_status = False
#         heating_delta = 0.0
#         floor_temp_heated = f_temp
#         basement_temp_heated = b_temp
#         basement_humi_heated = b_humi
#         a_basement_humi_heated = a_basement
#         floor_humi_heated = f_humi
#         a_floor_humi_heated = a_floor

#     return {
#         "id": row_id,
#         "timestamp": sensor_data.get("timestamp"),
#         "a_floor_humi": a_floor,
#         "dp_floor": dp_floor,
#         "a_street_humi": a_street,
#         "dp_street": dp_street,
#         "a_basement_humi": a_basement,
#         "dp_basement": dp_basement,
#         "humidity_difference": humidity_diff,
#         "vent_status": vent_status,
#         "vent_time_val": vent_time_val,
#         "sim_a_basement_humi": sim_a_basement_humi,
#         "sim_basement_humi": sim_basement_humi,
#         "sim_floor_humi": sim_floor_humi,
#         "heating_delta": heating_delta,
#         "heat_status": heat_status,
#         "floor_temp_heated": floor_temp_heated,
#         "basement_temp_heated": basement_temp_heated,
#         "basement_humi_heated": basement_humi_heated,
#         "a_basement_humi_heated": a_basement_humi_heated,
#         "floor_humi_heated": floor_humi_heated,
#         "a_floor_humi_heated": a_floor_humi_heated
#     }