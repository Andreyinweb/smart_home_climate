#!/usr/bin/env bash

# /run/run.sh

set -eo pipefail

DIR_PATH="$PWD"
SERVER_MODE=false
CONFIG_FILE=""

echo "СТАРТ run sh"

# Разбор аргументов командной строки
for arg in "$@"; do
    if [ "$arg" = "-server" ]; then
        SERVER_MODE=true
    elif [ -z "$CONFIG_FILE" ] && [ "$arg" != "-server" ]; then
        CONFIG_FILE="$arg"
    fi
done

if [ "$SERVER_MODE" = true ]; then
    ENV_FILE="/etc/smart_home_climate/config.env"
else
    if [ -n "$CONFIG_FILE" ]; then
        ENV_FILE="$CONFIG_FILE"
    else
        ENV_FILE="$DIR_PATH/.env"
    fi
fi

# Определение интерактивности режима
if [ ! -t 0 ] || [ "${NON_INTERACTIVE:-false}" = "true" ] || [ "$SERVER_MODE" = true ]; then
    IS_INTERACTIVE=false
else
    IS_INTERACTIVE=true
fi

# Функция подтверждения операций
ask_confirm() {
    local prompt_msg="$1"

    if [ "$IS_INTERACTIVE" = false ]; then
        return 0
    fi

    local response
    while true; do
        read -p "$prompt_msg [y/N]: " response
        case "$response" in
            [yY][eE][sS]|[yY])
                return 0
                ;;
            [nN][oO]|[nN])
                return 1
                ;;
            *)
                echo "Пожалуйста, введите y/n" >&2
                ;;
        esac
    done
}

# Функция установки системных пакетов
install_package() {
    local package_name="$1"
    local test_command="$2"
    local install_command="sudo apt install -y $package_name"
    
    if eval "$test_command" &>/dev/null; then
        echo "✅ Пакет '$package_name' уже установлен"
        return 0
    fi
    
    echo "❌ Пакет '$package_name' не установлен"
    if ask_confirm "Установить пакет '$package_name'?"; then
        echo "🔄 Обновление кэша пакетов..."
        sudo apt update -q
        
        echo "⚙️ Устанавливаю $package_name..."
        if eval "$install_command"; then
            if eval "$test_command" &>/dev/null; then
                echo "✅ Пакет '$package_name' успешно установлен"
                return 0
            else
                echo "❌ Пакет '$package_name' установлен, но проверка не пройдена!" >&2
                return 1
            fi
        else
            echo "❌ Ошибка установки пакета '$package_name'!" >&2
            return 1
        fi
    else
        echo "❌ Установка '$package_name' отменена пользователем"
        return 1
    fi
}

# Проверка и создание директории
check_or_create_dir() {
    local dir_path="$1"
    
    if [ ! -d "$dir_path" ]; then
        echo "Директория $dir_path не существует."
        if ask_confirm "Создать папку $dir_path ?"; then
            mkdir -p "$dir_path"
            echo "Директория $dir_path успешно создана." >&2
            return 0
        else
            echo "Создание $dir_path директории отменено." >&2
            return 1
        fi
    else
        echo "Директория $dir_path уже существует." >&2
        return 0
    fi
}

# Проверка и создание файла
check_or_create_file() {
    local file_path="$1"
    local text_in_file="$2"
    local mode="$3" # "check_only"
    local log_dir
    log_dir=$(dirname "$file_path")
    
    if [ ! -d "$log_dir" ]; then
        echo "✗ Директория '$log_dir' не существует — файл не может быть создан" >&2
        return 1
    fi

    if [ -f "$file_path" ]; then
        echo "✓ Файл '$file_path' существует" >&2
        return 0
    else
        echo "✗ Файл '$file_path' не найден" >&2
        
        if [ "$mode" = "check_only" ]; then
            echo "  > Режим проверки: создание файла пропущено" >&2
            return 1
        fi

        if ask_confirm "Создать файл '$file_path'?"; then    
            if [ -n "$text_in_file" ] && [ -f "$text_in_file" ]; then
                cp "$text_in_file" "$file_path"
            else
                touch "$file_path"
            fi
            echo "  > Файл '$file_path' успешно создан" >&2
            return 0
        else
            echo "  > Создание файла отменено" >&2
            return 1
        fi
    fi
}

# Загрузка и экспорт переменных окружения из конфига
loading_variables() {
    local config_file="$1"
    local is_required=true
    local missing=()
    local line name val

    if [ ! -f "$config_file" ]; then
        echo "❌ Конфигурационный файл $config_file не найден!" >&2
        return 1
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*#.*# ]] && is_required=false
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue

        if [[ "$line" == *=* ]]; then
            name="${line%%=*}"
            val="${line#*=}"
            
            name=$(echo "$name" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            val=$(echo "$val" | sed -E "s/#.*//; s/^[[:space:]]*//; s/[[:space:]]*$//; s/^['\"]|['\"]$//g")

            if [ "$is_required" = true ] && [ -z "$val" ]; then
                missing+=("$name")
            fi
            
            declare -g "$name=$val"
            export "$name=$val"
        fi
    done < "$config_file"

    if [ ${#missing[@]} -ne 0 ]; then
        echo "❌ Не заполнены обязательные переменные: ${missing[*]}. Пожалуйста, заполните их в $config_file и перезапустите скрипт." >&2
        return 1
    fi
}

######################################################### Загрузка конфигурации ##################################################

if [ "$SERVER_MODE" = true ]; then
    if [ -f "$ENV_FILE" ]; then
        loading_variables "$ENV_FILE"
    else
        echo "❌ Ошибка: Серверный конфигурационный файл $ENV_FILE не найден!" >&2
        exit 1
    fi
else
    if check_or_create_file "$ENV_FILE"; then 
        if ! loading_variables "$ENV_FILE"; then
            echo "Файл .env не содержит основные переменные. Будет перезаписан из run/env.txt" 
            CONFIGURATION_FILE="./run/env.txt"
        else
            if [ "${PROJECT_DIR:-}" = "$DIR_PATH" ]; then
                CONFIGURATION_FILE="$ENV_FILE" 
            else
                echo "В .env указана переменная PROJECT_DIR = '${PROJECT_DIR:-}', но текущая директория '$DIR_PATH'."
                if ask_confirm "Есть основные данные, но пути можем переписать по умолчанию?"; then
                    CONFIGURATION_FILE="$ENV_FILE"           
                else
                    if ask_confirm "Переписать файл .env? ОН БУДЕТ УДАЛЁН И ЗАПИСАН ЗАНОВО!"; then
                        rm -f "$ENV_FILE"
                        CONFIGURATION_FILE="./run/env.txt"
                        check_or_create_file "$ENV_FILE" "run/env.txt" || true
                    else
                        echo "НУЖЕН ФАЙЛ НАСТРОЕК .env. Завершение работы." 
                        exit 2
                    fi
                fi
            fi
        fi
    else
        CONFIGURATION_FILE="./run/env.txt"
    fi

    if ! check_or_create_file "$CONFIGURATION_FILE" "" "check_only"; then
        echo "Файл конфигурации $CONFIGURATION_FILE не найден. Проверьте наличие run/env.txt"
        exit 1
    fi

    loading_variables "$CONFIGURATION_FILE"
fi

############################################### Значения по умолчанию #######################################################
LOCATION_LAT="${LOCATION_LAT:-50.4501}"
LOCATION_LON="${LOCATION_LON:-30.5234}"
DB_DIR="${DB_DIR:-$DIR_PATH}"
DB_NAME="${DB_NAME:-climate_data.sqlite3}"
VENV_DIR="${VENV_DIR:-$DIR_PATH/venv}"
VENV_NAME="${VENV_NAME:-venv_smart_home_climate}"
LOG_DIR="${LOG_DIR:-$DIR_PATH/logs}"
WORK_LOG="${WORK_LOG:-$LOG_DIR/work_log.log}"
API_LOG="${API_LOG:-$LOG_DIR/api_log.log}"
BACKUP="${BACKUP:-$DIR_PATH/backup}"
SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
SERVER_PORT="${SERVER_PORT:-8000}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
SITE_WEATHER="${SITE_WEATHER:-OPENWEATHERMAP}"
APP_ENV="${APP_ENV:-DEVELOPMENT}"
PROJECT_DIR="$DIR_PATH"

export DB_DIR DB_NAME BACKUP LOG_DIR WORK_LOG API_LOG SERVER_HOST SERVER_PORT PROJECT_DIR APP_ENV LOCATION_LAT LOCATION_LON SITE_WEATHER APP_ENV VENV_DIR VENV_NAME PYTHON_VERSION

######################################################## Перезапись .env (только Dev) #######################################################
if [ "$SERVER_MODE" = false ]; then
cat << EOF > "$ENV_FILE"
# ОБЯЗАТЕЛЬНО дописать
VERSION = '${VERSION:-2.0.0}'

# ОБЯЗАТЕЛЬНО дописать макадреса датчиков:  
STREET_MAC = '${STREET_MAC:-}'  # Улица
BASEMENT_MAC = '${BASEMENT_MAC:-}'  # Подвал
FLOOR_MAC = '${FLOOR_MAC:-}'   # Пол

# ОБЯЗАТЕЛЬНО хотя бы один ключ с сайта погоды:
OPENWEATHERMAP_API_KEY = '${OPENWEATHERMAP_API_KEY:-}'
TOMORROW_API_KEY = '${TOMORROW_API_KEY:-}' 

########################## Не обязательные переменные  ########################################
# Сайт погоды
SITE_WEATHER = '${SITE_WEATHER}'

# Координаты города для сайта погоды:
LOCATION_LAT = '${LOCATION_LAT}'
LOCATION_LON = '${LOCATION_LON}'

# База данных
DB_DIR = '${DB_DIR}'
DB_NAME = '${DB_NAME}'

# Виртуальное окружение
VENV_DIR = '${VENV_DIR}'
VENV_NAME = '${VENV_NAME}'

# Логи папка, файлы.
LOG_DIR = '${LOG_DIR}'
WORK_LOG = '${WORK_LOG}'
API_LOG = '${API_LOG}'

# Папка сохранения backup базы данных
BACKUP = '${BACKUP}'

# Параметры запуска веб-сервера
SERVER_HOST = "${SERVER_HOST}"
SERVER_PORT = ${SERVER_PORT}

# Версия Python, которую нужно установить
PYTHON_VERSION = '${PYTHON_VERSION}'

# Режимы приложения и железа
APP_ENV = '${APP_ENV}'

# Местоположение проекта, для теста файла env
PROJECT_DIR = '${PROJECT_DIR}'
EOF
fi

#################################### Путь к venv ###################################################
VENV_PATH="$VENV_DIR/$VENV_NAME"

#################################################################################### Проверка Python 3.12 #########################################################
if command -v python3.12 &>/dev/null; then
    echo "✅ Python 3.12 уже установлен."
else
    echo "❌ Python 3.12 не найден."
    if ask_confirm "Установить Python 3.12?"; then
        sudo apt-get update
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update
        sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
    else
        echo "Отмена установки Python 3.12."
        exit 1
    fi
fi

####################################################### Проверка пакетов #######################################################
install_package "python3-pip" "pip3 --version"
install_package "python3-venv python3-dev" "python3.12 -m venv --help"

####################################################### Виртуальное окружение #######################################################
check_or_create_dir "$VENV_DIR" 
if [ -d "$VENV_DIR" ]; then
    if [ ! -d "$VENV_PATH" ]; then
        echo "Виртуальное окружение $VENV_NAME не существует."
        if ask_confirm "Создать виртуальное окружение $VENV_NAME ?"; then
            python3.12 -m venv "$VENV_PATH"
            echo "Виртуальное окружение успешно создано в $VENV_PATH"
            source "$VENV_PATH/bin/activate"
            if [ -f "requirements.txt" ]; then
                pip install -r requirements.txt
            fi
        else
            echo "Виртуальное окружение не создано."
        fi
    else
        echo "Виртуальное окружение $VENV_NAME уже существует в $VENV_DIR"
    fi
fi

####################################################### Папки и файлы логов/БД #######################################################
check_or_create_dir "$LOG_DIR" 
check_or_create_file "$WORK_LOG" "run/log.txt"
check_or_create_file "$API_LOG" "run/log.txt"
check_or_create_dir "$DB_DIR" 
check_or_create_dir "$BACKUP"

################################################# Запуск приложения #######################################################
if [ -f "$VENV_PATH/bin/activate" ]; then
    source "$VENV_PATH/bin/activate"
fi

echo "########################################### Запуск run_program.py #############################"
python3.12 run/run_program.py

echo "########################################### Запуск run_migrator.py #############################"
python3.12 run/migrator.py

echo "######################## Пуск основной программы проекта main.py ######################"
python3.12 -m app.main