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
import app.db.repository as db
from app.services.climate_engine import (
    calculate_absolute_humidity,
    calculate_relative_humidity,
)

work_log = logging.getLogger("climat_app.weather_service")


async def fetch_site_weather_data() -> Optional[Dict[str, float]]:
    """Запрашивает данные о погоде с OpenWeatherMap или Tomorrow.io."""
    api_key = settings.active_weather_api_key
    if not api_key:
        work_log.warning("SITE_WEATHER_API_KEY не установлен.")
        return None

    key_str = api_key.get_secret_value()

    if settings.site_weather == WeatherProvider.OPENWEATHERMAP:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"lat={settings.location_lat}&lon={settings.location_lon}"
            f"&appid={key_str}&units=metric"
        )
    elif settings.site_weather == WeatherProvider.TOMORROW:
        url = (
            f"https://api.tomorrow.io/v4/weather/realtime?"
            f"location={settings.location_lat},{settings.location_lon}"
            f"&apikey={key_str}"
        )
    else:
        work_log.warning(f"Неизвестный провайдер погоды: {settings.site_weather}")
        return None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ClimatApp/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                if settings.site_weather == WeatherProvider.OPENWEATHERMAP:
                    temp = float(data["main"]["temp"])
                    humi = float(data["main"]["humidity"])
                else:
                    values = data["data"]["values"]
                    temp = float(values["temperature"])
                    humi = float(values["humidity"])
                return {"temp": temp, "humi": humi}
            work_log.error(f"[{settings.site_weather.value}] Код ответа сервера: {response.status}")
    except urllib.error.URLError as e:
        work_log.error(f"[{settings.site_weather.value}] Ошибка подключения: {e}")
    except Exception as e:
        work_log.error(f"[{settings.site_weather.value}] Ошибка при запросе погоды: {e}")

    return None


async def record_site_weather(timestamp: Optional[str] = None, row_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Запрашивает погоду с сайта и записывает её ТОЛЬКО после подтверждения записи сенсоров с row_id."""
    if row_id is None:
        work_log.warning("Не передан row_id для записи погоды.")
        return None

    weather_data = await fetch_site_weather_data()
    if not weather_data:
        work_log.warning(f"Не удалось получить данные с {settings.site_weather.value}.")
        return None

    # Ожидание сохранения записи с row_id в table_sensor_data
    sensor_record_exists = False
    for _ in range(10):
        sensor_rec = await db.get_record_by_id("table_sensor_data", row_id, pk_col="id", log_to_api=False)
        if sensor_rec:
            sensor_record_exists = True
            break
        await asyncio.sleep(0.5)

    if not sensor_record_exists:
        work_log.warning(f"Запись сенсоров ID={row_id} не найдена в table_sensor_data. Погода не сохранена.")
        return None

    site_temp = weather_data["temp"]
    site_humi = weather_data["humi"]
    site_ah = calculate_absolute_humidity(site_temp, site_humi)

    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data_to_write = {
        "id": row_id,
        "timestamp": timestamp,
        "site_temp": site_temp,
        "site_humi": site_humi,
        "site_ah": site_ah,
        "name_site": settings.site_weather
    }

    if await db.upsert_record("weather_site_table", data_to_write, pk_col="id", log_to_api=False):
        work_log.info(
            f"[{settings.site_weather.value}] Записаны данные с сайта ({timestamp}): "
            f"T={site_temp}°C, RH={site_humi}%, AH={site_ah}г/м³"
        )
        return data_to_write
    return None


async def calibrate_hourly_coefficients(max_time_diff_seconds: int = 600) -> None:
    """Расчет часовых калибровочных коэффициентов delta_temp и delta_ah по медианам."""
    work_log.info("[Калибровка] Старт калибровки часовых коэффициентов...")
    rows = await db.get_calibration_data(max_time_diff_seconds, log_to_api=False)
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

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            await db.upsert_record("hourly_coefficients_table", coeff_data, pk_col="hour", log_to_api=False)

    work_log.info("[Калибровка] Калибровка часовых коэффициентов успешно завершена.")


async def get_calculated_street_climate(current_hour: int) -> Tuple[float, float, bool]:
    """Рассчитывает уличный климат на основе погоды с сайта и сохраненных коэффициентов."""
    latest_site = await db.get_latest_record("weather_site_table", log_to_api=False)
    if not latest_site:
        work_log.warning("[Расчет] Нет данных с сайта погоды. Возвращаются значения 0.0.")
        return 0.0, 0.0, False

    site_temp = float(latest_site.get("site_temp", 0.0))
    site_ah = float(latest_site.get("site_ah", 0.0))

    coeffs = await db.get_record_by_id("hourly_coefficients_table", current_hour, pk_col="hour", log_to_api=False) or {}
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