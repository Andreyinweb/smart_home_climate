# Файл с переменными для запуска скрипта run.sh
# Дополнительные настройки находятся в файле run.sh Начальные условия
# Переменные надо писать чтобы их пог прочитать и bash и python

PROJECT_DIR='/home/andrey/andrey_folder/Indoor_climate/smart_home_climate'
# Путь к целевой директории для виртуального окружения 
VENV_DIR="/home/venv" #  "/home/venv" #   Обязательно указать свою 
VENV_NAME="venv_climate" # Имя виртуального окружения
# Пути для проверки базы данных
DATA_DIR="/home/base" # Папка для хранения базы данных
DATA_FILE="climate_data.sqlite3"
# Версия Python, которую нужно установить
desired_version="3.12"
# Нужно дописать макадреса
BASEMENT_MAC=
STREET_MAC=
FLOOR_MAC= 