import os
import sys
from pathlib import Path
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения из файла .env
load_dotenv()

class AppConfig:
   PROJECT_DIR: str = Path.cwd()
   LOG_DIR: str = os.environ.get("LOG_DIR", f"{PROJECT_DIR}/logs")
   WORK_LOG: str = os.environ.get("WORK_LOG", f"{PROJECT_DIR}/logs/work_log.log")
   API_LOG: str = os.environ.get("API_LOG", f"{PROJECT_DIR}/logs/api_log.log")
   BACKUP: str = os.environ.get("BACKUP", f"{PROJECT_DIR}/backup")
   # APP start configuration
   MODE = "BASEMENT_STREET_FLOOR"  # Есть датчик температуры пола, всего 3 датчика: у улицы, в подвале и у пола
   # MODE = "BASEMENT_STREET"  # Расчёт температуры у пола, всего 2 датчика: у улицы и в подвале
   # MODE = "BASEMENT_FLOOR"  # Расчёт температуры у пола, всего 2 датчика: в подвале и у пола
   # MODE = "BASEMENT"  # Есть датчик температуры подвала, всего 1 датчик. Данные улицы берутся с сайта погоды. 

   # Интервалов опроса в секундах
   INTERVAL_SECONDS = 300
   # Максимальное количество повторных попыток опроса датчиков
   MAX_RETRIES = 5
   # Время в секундах, через которое сайт возвращает результат
   WEBSITE_RETURN_TIME = 390
   # Физические параметры для расчетов
   T_FLOOR_MAC_DIFF = 2.5  # Разница температур между воздухом в подвале и самым холодным углом пола
   ABSOLUTE_HUMIDITY_TOLERANCE = 0.5  # Погрешность абсолютной влажности
   MINIMUM_HUMIDITY = 60  # Отличная относительная влажность у пола, плесени не будет точно
   TARGET_RH = 70.0    # Целевая относительная влажность у пола для предотвращения плесени
   DANGEROUS_HUMIDITY = 80  # ОПАСНАЯ относительная влажность у пола, рост плесени

   PRICE_GAS = 7.96 # Цена газа

   START_OF_MONTH_GAS_METER = 36766.0  # Начальное значение счетчика газа в начале месяца
   HOT_WATER_PER_HOUR = 2.5 # Расход газа в час на нагрев воды.

   def __init__(self):
      # 1. Основной лог работы приложения (климат, БД, опросы датчиков)
      self.work_log = self.setup_logger("climat_app", self.WORK_LOG)
      # 2. Лог для API и веб-сервера (запросы, роуты)
      self.api_log = self.setup_logger("api_app", self.API_LOG)
      # Перенаправляем стандартные логи Uvicorn в api_log.log и глушим их вывод в консоль
      if self.api_log.handlers:
         api_handler = self.api_log.handlers[0]
         for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
            u_logger = logging.getLogger(logger_name)
            u_logger.handlers = [api_handler]  # Назначаем только файловый обработчик
            u_logger.propagate = False         # Запрещаем передачу сообщений в консоль
            u_logger.setLevel(logging.INFO)
   
   @staticmethod
   def clean_logger_name(record: logging.LogRecord) -> bool:
      """Отрезает префикс 'climat_app.' или 'api_app.' у имени логгера"""
      if record.name.startswith(("climat_app.", "api_app.")):
         record.name = record.name.split(".")[-1]
      return True 
         
   def setup_logger(self, name: str, log_file: str, mode="a") -> logging.Logger:
      """Создает логгер с указанным именем и файлом"""
      logger = logging.getLogger(name)
      logger.setLevel(logging.INFO)
      
      formatter = logging.Formatter(
         "%(asctime)s:%(levelname)s:" + "%(name)s" + ":%(message)s",
         datefmt="%Y-%m-%d %H:%M:%S"
      )
      
      # Гарантируем наличие папки logs
      os.makedirs(os.path.dirname(log_file), exist_ok=True)
      
      handler = logging.FileHandler(log_file, mode=mode)
      handler.setFormatter(formatter)
      handler.addFilter(self.clean_logger_name)

      logger.addHandler(handler)
      logger.propagate = False  # Логи не дублируются в консоль Root логгера по умолчанию
      return logger

class BLEConfig:
   # BLE configuration
   INTERVAL_SECONDS: int = int(os.environ.get("INTERVAL_SECONDS", 300))
   MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", 5))
   # MAC addresses for BLE sensors
   NAME_SENSOR_MAC: list = ["FLOOR_MAC", "STREET_MAC", "BASEMENT_MAC"]   
   MAC_DICT: dict = {
      "STREET_MAC": os.environ.get("STREET_MAC", False),
      "BASEMENT_MAC": os.environ.get("BASEMENT_MAC", False),
      "FLOOR_MAC": os.environ.get("FLOOR_MAC", False)
   }
   sensor_name = []
   for name in NAME_SENSOR_MAC:
      sensor_name.append(name[:-4].lower())

class DatabaseConfig:
   # Data base configuration
   DB_DIR: str = os.environ.get("DB_DIR", ".")
   DB_NAME: str = os.environ.get("DB_NAME", "climate_data.sqlite3")
   DB_PATH: str = DB_DIR + "/" + DB_NAME

class APIConfig:
   WEBSITE_RETURN_TIME: int = int(os.environ.get("WEBSITE_RETURN_TIME", "30"))
   SERVER_HOST: str = os.environ.get("SERVER_HOST", "0.0.0.0")
   SERVER_PORT: int = int(os.environ.get("SERVER_PORT", "8000"))

   # Настройки OpenWeatherMap API
   SITE_WEATHER_API_KEY: str = os.environ.get("SITE_WEATHER_API_KEY", "")

   LOCATION_LAT: float = float(os.environ.get("LOCATION_LAT", 50.4501))
   LOCATION_LON: float = float(os.environ.get("LOCATION_LON", 30.5234))
   # Флаг активности уличного физического датчика (True - включен, False - зимовка/расчет)

class Config(
   AppConfig,
   DatabaseConfig,
   BLEConfig,
   APIConfig
   ):
   def __init__(self):
      AppConfig.__init__(self)
      DatabaseConfig.__init__(self)
      BLEConfig.__init__(self)
      APIConfig.__init__(self)

# Прописываем настройки для всей программы
config = Config()

# Логгер для самого модуля settings (дочерний от climat_app)
work_log = logging.getLogger("climat_app.settings")

for name in config.NAME_SENSOR_MAC:      
   if not config.MAC_DICT[name] and config.MODE == "BASEMENT_STREET_FLOOR":
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   elif config.MODE == "BASEMENT_STREET" and not config.MAC_DICT["STREET_MAC"] and not config.MAC_DICT["BASEMENT_MAC"]:
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   elif config.MODE == "BASEMENT" and not config.MAC_DICT["BASEMENT_MAC"]:
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()