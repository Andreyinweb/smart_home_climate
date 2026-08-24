import json
import urllib.request
import urllib.error
import logging
from datetime import datetime

from settings import config
import models
import operations

work_log = logging.getLogger("climat_app.weather_service")

# def fetch_openweathermap_data():
#     """Запрашивает данные о погоде с OpenWeatherMap API по координатам."""
#     if not config.OPENWEATHER_API_KEY:
#         work_log.warning("[WeatherAPI] OPENWEATHER_API_KEY не установлен в settings/env.")
#         return None

#     url = (
#         f"https://api.openweathermap.org/data/2.5/weather?"
#         f"lat={config.LOCATION_LAT}&lon={config.LOCATION_LON}"
#         f"&appid={config.OPENWEATHER_API_KEY}&units=metric"
#     )

#     try:
#         req = urllib.request.Request(url, headers={'User-Agent': 'ClimatApp/1.0'})
#         with urllib.request.urlopen(req, timeout=10) as response:
#             if response.status == 200:
#                 data = json.loads(response.read().decode('utf-8'))
#                 temp = float(data['main']['temp'])
#                 humi = float(data['main']['humidity'])
#                 return {'temp': temp, 'humi': humi}
#             else:
#                 work_log.error(f"[WeatherAPI] Код ответа сервера: {response.status}")
#     except urllib.error.URLError as e:
#         work_log.error(f"[WeatherAPI] Ошибка подключения к OpenWeatherMap: {e}")
#     except Exception as e:
#         work_log.error(f"[WeatherAPI] Ошибка при запросе погоды: {e}")

#     return None

def fetch_openweathermap_data():
    """Запрашивает данные о погоде с OpenWeatherMap API по координатам."""
    if not config.OPENWEATHER_API_KEY:
        work_log.warning("[WeatherAPI] OPENWEATHER_API_KEY не установлен в settings/env.")
        return None

    url = (
        f"https://api.tomorrow.io/v4/weather/realtime?"
        f"location={config.LOCATION_LAT},{config.LOCATION_LON}"
        f"&apikey={config.OPENWEATHER_API_KEY}"
    )

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ClimatApp/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                values = data['data']['values']
                temp = float(values['temperature'])
                humi = float(values['humidity'])
                return {'temp': temp, 'humi': humi}
            else:
                work_log.error(f"[WeatherAPI] Код ответа сервера: {response.status}")
    except urllib.error.URLError as e:
        work_log.error(f"[WeatherAPI] Ошибка подключения к Tomorrow.io: {e}")
    except Exception as e:
        work_log.error(f"[WeatherAPI] Ошибка при запросе погоды: {e}")

    return None

def record_site_weather(timestamp: str = None, id: int = None):
    """Получает текущую погоду с сайта, высчитывает AH и записывает в weather_site_table."""
    weather_data = fetch_openweathermap_data()
    if not weather_data:
        work_log.warning("[WeatherAPI] Не удалось получить данные с OpenWeatherMap.")
        return None

    site_temp = weather_data['temp']
    site_humi = weather_data['humi']
    site_ah = operations.calculate_absolute_humidity(site_temp, site_humi)
    
    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data_to_write = {
        'id': id,
        'timestamp': timestamp,
        'site_temp': site_temp,
        'site_humi': site_humi,
        'site_ah': site_ah
    }

    if models.write_climate_data('weather_site_table', data_to_write):
        work_log.info(f"[WeatherAPI] Записаны данные с сайта ({timestamp}): T={site_temp}°C, RH={site_humi}%, AH={site_ah}г/м³")
        return data_to_write
    return None

def calibrate_hourly_coefficients(max_time_diff_seconds: int = 600) -> None:
    """
    Фоновый расчет часовых калибровочных коэффициентов delta_temp и delta_ah по медианам.
    Все запросы и записи к БД производятся исключительно через функции модуля models.py.
    """
    work_log.info("[Калибровка] Старт калибровки часовых коэффициентов...")
    
    rows = models.get_calibration_data(max_time_diff_seconds)
    if not rows:
        work_log.warning("[Калибровка] Данные для калибровки не найдены.")
        return

    hourly_temp_deltas = {h: [] for h in range(24)}
    hourly_ah_deltas = {h: [] for h in range(24)}

    for row in rows:
        hour = int(row['hour_val'])
        s_temp = float(row['street_temp'])
        s_humi = float(row['street_humi'])
        w_temp = float(row['site_temp'])
        w_ah = float(row['site_ah'])

        s_ah = operations.calculate_absolute_humidity(s_temp, s_humi)

        delta_t = s_temp - w_temp
        delta_ah = s_ah - w_ah

        hourly_temp_deltas[hour].append(delta_t)
        hourly_ah_deltas[hour].append(delta_ah)

    for h in range(24):
        t_list = hourly_temp_deltas[h]
        ah_list = hourly_ah_deltas[h]
        count = len(t_list)

        if count > 0:
            med_t = operations.calculate_median(t_list)
            med_ah = operations.calculate_median(ah_list)
            models.update_hourly_coefficient(h, med_t, med_ah, count)

    work_log.info("[Калибровка] Калибровка часовых коэффициентов успешно завершена.")

def get_calculated_street_climate(current_hour: int):
    """
    Рассчитывает уличный климат на основе последних данных сайта погоды и сохраненных коэффициентов.
    Возвращает: (street_temp, street_humi, sensor_or_calc_street = False)
    """
    latest_site = models.get_latest_climate_data('weather_site_table')
    if not latest_site:
        work_log.warning("[Расчет] Нет данных с сайта погоды. Возвращаются значения 0.0.")
        return 0.0, 0.0, False

    site_data = latest_site[0]
    site_temp = float(site_data['site_temp'])
    site_ah = float(site_data['site_ah'])

    coeffs = models.get_hourly_coefficient(current_hour)
    delta_temp = float(coeffs.get('delta_temp', 0.0))
    delta_ah = float(coeffs.get('delta_ah', 0.0))

    calc_temp, calc_ah, calc_rh = operations.calculate_winter_climate(
        site_temp=site_temp,
        site_ah=site_ah,
        delta_temp=delta_temp,
        delta_ah=delta_ah
    )

    work_log.info(
        f"[Расчет Зима] Час={current_hour:02d}: Сайт T={site_temp}°C, AH={site_ah}г/м³ | "
        f"dT={delta_temp}, dAH={delta_ah} -> Расчет T={calc_temp}°C, RH={calc_rh}%"
    )

    return calc_temp, calc_rh, False