# python3.12 settings.py  # Настройки для проекта Smart Home Climate

import os
import sys
import logging
from dotenv import load_dotenv
from run.run_data import PROJECT_DIR, DATA_DIR, DATA_FILE


# Преобразовываем путь к папке /analysis
parent_path_str = ('/'.join(os.getcwd().split('/')[:-1]))
ENV_FILE = parent_path_str + "/.env"   

# Добавляем в path путь к папке, чтобы можно было импортировать.
if parent_path_str not in sys.path:
   sys.path.insert(0, parent_path_str)

# Загрузка переменных окружения из файла  ANALYSIS_DIR/.env
load_dotenv(ENV_FILE, override=True, verbose=True)

class AppConfig:
   # Переменные из run_data, необходимые для инициализации путей
   PROJECT_DIR: str = PROJECT_DIR
   
   # APP configuration
   MODE: str = os.environ.get("MODE", "test")  # test| dev | prod | stage ...
   LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
   INTERVAL_SECONDS: int = int(os.environ.get("INTERVAL_SECONDS", "600"))
   T_FLOOR_MAC_DIFF: float = float(os.environ.get("T_FLOOR_MAC_DIFF", "4.5"))
   ABSOLUTE_HUMIDITY_TOLERANCE: float = float(os.environ.get("ABSOLUTE_HUMIDITY_TOLERANCE", "0.5"))
   MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", "5"))
   WEBSITE_RETURN_TIME: int = int(os.environ.get("WEBSITE_RETURN_TIME", "30"))
   TARGET_RH: float = float(os.environ.get("TARGET_RH", "74.0"))
   SERVER_HOST: str = os.environ.get("SERVER_HOST", "0.0.0.0")
   SERVER_PORT: int = int(os.environ.get("SERVER_PORT", "8000"))
   if MODE == "FLOOR_MAC":
      NAME_SENSOR: list = ["FLOOR_MAC", "STREET_MAC", "BASEMENT_MAC"]
      MAC_DICT: dict = {
         "STREET_MAC": os.environ.get("STREET_MAC", False),
         "BASEMENT_MAC": os.environ.get("BASEMENT_MAC", False),
         "FLOOR_MAC": os.environ.get("FLOOR_MAC", False)
          }

   else:
      NAME_SENSOR: list = ["STREET_MAC", "BASEMENT_MAC"]
      MAC_DICT: dict = {
         "STREET_MAC": os.environ.get("STREET_MAC", False),
         "BASEMENT_MAC": os.environ.get("BASEMENT_MAC", False)
      }

   def __init__(self):
      # Основные логгеры приложения
      self.work_log = self.setup_logger("work", f"{self.PROJECT_DIR}/logs/work_log.log")
      
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
      logger.propagate = False
      return logger

class DatabaseConfig:
   # Data base configuration
   DB_DIR: str = os.environ.get("DB_DIR", DATA_DIR)
   DB_NAME: str = os.environ.get("DB_NAME", DATA_FILE)
   DB_PATH: str = DB_DIR + "/" + DB_NAME


class Config(
   AppConfig,
   DatabaseConfig
   ):
   def __init__(self):
      AppConfig.__init__(self)

# Прописываем настройки для всей программы
config = Config()

## Настройка логирования для модуля Main_climat
log_project = logging.getLogger("Main_climat")  # Имя модуля по умолчанию
log_project.parent = config.work_log
work_log = config.work_log

for name in config.NAME_SENSOR:      
   if not config.MAC_DICT[name] and config.MODE == "FLOOR_MAC":
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   elif config.MODE == "TWO_SENSORS" and not config.MAC_DICT["STREET_MAC"] and not config.MAC_DICT["BASEMENT_MAC"]:
      print(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env. Значение {config.MAC_DICT[name]}")
      work_log.error(f"Ошибка: Не указан MAC-адрес для датчика {name}. Проверьте файл .env.")          
      sys.exit()
   