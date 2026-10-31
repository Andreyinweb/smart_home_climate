#!/usr/bin/env bash

# run/run.sh
#
# Источники настроек (по порядку): окружение → .env → run/env.txt (из него создаётся .env) → иначе СТОП.
# Обязательные переменные = имена из run/env.txt ДО строки-разделителя «##########…».
#
# Автоматический режим (сервер): в окружении есть VERSION и ещё хотя бы одна обязательная переменная.
#   Все вопросы получают «да», .env существующий не трогается, python/pip не ставятся (вместо этого стоп).
# Обычный режим (разработка): любое действие только с согласия в терминале.
#   Нет терминала — на вопросы отвечается «нет».

set -Eeo pipefail

# Исходные потоки: 3 = stdout, 4 = stderr (терминал), 5 = stdin
exec 3>&1 4>&2 5<&0

DIR_PATH="$PWD"
ENV_FILE="$DIR_PATH/.env"
ENV_TXT="$DIR_PATH/run/env.txt"
SEP_LINE='########################## Не обязательные переменные  ########################################'
RE_SEP='^[[:space:]]*#{10,}'

#################################### Журнал ####################################
# До загрузки конфигурации LOG_DIR неизвестен, поэтому сообщения копятся в LOG_BUF
# и сбрасываются в run_log.log сразу после его открытия.
LOG_READY=false
LOG_BUF=""

note() {
    local ts
    printf -v ts '%(%Y-%m-%d %H:%M:%S)T' -1
    if [ "$LOG_READY" = true ]; then
        printf '%s: %s\n' "$ts" "$*" >> "$RUN_LOG"
    else
        LOG_BUF+="$ts: $*"$'\n'
    fi
}

open_log() {
    RUN_LOG="${RUN_LOG:-${LOG_DIR:-$DIR_PATH/logs}/run_log.log}"
    mkdir -p -- "${RUN_LOG%/*}" 2>/dev/null || return 1
    printf '%s' "$LOG_BUF" >> "$RUN_LOG" 2>/dev/null || return 1
    LOG_BUF=""
    LOG_READY=true
}

# Ошибка: в терминал (fd 4) и в журнал, затем стоп
die() {
    echo "❌ $*" >&4
    note "❌ $*"
    if [ "$LOG_READY" != true ]; then open_log || true; fi
    exit 1
}

trap 'rc=$?; note "❌ Ошибка (код $rc), строка $LINENO: $BASH_COMMAND"; echo "❌ run.sh: ошибка (код $rc), строка $LINENO. Подробности: ${RUN_LOG:-журнал не открыт}" >&4' ERR

#################################### Вопросы и действия ####################################
AUTO=false

ask_confirm() {
    local prompt="$1" answer="" use_tty=false
    if [ "$AUTO" = true ]; then
        note "АВТО: «$prompt» → да"
        return 0
    fi
    if ( : </dev/tty ) 2>/dev/null; then
        use_tty=true
    elif [ ! -t 5 ]; then
        note "Нет терминала: «$prompt» → нет"
        return 1
    fi
    while true; do
        if [ "$use_tty" = true ]; then
            printf '%s [y/N]: ' "$prompt" > /dev/tty
            read -r answer < /dev/tty || return 1
        else
            printf '%s [y/N]: ' "$prompt" >&3
            read -r answer <&5 || return 1
        fi
        case "$answer" in
            [yY]|[yY][eE][sS]) return 0 ;;
            [nN]|[nN][oO]|"")  return 1 ;;
            *)
                if [ "$use_tty" = true ]; then echo "Пожалуйста, введите y/n" > /dev/tty
                else echo "Пожалуйста, введите y/n" >&3; fi
                ;;
        esac
    done
}

install_package() {
    local package_name="$1" test_command="$2"
    if eval "$test_command" &>/dev/null; then
        echo "✅ Пакет '$package_name' уже установлен"
        return 0
    fi
    echo "❌ Пакет '$package_name' не установлен"
    if [ "$AUTO" = true ]; then
        die "Не установлен пакет '$package_name'. В автоматическом режиме пакеты не ставятся."
    fi
    ask_confirm "Установить пакет '$package_name'?" || { echo "❌ Установка '$package_name' отменена"; return 1; }
    echo "🔄 Обновление кэша пакетов..."
    sudo apt update -q || return 1
    echo "⚙️ Устанавливаю $package_name..."
    # shellcheck disable=SC2086
    sudo apt install -y $package_name || { echo "❌ Ошибка установки пакета '$package_name'!" >&2; return 1; }
    eval "$test_command" &>/dev/null || { echo "❌ Пакет '$package_name' установлен, но проверка не пройдена!" >&2; return 1; }
    echo "✅ Пакет '$package_name' успешно установлен"
}

check_or_create_dir() {
    local dir_path="$1"
    if [ -d "$dir_path" ]; then
        echo "Директория $dir_path уже существует."
        return 0
    fi
    echo "Директория $dir_path не существует."
    if ask_confirm "Создать папку $dir_path ?"; then
        mkdir -p -- "$dir_path" || return 1
        echo "Директория $dir_path успешно создана."
        return 0
    fi
    echo "Создание $dir_path отменено."
    return 1
}

check_or_create_file() {
    local file_path="$1" template="$2"
    if [ ! -d "${file_path%/*}" ]; then
        echo "✗ Директория '${file_path%/*}' не существует — файл не может быть создан"
        return 1
    fi
    if [ -f "$file_path" ]; then
        echo "✓ Файл '$file_path' существует"
        return 0
    fi
    echo "✗ Файл '$file_path' не найден"
    if ask_confirm "Создать файл '$file_path'?"; then
        if [ -n "$template" ] && [ -f "$template" ]; then
            cp -- "$template" "$file_path" || return 1
        else
            : > "$file_path" || return 1
        fi
        echo "  > Файл '$file_path' успешно создан"
        return 0
    fi
    echo "  > Создание файла отменено"
    return 1
}

#################################### Разбор env-файлов ####################################
# Строка вида:  NAME = 'value'  # комментарий   →  P_NAME, P_VAL, P_TAIL (хвост с комментарием)
P_NAME="" P_VAL="" P_TAIL=""
parse_assign() {
    local line="${1%$'\r'}" rest q="'"
    local re_name='^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$'
    local re_sq="^[[:space:]]*${q}([^${q}]*)${q}(.*)$"
    local re_dq='^[[:space:]]*"([^"]*)"(.*)$'
    [[ $line =~ $re_name ]] || return 1
    P_NAME="${BASH_REMATCH[1]}"
    rest="${BASH_REMATCH[2]}"
    if [[ $rest =~ $re_sq ]] || [[ $rest =~ $re_dq ]]; then
        P_VAL="${BASH_REMATCH[1]}"
        P_TAIL="${BASH_REMATCH[2]}"
    else
        P_TAIL=""
        if [[ $rest == *"#"* ]]; then
            P_TAIL="  #${rest#*#}"
            rest="${rest%%#*}"
        fi
        rest="${rest#"${rest%%[![:space:]]*}"}"
        rest="${rest%"${rest##*[![:space:]]}"}"
        P_VAL="$rest"
    fi
    return 0
}

declare -A TXT_VAL=() ENVF_VAL=() FINAL=() IS_OPT=()
REQ_NAMES=()

# env.txt: имена до разделителя — обязательные; значения запоминаем все
load_env_txt() {
    local line in_req=true
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ $line =~ $RE_SEP ]]; then in_req=false; continue; fi
        parse_assign "$line" || continue
        if [ "$in_req" = true ]; then REQ_NAMES+=("$P_NAME"); fi
        TXT_VAL["$P_NAME"]="$P_VAL"
    done < "$ENV_TXT"
}

load_envf() {
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        parse_assign "$line" || continue
        ENVF_VAL["$P_NAME"]="$P_VAL"
    done < "$ENV_FILE"
}

#################################### Необязательные переменные и значения по умолчанию ####################################
# Строки на «#» — комментарии для .env, остальные — имена переменных (порядок = порядок в .env)
OPT_SPEC=(
    "# Сайт погоды (OPENWEATHERMAP или TOMORROW)"
    SITE_WEATHER
    "# Координаты города для сайта погоды:"
    LOCATION_LAT LOCATION_LON
    "# База данных (имя = версия + climate_data.sqlite3, считается из VERSION)"
    DB_DIR DB_NAME
    "# Виртуальное окружение"
    VENV_DIR VENV_NAME
    "# Логи папка, файлы."
    LOG_DIR WORK_LOG API_LOG
    "# Папка сохранения backup базы данных"
    BACKUP
    "# Параметры запуска веб-сервера"
    SERVER_HOST SERVER_PORT
    "# Версия Python, которую нужно установить"
    PYTHON_VERSION
    "# Режимы приложения и железа"
    APP_ENV
    "# Местоположение проекта, для теста файла env"
    PROJECT_DIR
    "# USB Relay. Подключаемое реле."
    RELAY_ID RELAY_INVERTED RELAY_TIMEOUT RELAY_MAX_RETRIES
)
OPT_NAMES=()
for s in "${OPT_SPEC[@]}"; do
    case "$s" in
        "#"*) ;;
        *) OPT_NAMES+=("$s"); IS_OPT["$s"]=1 ;;
    esac
done
PATH_VARS=(DB_DIR VENV_DIR LOG_DIR WORK_LOG API_LOG BACKUP)

# Результат в REPLY (без подпроцессов)
get_default() {
    case "$1" in
        SITE_WEATHER)      REPLY="OPENWEATHERMAP" ;;
        LOCATION_LAT)      REPLY="50.4501" ;;
        LOCATION_LON)      REPLY="30.5234" ;;
        DB_DIR)            REPLY="$DIR_PATH" ;;
        DB_NAME)           REPLY="${VERSION_PREFIX}climate_data.sqlite3" ;;
        VENV_DIR)          REPLY="$DIR_PATH/venv" ;;
        VENV_NAME)         REPLY="venv_smart_home_climate" ;;
        LOG_DIR)           REPLY="$DIR_PATH/logs" ;;
        WORK_LOG)          REPLY="${FINAL[LOG_DIR]}/work_log.log" ;;
        API_LOG)           REPLY="${FINAL[LOG_DIR]}/api_log.log" ;;
        BACKUP)            REPLY="$DIR_PATH/backup" ;;
        SERVER_HOST)       REPLY="0.0.0.0" ;;
        SERVER_PORT)       REPLY="8000" ;;
        PYTHON_VERSION)    REPLY="3.12" ;;
        APP_ENV)           REPLY="DEVELOPMENT" ;;
        PROJECT_DIR)       REPLY="$DIR_PATH" ;;
        RELAY_ID)          REPLY="959BI_1" ;;
        RELAY_INVERTED)    REPLY="false" ;;
        RELAY_TIMEOUT)     REPLY="2.0" ;;
        RELAY_MAX_RETRIES) REPLY="3" ;;
        *)                 REPLY="" ;;
    esac
}

# Запись .env: обязательная часть — из env.txt как есть (значения из существующего .env, если есть),
# необязательная — из таблицы выше. Ключи из окружения в файл не попадают.
write_env_file() {
    local tmp="$ENV_FILE.tmp" line v s
    (
        umask 077
        {
            while IFS= read -r line || [ -n "$line" ]; do
                if [[ $line =~ $RE_SEP ]]; then break; fi
                if parse_assign "$line"; then
                    v="${ENVF_VAL[$P_NAME]:-}"
                    if [ -z "$v" ]; then v="$P_VAL"; fi
                    printf "%s = '%s'%s\n" "$P_NAME" "$v" "$P_TAIL"
                else
                    printf '%s\n' "${line%$'\r'}"
                fi
            done < "$ENV_TXT"
            printf '%s\n' "$SEP_LINE"
            for s in "${OPT_SPEC[@]}"; do
                case "$s" in
                    "#"*) printf '\n%s\n' "$s" ;;
                    *)    printf "%s = '%s'\n" "$s" "${FINAL[$s]}" ;;
                esac
            done
        } > "$tmp"
    ) || return 1
    mv -f -- "$tmp" "$ENV_FILE"
}

######################################## Загрузка конфигурации ########################################
note "СТАРТ RUN"

[ -f "$ENV_TXT" ] || die "Не найден файл $ENV_TXT (запускайте run.sh из корня проекта)."
load_env_txt
[ "${#REQ_NAMES[@]}" -gt 0 ] || die "В $ENV_TXT не найдено ни одной обязательной переменной."
case " ${REQ_NAMES[*]} " in
    *" VERSION "*) ;;
    *) die "В обязательной части $ENV_TXT должна быть переменная VERSION." ;;
esac

# 1. Что есть в окружении
env_missing=()
other_filled=0
for n in "${REQ_NAMES[@]}"; do
    if [ -n "${!n:-}" ]; then
        if [ "$n" != "VERSION" ]; then other_filled=$((other_filled + 1)); fi
    else
        env_missing+=("$n")
    fi
done
if [ -n "${VERSION:-}" ] && [ "$other_filled" -ge 1 ]; then AUTO=true; fi
if [ "$AUTO" = true ]; then note "Режим: автоматический (сервер)"; else note "Режим: обычный (вопросы в терминал)"; fi

# 2. Недостающие обязательные: .env, затем env.txt
SOURCE="окружение"
from_txt=0
HAVE_ENVF=false
if [ "${#env_missing[@]}" -gt 0 ]; then
    SOURCE="файлы"
    if [ "${#env_missing[@]}" -eq "${#REQ_NAMES[@]}" ]; then
        note "В окружении нет ни одной обязательной переменной."
    else
        note "В окружении нет обязательных переменных: ${env_missing[*]}"
    fi
    if [ -f "$ENV_FILE" ]; then
        load_envf
        HAVE_ENVF=true
        note "Найден файл $ENV_FILE"
    else
        note "Файл $ENV_FILE не найден"
    fi
    still=()
    for n in "${env_missing[@]}"; do
        if [ -n "${ENVF_VAL[$n]:-}" ]; then
            FINAL["$n"]="${ENVF_VAL[$n]}"
        elif [ -n "${TXT_VAL[$n]:-}" ]; then
            FINAL["$n"]="${TXT_VAL[$n]}"
            from_txt=$((from_txt + 1))
            note "$n взята из $ENV_TXT"
        else
            still+=("$n")
        fi
    done
    if [ "${#still[@]}" -gt 0 ]; then
        die "Не заполнены обязательные переменные: ${still[*]}. Задайте их в окружении, в .env или в run/env.txt и перезапустите."
    fi
    for n in "${env_missing[@]}"; do export "$n=${FINAL[$n]}"; done

    # Неизвестные имена в .env и расхождение версии
    for n in "${!ENVF_VAL[@]}"; do
        if [ -z "${IS_OPT[$n]:-}" ] && [[ " ${REQ_NAMES[*]} " != *" $n "* ]]; then
            note "Предупреждение: переменная $n из .env неизвестна и игнорируется"
        fi
    done
    if [ -n "${ENVF_VAL[VERSION]:-}" ] && [ -n "${TXT_VAL[VERSION]:-}" ] && [ "${ENVF_VAL[VERSION]}" != "${TXT_VAL[VERSION]}" ]; then
        note "Предупреждение: VERSION в .env ('${ENVF_VAL[VERSION]}') отличается от env.txt ('${TXT_VAL[VERSION]}')"
    fi
fi

# 3. VERSION → префикс имени БД (3.0.0 → 3_0_0_)
re_ver='^[0-9]+(\.[0-9]+)*$'
[[ $VERSION =~ $re_ver ]] || die "Некорректная VERSION='$VERSION' (ожидается вид 3.0.0)."
VERSION_PREFIX="${VERSION//./_}_"

# 4. Необязательные: окружение → (.env → env.txt, если источник не окружение) → по умолчанию
FIXED=false
defaulted=()
for n in "${OPT_NAMES[@]}"; do
    cand=""
    if [ -n "${!n:-}" ]; then
        cand="${!n}"
    elif [ "$SOURCE" != "окружение" ]; then
        cand="${ENVF_VAL[$n]:-}"
        if [ -z "$cand" ]; then cand="${TXT_VAL[$n]:-}"; fi
    fi
    if [ -z "$cand" ]; then
        get_default "$n"
        cand="$REPLY"
        defaulted+=("$n")
    fi
    FINAL["$n"]="$cand"
done
if [ "${#defaulted[@]}" -gt 0 ]; then note "Значения по умолчанию: ${defaulted[*]}"; fi

# 5. PROJECT_DIR: .env/окружение от другого проекта → сбрасываем только пути
if [ "${FINAL[PROJECT_DIR]}" != "$DIR_PATH" ]; then
    note "PROJECT_DIR='${FINAL[PROJECT_DIR]}' не совпадает с папкой проекта '$DIR_PATH'"
    if ask_confirm "PROJECT_DIR='${FINAL[PROJECT_DIR]}', а проект в '$DIR_PATH'. Заменить пути (${PATH_VARS[*]}) на значения по умолчанию?"; then
        FINAL[LOG_DIR]="$DIR_PATH/logs"
        for n in "${PATH_VARS[@]}"; do
            get_default "$n"
            FINAL["$n"]="$REPLY"
        done
        FIXED=true
        note "Пути сброшены на значения по умолчанию"
    else
        die "Пути указывают на другой проект ('${FINAL[PROJECT_DIR]}'). Исправьте PROJECT_DIR или пути."
    fi
    FINAL[PROJECT_DIR]="$DIR_PATH"
fi

# 6. DB_NAME = префикс VERSION + базовая часть имени (старый префикс версии отрезается)
db_base="${FINAL[DB_NAME]}"
re_pref='^[0-9]+(_[0-9]+)+_'
if [[ $db_base =~ $re_pref ]]; then db_base="${db_base#"${BASH_REMATCH[0]}"}"; fi
if [ -z "$db_base" ] || [[ $db_base == */* ]]; then db_base="climate_data.sqlite3"; fi
if [ "${FINAL[DB_NAME]}" != "${VERSION_PREFIX}${db_base}" ]; then
    note "DB_NAME исправлено: '${FINAL[DB_NAME]}' → '${VERSION_PREFIX}${db_base}'"
    FINAL[DB_NAME]="${VERSION_PREFIX}${db_base}"
    FIXED=true
fi

# 7. PYTHON_VERSION подставляется в команды — проверяем формат
re_py='^3\.[0-9]+$'
if ! [[ ${FINAL[PYTHON_VERSION]} =~ $re_py ]]; then
    note "PYTHON_VERSION='${FINAL[PYTHON_VERSION]}' некорректна, значение по умолчанию: 3.12"
    FINAL[PYTHON_VERSION]="3.12"
    FIXED=true
fi

# 8. Сайт погоды и его ключ
site="${FINAL[SITE_WEATHER]^^}"
case "$site" in
    OPENWEATHERMAP|TOMORROW)
        if [ "$site" != "${FINAL[SITE_WEATHER]}" ]; then FINAL[SITE_WEATHER]="$site"; FIXED=true; fi
        ;;
    *)
        note "SITE_WEATHER='${FINAL[SITE_WEATHER]}' неизвестен (допустимо: OPENWEATHERMAP, TOMORROW)"
        if ask_confirm "SITE_WEATHER='${FINAL[SITE_WEATHER]}' неизвестен. Заменить на OPENWEATHERMAP?"; then
            FINAL[SITE_WEATHER]="OPENWEATHERMAP"
            FIXED=true
        else
            die "Неизвестный SITE_WEATHER='${FINAL[SITE_WEATHER]}' (допустимо: OPENWEATHERMAP, TOMORROW)."
        fi
        ;;
esac
key_name="${FINAL[SITE_WEATHER]}_API_KEY"
if [ -z "${!key_name:-}" ]; then
    die "Для SITE_WEATHER=${FINAL[SITE_WEATHER]} не заполнен $key_name (заполните его или смените SITE_WEATHER)."
fi

# 9. Экспорт
for n in "${OPT_NAMES[@]}"; do export "$n=${FINAL[$n]}"; done
export VERSION
RUN_LOG="${RUN_LOG:-$LOG_DIR/run_log.log}"
export RUN_LOG

# 10. Запись .env (только когда источник — файлы; значения из окружения на диск не пишутся)
if [ "$SOURCE" != "окружение" ]; then
    if [ "$HAVE_ENVF" = false ]; then
        if ask_confirm "Файл .env не найден. Создать его из $ENV_TXT?"; then
            write_env_file || die "Не удалось записать $ENV_FILE"
            note "Файл .env создан из $ENV_TXT"
        else
            note "Файл .env не создан; переменные взяты из $ENV_TXT только для этого запуска"
        fi
    else
        need_update=false
        if [ "$from_txt" -gt 0 ] || [ "$FIXED" = true ]; then need_update=true; fi
        for n in "${OPT_NAMES[@]}"; do
            if [ -z "${ENVF_VAL[$n]:-}" ]; then need_update=true; fi
        done
        if [ "$need_update" = true ]; then
            if [ "$AUTO" = true ]; then
                note "АВТО: в .env не хватает переменных или они исправлены; файл не изменяется, значения применены в окружении процесса"
            elif ask_confirm "В .env не хватает переменных или значения исправлены. Перезаписать .env по шаблону (неизвестные переменные будут удалены)?"; then
                write_env_file || die "Не удалось записать $ENV_FILE"
                note "Файл .env обновлён"
            fi
        fi
    fi
fi

################################ Журнал и вывод ################################
open_log || die "Не удалось открыть журнал ${RUN_LOG:-}"
exec 1>> "$RUN_LOG" 2>&1

VENV_PATH="$VENV_DIR/$VENV_NAME"
PY="python${PYTHON_VERSION}"

############################ Папки и файлы логов/БД ############################
check_or_create_dir "$LOG_DIR"  || die "Папка логов $LOG_DIR не создана"
check_or_create_file "$WORK_LOG" "run/log.txt" || die "Файл $WORK_LOG не создан"
check_or_create_file "$API_LOG"  "run/log.txt" || die "Файл $API_LOG не создан"
check_or_create_dir "$DB_DIR"   || die "Папка БД $DB_DIR не создана"
check_or_create_dir "$BACKUP"   || die "Папка backup $BACKUP не создана"

########################### Проверка Python ###########################
if command -v "$PY" &>/dev/null; then
    echo "✅ $PY уже установлен."
else
    echo "❌ $PY не найден."
    if [ "$AUTO" = true ]; then
        die "$PY не найден. В автоматическом режиме Python не устанавливается."
    fi
    ask_confirm "Установить $PY?" || die "Установка $PY отменена."
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update
    sudo apt-get install -y "$PY" "${PY}-venv" "${PY}-dev"
fi

############################ Проверка пакетов ############################
install_package "python3-pip" "pip3 --version" || die "pip не установлен."
install_package "${PY}-venv ${PY}-dev" "$PY -c 'import ensurepip, venv'" || die "Модуль venv для $PY не установлен."

########################### Виртуальное окружение ###########################
check_or_create_dir "$VENV_DIR" || die "Папка $VENV_DIR не создана"
if [ ! -d "$VENV_PATH" ]; then
    echo "Виртуальное окружение $VENV_NAME не существует."
    if ask_confirm "Создать виртуальное окружение $VENV_NAME ?"; then
        "$PY" -m venv "$VENV_PATH"
        echo "Виртуальное окружение успешно создано в $VENV_PATH"
        # shellcheck disable=SC1091
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

############################### Запуск приложения ###############################
if [ -f "$VENV_PATH/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_PATH/bin/activate"
fi

note "СТАРТ run_program.py"
echo "################################----------- Запуск run_program.py #############################"
"$PY" run/run_program.py

note "СТАРТ migrator.py"
echo "################################----------- Запуск migrator.py #############################"
"$PY" run/migrator.py

note "СТАРТ main.py"
# Восстановление стандартных потоков (systemd / консоль)
trap - ERR
exec 1>&3 2>&4 3>&- 4>&- 5<&-

echo "######################## Пуск основной программы проекта main.py ######################"
exec "$PY" -m app.main