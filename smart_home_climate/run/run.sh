#!/bin/bash

# bash run/run.sh

# chmod +x run.sh

######################################################### Функции #########################################################
# Функция для запроса подтверждения
ask_confirm() {
    local prompt="$1"
    while true; do
        read -p "$prompt y/n  д/н т/н так/ні: " answer
        case "$answer" in
            ([yY]|[yY][eE][sS]|[дД]|[дД][аА]|[тТ]|[так])
                return 0
                ;;
            ([nN]|[nN][oO]|[нН]|[нН][іІ]|[нН]|[ні])
                return 1
                ;;
            (*)
                echo "Пожалуйста, введите y/n  д/н т/н так/ні" >&2
                ;;
        esac
    done
}

# Универсальная функция установки пакетов
install_package() {
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
# Проверяет наличие файла и создает его, если он не существует
function check_or_create_file() {
    local file_path="$1"
    local text_in_file="$2"
    local log_dir=$(dirname "$file_path")
    
    # Сначала проверяем существование директории
    if [ ! -d "$log_dir" ]; then
        echo "✗ Директория '$log_dir' не существует - файл не может быть создан" >&2
        return 2
    fi

    # Проверяем существование файла
    if [ -f "$file_path" ]; then
        echo "✓ Файл '$file_path' существует" >&2
        return 1
    else
        echo "✗ Файл '$file_path' не найден" >&2
        if ask_confirm "Создать файл '$file_path'?"; then    
            cp $text_in_file $file_path
            echo "  > Файл '$file_path' успешно создан" >&2
            return 0
        else
            echo "  > Создание файла отменено" >&2
            return 2
        fi
    fi
}

######################################################### Начальные условия #########################################################
check_or_create_file "./run/run_data.py"
source ./run/run_data.py # Аналог import run_data

for var in PROJECT_DIR VENV_DIR VENV_NAME DATA_DIR DATA_FILE \
            desired_version STREET BASEMENT FLOOR; do
    if [ -z "${!var}" ]; then
        echo "Ошибка: Переменная $var не определена в файле run_data.sh"
        echo "Пожалуйста, проверьте файл run_data.sh и убедитесь, что все необходимые переменные определены."
        exit 1
    fi
done
#################################### Не изменяемые переменные. Используются во всём проекте ###################################################
# Путь к целевой директории для виртуального окружения
VENV_PATH="$VENV_DIR/$VENV_NAME"
# Пути для проверки .env
ENV_FILE="${PROJECT_DIR%/*}/.env"
# Пути для проверки log
LOG_DIR="$PROJECT_DIR/logs"
WORK_FILE="$LOG_DIR/work_log.log"
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

        # Этап 5: Настройка версии по умолчанию
        echo "Python $desired_version установлен."
        if ask_confirm "Сделать Python $desired_version версией по умолчанию (обновить ссылку python3)?"; then
            sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
            sudo update-alternatives --set python3 /usr/bin/python3.12
            echo "Ссылка python3 теперь ведет на версию $desired_version"
        else
            echo "Ссылка python3 не изменена. Для ручной настройки выполните:"
            echo "  sudo update-alternatives --config python3"
        fi

        # Проверка результата
        new_version=$(python3 --version 2>&1 | cut -d' ' -f2)
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
            python3 -m venv "$VENV_PATH"
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
######################################################## Проверка .env #######################################################
# Проверка файла .env (только если папка существует или была создана)
check_or_create_file "$ENV_FILE" "run/env.txt"
env_dir=$?
if [ "$env_dir" -eq 0 ]; then
    echo " " >> $ENV_FILE
    echo "STREET = '$STREET'" >> $ENV_FILE
    echo "BASEMENT = '$BASEMENT'" >> $ENV_FILE
    echo "FLOOR = '$FLOOR'" >> $ENV_FILE
    echo " " >> $ENV_FILE
    echo "DB_DIR = '$DATA_DIR'" >> $ENV_FILE
    echo "DB_NAME = '$DATA_FILE'" >> $ENV_FILE
    echo "VENV_DIR = '$VENV_DIR'" >> $ENV_FILE
    echo "VENV_NAME = '$VENV_NAME'" >> $ENV_FILE
elif [ "$env_dir" -eq 2 ]; then 
    echo "Файл .env не был создан. Пожалуйста, создайте его вручную и добавьте необходимые переменные."
    exit 1
fi

####################################################### Проверка файлы логов #######################################################
# Проверка папки logs
check_or_create_dir "$LOG_DIR" 
# Проверка файлов log (только если папка существует или была создана)
check_or_create_file "$WORK_FILE" "run/log.txt"
####################################################### Проверка базы данных #######################################################
# Проверка папки data
check_or_create_dir "$DATA_DIR" 
################################################ Делаем резервную копию run_data.py #######################################################

# Проверяем существование директории
if check_or_create_dir "$PROJECT_DIR/backup"; then    
    cp run/run_data.py $PROJECT_DIR/backup/run_data_$(date +'%Y%m%d_%H%M%S').py
    echo "Резервное копирование файла run_data.py в $PROJECT_DIR/backup/run_data_$(date +'%Y%m%d_%H%M%S').py"
    # Удаляем старые бэкапы (кроме 10 последних)
    ls -t $PROJECT_DIR/backup/run_data_*.py | tail -n +11 | xargs rm -f --
else
    echo "Не скопирован файла run_data.py нет папки $PROJECT_DIR/backup/"
fi
################################################# Запуск run_program.py #######################################################

echo "########################################### Запуск run_program.py #############################"

python3 run/run_program.py

echo "Проверка завершена."
echo "######################## Пуск основной программы проекта main.py ######################"

python3 main.py