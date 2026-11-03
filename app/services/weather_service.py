# app/services/weather_service.py

import asyncio
import json
import logging
import statistics
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from app.core.config import WeatherProvider, settings
import app.db.crud as db
from app.db import queries
from app.services.climate_service import (
    calculate_absolute_humidity,
    calculate_relative_humidity,
)

work_log = logging.getLogger("climat_app.weather_service")

# Блокировка для предотвращения параллельного выполнения калибровки
_calibration_lock = asyncio.Lock()

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
# MET Norway требует осмысленный User-Agent с контактом. ЗАМЕНИТЬ email на свой.
_USER_AGENT = "ClimatApp/1.0 your@email.com"
_KEYLESS = (WeatherProvider.OPEN_METEO, WeatherProvider.MET_NO)


def _build_url(provider: WeatherProvider, key: str) -> Optional[str]:
    lat, lon = settings.location_lat, settings.location_lon
    if provider == WeatherProvider.OPENWEATHERMAP:
        return (
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"lat={lat}&lon={lon}&appid={key}&units=metric"
        )
    if provider == WeatherProvider.TOMORROW:
        return f"https://api.tomorrow.io/v4/weather/realtime?location={lat},{lon}&apikey={key}"
    if provider == WeatherProvider.OPEN_METEO:
        return (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m"
        )
    if provider == WeatherProvider.MET_NO:
        # MET Norway: не более 4 знаков после запятой, иначе 403.
        return f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}"
    return None


def _extract(provider: WeatherProvider, data: Dict[str, Any]) -> Tuple[float, float]:
    """Возвращает (температура °C, относительная влажность %)."""
    if provider == WeatherProvider.OPENWEATHERMAP:
        return float(data["main"]["temp"]), float(data["main"]["humidity"])
    if provider == WeatherProvider.TOMORROW:
        v = data["data"]["values"]
        return float(v["temperature"]), float(v["humidity"])
    if provider == WeatherProvider.OPEN_METEO:
        c = data["current"]
        return float(c["temperature_2m"]), float(c["relative_humidity_2m"])
    d = data["properties"]["timeseries"][0]["data"]["instant"]["details"]
    return float(d["air_temperature"]), float(d["relative_humidity"])


def _http_get_json(url: str) -> Any:
    """Синхронный запрос. Вызывается через asyncio.to_thread, чтобы не вешать event loop."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


async def fetch_site_weather_data() -> Optional[Dict[str, float]]:
    """Запрашивает данные о погоде у выбранного провайдера."""
    provider = settings.site_weather
    api_key = settings.active_weather_api_key
    key_str = api_key.get_secret_value() if api_key else ""

    if not key_str and provider not in _KEYLESS:
        work_log.warning("API-ключ погоды не установлен.")
        return None

    url = _build_url(provider, key_str)
    if url is None:
        work_log.warning(f"Неизвестный провайдер погоды: {provider}")
        return None

    try:
        data = await asyncio.to_thread(_http_get_json, url)
        temp, humi = _extract(provider, data)
        return {"temp": temp, "humi": humi}
    except urllib.error.URLError as e:
        work_log.error(f"[{provider.value}] Ошибка подключения: {e}")
    except Exception as e:
        work_log.error(f"[{provider.value}] Ошибка при запросе погоды: {e}")

    return None


async def record_site_weather(
    timestamp: Optional[str] = None,
    row_id: Optional[int] = None,
    cache_seconds: int = 240,
) -> Optional[Dict[str, Any]]:
    """
    Записывает погоду ТОЛЬКО после подтверждения записи сенсоров с row_id.
    Если последняя запись weather_site_table того же провайдера младше cache_seconds
    (по timestamp цикла), запрос к сайту не делается: значения копируются из неё.
    """
    if row_id is None:
        work_log.warning("Не передан row_id для записи погоды.")
        return None

    # Ожидание сохранения записи с row_id в table_sensor_data (внешний ключ)
    sensor_record_exists = False
    for _ in range(10):
        rows = await db.get("table_sensor_data", pk=row_id, pk_col="id")
        if rows:
            sensor_record_exists = True
            break
        await asyncio.sleep(0.5)

    if not sensor_record_exists:
        work_log.warning(f"Запись сенсоров ID={row_id} не найдена в table_sensor_data. Погода не сохранена.")
        return None

    if not timestamp:
        timestamp = datetime.now().strftime(_TS_FORMAT)

    provider_name = settings.site_weather.value

    # Проверка кэша: последняя запись того же провайдера и не старше cache_seconds
    site_temp = site_humi = site_ah = None
    rows = await db.get("weather_site_table", order_col="id", limit=1)
    last = rows[0] if rows else None
    if last and last.get("name_site") == provider_name:
        try:
            age = (
                datetime.strptime(timestamp, _TS_FORMAT)
                - datetime.strptime(last["timestamp"], _TS_FORMAT)
            ).total_seconds()
            if 0 <= age < cache_seconds:
                site_temp = float(last["site_temp"])
                site_humi = float(last["site_humi"])
                site_ah = float(last["site_ah"])
        except (ValueError, TypeError, KeyError):
            pass

    from_cache = site_temp is not None
    if not from_cache:
        weather_data = await fetch_site_weather_data()
        if not weather_data:
            work_log.warning(f"Не удалось получить данные с {provider_name}.")
            return None
        site_temp = weather_data["temp"]
        site_humi = weather_data["humi"]
        site_ah = calculate_absolute_humidity(site_temp, site_humi)

    data_to_write = {
        "id": row_id,
        "timestamp": timestamp,
        "site_temp": site_temp,
        "site_humi": site_humi,
        "site_ah": site_ah,
        "name_site": provider_name,
    }

    await db.upsert("weather_site_table", [data_to_write], pk_col="id")
    work_log.info(
        f"[{provider_name}] {'Скопированы предыдущие данные' if from_cache else 'Записаны данные с сайта'} "
        f"({timestamp}): T={site_temp}°C, RH={site_humi}%, AH={site_ah}г/м³"
    )
    return data_to_write


async def calibrate_hourly_coefficients(max_time_diff_seconds: int = 600, days: int = 30) -> None:
    """Расчет часовых калибровочных коэффициентов delta_temp и delta_ah по медианам за последние days дней."""
    if _calibration_lock.locked():
        work_log.info("[Калибровка] Пропуск: процесс калибровки уже выполняется.")
        return

    async with _calibration_lock:
        work_log.info(f"[Калибровка] Старт калибровки часовых коэффициентов (за {days} дн.)...")
        rows = await db.query(queries.CALIBRATION_DATA, (max_time_diff_seconds, f"-{days} days"))
        if not rows:
            work_log.warning("[Калибровка] Данные для калибровки не найдены.")
            return

        hourly_temp_deltas = {h: [] for h in range(24)}
        hourly_ah_deltas = {h: [] for h in range(24)}

        for row in rows:
            hour = int(row["hour_val"])
            s_temp = float(row["street_temp"])
            s_humi = float(row["street_humi"])
            w_temp = float(row["site_temp"])
            w_ah = float(row["site_ah"])

            s_ah = calculate_absolute_humidity(s_temp, s_humi)
            hourly_temp_deltas[hour].append(s_temp - w_temp)
            hourly_ah_deltas[hour].append(s_ah - w_ah)

        now_str = datetime.now().strftime(_TS_FORMAT)
        for h in range(24):
            t_list = hourly_temp_deltas[h]
            ah_list = hourly_ah_deltas[h]
            count = len(t_list)
            if count > 0:
                med_t = round(float(statistics.median(t_list)), 2)
                med_ah = round(float(statistics.median(ah_list)), 2)
                coeff_data = {
                    "hour": h,
                    "delta_temp": med_t,
                    "delta_ah": med_ah,
                    "samples_count": count,
                    "updated_at": now_str,
                }
                await db.upsert("hourly_coefficients_table", [coeff_data], pk_col="hour")

        work_log.info("[Калибровка] Калибровка часовых коэффициентов успешно завершена.")


async def get_calculated_street_climate(current_hour: int) -> Tuple[float, float, bool]:
    """Рассчитывает уличный климат на основе погоды с сайта и сохраненных коэффициентов."""
    rows = await db.get("weather_site_table", order_col="id", limit=1)
    latest_site = rows[0] if rows else None
    if not latest_site:
        work_log.warning("[Расчет] Нет данных с сайта погоды. Возвращаются значения 0.0.")
        return 0.0, 0.0, False

    site_temp = float(latest_site.get("site_temp", 0.0))
    site_ah = float(latest_site.get("site_ah", 0.0))

    coeff_rows = await db.get("hourly_coefficients_table", pk=current_hour, pk_col="hour")
    coeffs = coeff_rows[0] if coeff_rows else {}
    delta_temp = float(coeffs.get("delta_temp", 0.0))
    delta_ah = float(coeffs.get("delta_ah", 0.0))

    calc_temp = round(site_temp + delta_temp, 1)
    calc_ah = max(0.0, round(site_ah + delta_ah, 2))
    calc_rh = calculate_relative_humidity(calc_temp, calc_ah)

    work_log.info(
        f"[Расчет Зима] Час={current_hour:02d}: Сайт T={site_temp}°C, AH={site_ah}г/м³ | "
        f"dT={delta_temp}, dAH={delta_ah} -> Расчет T={calc_temp}°C, RH={calc_rh}%"
    )

    return calc_temp, calc_rh, False