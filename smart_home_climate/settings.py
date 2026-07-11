# python3.12 settings.py  # Настройки для проекта Smart Home Climate

import os
import sys
from pathlib import Path
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения из файла .env
load_dotenv()

class AppConfig:

   PROJECT_DIR: str = Path.cwd()
   # APP configuration
   MODE: str = os.environ.get("MODE", "DEV")  
   LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


   def __init__(self):
      # 1. Основной лог работы приложения (климат, БД, опросы датчиков)
      self.work_log = self.setup_logger("climat_app", f"{self.PROJECT_DIR}/logs/work_log.log")
      # 2. Лог для API и веб-сервера (запросы, роуты)
      self.api_log = self.setup_logger("api_app", f"{self.PROJECT_DIR}/logs/api_log.log")
      
      # Перенаправляем стандартные логи Uvicorn в api_log.log и глушим их вывод в консоль
      if self.api_log.handlers:
         api_handler = self.api_log.handlers[0]
         for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
            u_logger = logging.getLogger(logger_name)
            u_logger.handlers = [api_handler]  # Назначаем только файловый обработчик
            u_logger.propagate = False         # Запрещаем передачу сообщений в консоль
            u_logger.setLevel(logging.INFO)
      
   def setup_logger(self, name: str, log_file: str, mode="a") -> logging.Logger:
      """Создает логгер с указанным именем и файлом"""
      logger = logging.getLogger(name)
      logger.setLevel(logging.INFO)
      
      formatter = logging.Formatter(
         "%(asctime)s:%(levelname)s:%(name)s:%(message)s",
         datefmt="%Y-%m-%d %H:%M:%S"
      )
      
      # Гарантируем наличие папки logs
      os.makedirs(os.path.dirname(log_file), exist_ok=True)
      
      handler = logging.FileHandler(log_file, mode=mode)
      handler.setFormatter(formatter)
      
      logger.addHandler(handler)
      logger.propagate = False  # Логи не дублируются в консоль Root логгера по умолчанию
      return logger
   
class BLEConfig:
   # BLE configuration
   INTERVAL_SECONDS: int = int(os.environ.get("INTERVAL_SECONDS", 300))
   MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", 5))
   TARGET_RH: float = float(os.environ.get("TARGET_RH", 74.0))
   ABSOLUTE_HUMIDITY_TOLERANCE: float = float(os.environ.get("ABSOLUTE_HUMIDITY_TOLERANCE", 0.5))
   # MAC addresses for BLE sensors
   NAME_SENSOR: list = ["FLOOR_MAC", "STREET_MAC", "BASEMENT_MAC"]
   MAC_DICT: dict = {
      "STREET_MAC": os.environ.get("STREET_MAC", False),
      "BASEMENT_MAC": os.environ.get("BASEMENT_MAC", False),
      "FLOOR_MAC": os.environ.get("FLOOR_MAC", False)
         }

class DatabaseConfig:
   # Data base configuration
   DB_DIR: str = os.environ.get("DB_DIR")
   DB_NAME: str = os.environ.get("DB_NAME")
   DB_PATH: str = DB_DIR + "/" + DB_NAME

class APIConfig:
   WEBSITE_RETURN_TIME: int = int(os.environ.get("WEBSITE_RETURN_TIME", "30"))
   SERVER_HOST: str = os.environ.get("SERVER_HOST", "0.0.0.0")
   SERVER_PORT: int = int(os.environ.get("SERVER_PORT", "8000"))

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

for name in config.NAME_SENSOR:      
   if not config.MAC_DICT[name] and config.MODE == "FLOOR":
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   elif config.MODE == "TWO_SENSORS" and not config.MAC_DICT["STREET_MAC"] and not config.MAC_DICT["BASEMENT_MAC"]:
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   elif config.MODE == "SENSORS_ONE" and not config.MAC_DICT["BASEMENT_MAC"]:
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()