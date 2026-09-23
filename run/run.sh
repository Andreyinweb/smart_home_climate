#!/bin/bash

# bash run/run.sh /home/andrey/andrey_folder/New_Indoor_climate/In_server/.env

# chmod +x run.sh
################################################ Переменные #########################################################
DIR_PATH="$PWD"
# Обязательно указываем путь к файлу .env или настроек.
if [ -n "$1" ]; then
    ENV_FILE="$1"
else
    ENV_FILE="$DIR_PATH/.env"
fi

######################################################### Функции #########################################################
# Функция для запроса подтверждения
function ask_confirm() {
    local prompt="$1"
    while true; do
        read -p "$prompt y/n: " answer
        case "$answer" in
            ([yY]|[yY][eE][sS])
                return 0
                ;;
            ([nN]|[nN][oO])
                return 1
                ;;
            (*)
                echo "Пожалуйста, введите y/n" >&2
                ;;
        esac
    done
}

# Универсальная функция установки пакетов
function install_package() {
    local package_name="$1"
    local test_command="$2"
    local install_command="sudo apt install -y $package_name"
    
    # Проверка, установлен ли уже пакет
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
            # Повторная проверка после установки
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

                # Пример использования для других пакетов:
                # install_package "curl" "curl --version"
                # install_package "git" "git --version"
}

# Проверяет наличие папаки и создает ее, если она не существует
function check_or_create_dir() {
    local dir_path="$1"
    
    # Проверяем существование директории
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

# Проверяет наличие файла и создает его, если он не существует (если не включен режим "только проверка")
function check_or_create_file() {
    local file_path="$1"
    local text_in_file="$2"
    local mode="$3" # "check_only", файл создаваться не будет
    local log_dir=$(dirname "$file_path")
    
    # Коды возврата (Exit Status) функции check_or_create_file:
    # 0 — Успех: файл уже существует
    # 1 — Успех: файла не было, но он был успешно создан
    # 2 — Файла нет и он не создан (режим check_only или отказ пользователя)
    # 3 — Ошибка: отсутствует директория или нет прав на создание
    
    # Сначала проверяем существование директории
    if [ ! -d "$log_dir" ]; then
        echo "✗ Директория '$log_dir' не существует — файл не может быть создан" >&2
        return 3
    fi

    # Проверяем существование файла
    if [ -f "$file_path" ]; then
        echo "✓ Файл '$file_path' существует" >&2
        return 0
    else
        echo "✗ Файл '$file_path' не найден" >&2
        
        # ЕСЛИ включен режим "только проверка", сразу выходим без создания
        if [ "$mode" = "check_only" ]; then
            echo "  > Режим проверки: создание файла пропущено" >&2
            return 2
        fi

        # Иначе — обычная логика создания
        if ask_confirm "Создать файл '$file_path'?"; then    
            if [ -n "$text_in_file" ] && [ -f "$text_in_file" ]; then
                cp "$text_in_file" "$file_path"
            else
                touch "$file_path"
            fi
            echo "  > Файл '$file_path' успешно создан" >&2
            return 1
        else
            echo "  > Создание файла отменено" >&2
            return 2
        fi
    fi
}

function loading_variables() {
    local config_file="$1"
    local is_required=true
    local missing=()
    local line name val

    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*#.*# ]] && is_required=false
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue

        if [[ "$line" == *=* ]]; then
            name="${line%%=*}"
            val="${line#*=}"
            
            # Строго в кавычках и с обычным символом '|'
            name=$(echo "$name" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            val=$(echo "$val" | sed -E "s/#.*//; s/^[[:space:]]*//; s/[[:space:]]*$//; s/^['\"]|['\"]$//g")

            if [ "$is_required" = true ] && [ -z "$val" ]; then
                missing+=("$name")
            fi
            
            # -g объявляет переменную в глобальном окружении скрипта
            declare -g "$name=$val"
        fi
    done < "$config_file"

    if [ ${#missing[@]} -ne 0 ]; then
        echo "❌ Не заполнены обязательные переменные: ${missing[*]}. Пожалуйста, заполните их в $config_file и перезапустите скрипт." >&2
        return 2
    fi
}


######################################################### Начальные условия ##################################################


# Коды возврата (Exit Status) функции check_or_create_file:
# 0 — Успех: файл уже существует
# 1 — Успех: файла не было, но он был успешно создан
# 2 — Файла нет и он не создан (режим check_only или отказ пользователя)
# 3 — Ошибка: отсутствует директория или нет прав на создание

check_or_create_file "$ENV_FILE" #"./run/env.txt"
if [ $? == 0 ]; then 
    loading_variables "$ENV_FILE"
    if [ $? == 2 ]; then
        echo "Файл .env не заполнен основные переменные. Будет перезаписан" 
        CONFIGURATION_FILE="./run/env.txt"

    else
        # Проверка соответствия PROJECT_DIR текущей директории
        if [ "$PROJECT_DIR" == "$DIR_PATH" ]; then
            # Если PROJECT_DIR совпадает с текущей директорией, используем файл .env
            CONFIGURATION_FILE="$ENV_FILE" 

        elif [ "$PROJECT_DIR" != "$DIR_PATH" ]; then
            # Если PROJECT_DIR не совпадает с текущей директорией, выводим предупреждение и предлагаем варианты действий
            echo "В .env указана переменная PROJECT_DIR = '$PROJECT_DIR', но текущая директория '$DIR_PATH'."
            if ask_confirm "Есть основные данные, но пути можем переписать по умолчанию? !!!!! БЕЗ env.txt ФАЙЛА"; then
                # Перезаписываем не основные переменные по умолчанию без env.txt файла
                CONFIGURATION_FILE="$ENV_FILE"           
            else
                if ask_confirm "!!!!!!!!!!  Переписать файл .env? !! ОН БУДЕТ УДАЛЁН И ЗАПИСАН ЗАНОВО !!"; then
                    # Удаляет файл .env и создает новый с настройками по умолчанию из env.txt
                    rm "$ENV_FILE"
                    CONFIGURATION_FILE="./run/env.txt"
                    check_or_create_file "$ENV_FILE" "run/env.txt"
                    if [ $? !=2 ]; then
                        echo "НУЖЕН ФАЙЛ НАСТРОЕК .env. Завершение работы. ПЕРЕЗАПУСТИ ." 
                        exit 2
                    fi

                else
                    echo "НУЖЕН ФАЙЛ НАСТРОЕК .env. Завершение работы. ПЕРЕЗАПУСТИ ." 
                    exit 2
                fi
            fi
        fi
    fi
else
    CONFIGURATION_FILE="./run/env.txt"
fi


check_or_create_file "$CONFIGURATION_FILE" "" "check_only"
if [ $? != 0 ]; then
    echo "Файл конфигурации $CONFIGURATION_FILE не найден. Перезапустите программу и и проверте наличие run/env.txt "
    exit 1
fi

loading_variables "$CONFIGURATION_FILE"

############################################### Проверка переменных окружения #######################################################
if [ -z "$LOCATION_LAT" ]; then
    LOCATION_LAT='50.4501'
fi
if [ -z "$LOCATION_LON" ]; then
    LOCATION_LON='30.5234'
fi
if [ -z "$DB_DIR" ]; then
    DB_DIR="$DIR_PATH"
fi
if [ -z "$DB_NAME" ]; then
    DB_NAME='climate_data.sqlite3'
fi
if [ -z "$VENV_DIR" ]; then
    VENV_DIR="$DIR_PATH/venv"
fi
if [ -z "$VENV_NAME" ]; then
    VENV_NAME='venv_smart_home_climate'
fi
if [ -z "$LOG_DIR" ]; then
    LOG_DIR="$DIR_PATH/logs"
fi
if [ -z "$WORK_LOG" ]; then
    WORK_LOG="$LOG_DIR/work_log.log"
fi
if [ -z "$API_LOG" ]; then
    API_LOG="$LOG_DIR/api_log.log"
fi
if [ -z "$BACKUP" ]; then
    BACKUP="$DIR_PATH/backup"
fi
if [ -z "$SERVER_HOST" ]; then
    SERVER_HOST='0.0.0.0'
fi
if [ -z "$SERVER_PORT" ]; then
    SERVER_PORT='8000'
fi
if [ -z "$PYTHON_VERSION" ]; then
    PYTHON_VERSION='3.12'
fi

if [ -z "$SITE_WEATHER" ]; then
    SITE_WEATHER='OPENWEATHERMAP'
fi


PROJECT_DIR="$DIR_PATH"

######################################################## Проверка .env #######################################################
# Запись файла .env
cat << EOF > "$ENV_FILE"
# ОБЯЗАТЕЛЬНО дописать
VERSION = '${VERSION}'

# ОБЯЗАТЕЛЬНО дописать макадреса датчиков:  
STREET_MAC = '${STREET_MAC}'  # Улица
BASEMENT_MAC = '${BASEMENT_MAC}'  # Подвал
FLOOR_MAC = '${FLOOR_MAC}'   # Пол

# ОБЯЗАТЕЛЬНО хотя бы один ключ с сайта погоды:
OPENWEATHERMAP_API_KEY = '${OPENWEATHERMAP_API_KEY}'
TOMORROW_API_KEY = '${TOMORROW_API_KEY}' 

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

# Местоположение проекта, для теста файла env
PROJECT_DIR = '${PROJECT_DIR}'
EOF

#################################### Не изменяемые переменные. Используются во всём проекте ###################################################
# Путь к целевой директории для виртуального окружения
VENV_PATH="$VENV_DIR/$VENV_NAME"
# Пути для проверки log
LOG_DIR="$PROJECT_DIR/logs"
WORK_LOG="$LOG_DIR/work_log.log"
API_LOG="$LOG_DIR/api_log.log"
#################################################################################### Проверка Python #########################################################

# Проверяем текущую версию Python
current_version=$(python3 --version 2>&1 | cut -d' ' -f2)


if [[ "$current_version" == *"$desired_version"* ]]; then
    echo "Python $desired_version уже установлен (текущая версия: $current_version)"
else
    echo "Обнаружена версия Python: $current_version"
    echo "Хотите установить Python $desired_version?"

    if ! ask_confirm "Продолжить установку?"; then
        echo "Установка Python $desired_version отменена пользователем."
    else

        # Этап 1: Обновление пакетов
        echo "Для установки потребуется обновить список пакетов."
        if ask_confirm "Выполнить apt-get update?"; then
            sudo apt-get update
        else
            echo "Пропуск обновления пакетов (может повлиять на установку)."
        fi

        # Этап 2: Установка зависимостей
        echo "Необходимо установить вспомогательные пакеты."
        if ask_confirm "Установить software-properties-common?"; then
            sudo apt-get install -y software-properties-common
        else
            echo "Пропуск установки зависимостей (может вызвать ошибки)."
        fi

        # Этап 3: Добавление PPA
        echo "Для установки Python $desired_version нужно добавить репозиторий deadsnakes."
        if ask_confirm "Добавить ppa:deadsnakes/ppa?"; then
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update
        else
            echo "Пропуск добавления PPA. Установка невозможна."
            exit 1
        fi

        # Этап 4: Основная установка
        echo "Готов к установке Python $desired_version."
        if ask_confirm "Установить python3.12?"; then
            sudo apt-get install -y python3.12
        else
            echo "Установка отменена."
            exit 0
        fi


        # Проверка результата
        new_version=$(python3.12 --version 2>&1 | cut -d' ' -f2)
        echo "Установка завершена. Текущая версия Python: $new_version"
    fi
fi
####################################################### Проверка и установка пакетов #######################################################
# Проверка и установка pip3
install_package "python3-pip" "pip3 --version"
# Проверка и установка python3-venv
install_package "python3-venv python3-dev" "python3 -m venv --help"
####################################################### Создание виртуального окружения #######################################################
# Проверяем существование директории
check_or_create_dir "$VENV_DIR" 
# Проверяем существование виртуального окружения
if [ -d "$VENV_DIR" ]; then
    if [ ! -d "$VENV_PATH" ]; then
        echo "Виртуальное окружение $VENV_NAME не существует."
        if ask_confirm "Создать виртуальное окружение  $VENV_NAME ?"; then
            python3.12 -m venv "$VENV_PATH"
            echo "Виртуальное окружение успешно создано в $VENV_PATH"
            
            # Активируем и устанавливаем базовые пакеты (опционально)
            echo "Активируем окружение и устанавливаем базовые пакеты..."
            source "$VENV_PATH/bin/activate"
            pip3 install -r requirements.txt
            # deactivate
        else
            echo "Виртуальное окружение не создано пользователем: $VENV_PATH"
        fi
    else
        echo "Виртуальное окружение $VENV_NAME уже существует в $VENV_DIR"
    fi
else
    echo "Виртуальное окружениел не проверялось - папка '$VENV_DIR' отсутствует"
fi


####################################################### Проверка файлы логов #######################################################
# Проверка папки logs
check_or_create_dir "$LOG_DIR" 
# Проверка файлов log (только если папка существует или была создана) 
check_or_create_file "$WORK_LOG" "run/log.txt"
check_or_create_file "$API_LOG" "run/log.txt"
####################################################### Проверка базы данных #######################################################
# Проверка папки data
check_or_create_dir "$DB_DIR" 
################################################ Делаем резервную копию run_data.py #######################################################

# Проверяем существование директории backup
check_or_create_dir "$PROJECT_DIR/backup"
################################################# Запуск run_program.py #######################################################

echo "########################################### Запуск run_program.py #############################"
source "$VENV_PATH/bin/activate"
python3.12 run/run_program.py

echo "Проверка завершена."
# TODO удали
# exit
echo "########################################### Запуск run_migrator.py #############################"

python3.12 run/migrator.py

echo "######################## Пуск основной программы проекта main.py ######################"

# python3.12 app/main.py
python3.12 -m app.main
