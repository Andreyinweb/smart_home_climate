#!/usr/bin/env bash

# run/run.sh
#
# Запуск из корня проекта:  bash run/run.sh [-new | -calc]
#   без параметров  обычный запуск
#   -new            общий сброс к базовым настройкам: .env, база данных, backup-файлы, журналы и заглушка
#                   usbrelay переносятся в архив backup/reset_<время>, после чего старт как с нуля.
#                   Виртуальное окружение не трогается. Нужен терминал и ввод слова NEW.
#   -calc           после подготовки и миграции выполнить run/initial_calculations.py и выйти (main.py не запускается)
#
# Значение каждой переменной: окружение → .env → run/env.txt → значение по умолчанию.
# Обязательны только переменные из run/env.txt ДО строки-разделителя «##########…» (сейчас только VERSION).
#
# Автоматический режим (сервер): задана переменная окружения RUN_AUTO=true (например, в unit-файле systemd).
#   Все вопросы получают «да», существующий .env не трогается, python/pip не ставятся (вместо этого стоп).
# Обычный режим (разработка): любое действие только с согласия в терминале. Нет терминала — «нет».
#
# Первый старт (нет .env и нет переменных проекта в окружении): показывается список действий
#   и задаётся один вопрос на весь список. При «нет» ничего не создаётся.
#
# Язык сообщений в терминале: LANGUAGE (окружение, .env, env.txt), иначе язык системы, иначе английский.
#   Поддерживаются ru, uk, en. Журнал run_log.log всегда на английском. LANGUAGE в дочерние процессы
#   не экспортируется (это переменная gettext), приложение читает её из .env.
#
# После создания .env значения в run/env.txt очищаются (остаются имена, комментарии и VERSION),
# чтобы данные не попали в git.
#
# Реле usbrelay (/usr/local/bin/usbrelay):
#   Заглушка run/stub.txt ставится только в обычном режиме и только при APP_ENV=DEVELOPMENT.
#   В режиме AUTO или при любом другом APP_ENV наша заглушка удаляется (файл без маркера не трогается).
#   APP_ENV по умолчанию: DEVELOPMENT в обычном режиме, STAGING в режиме AUTO.
#   Если при APP_ENV=DEVELOPMENT из .env по адресу лежит реальный usbrelay (не заглушка),
#   APP_ENV заменяется на STAGING (в .env тоже) с предупреждением в журнале.
#   Если APP_ENV=DEVELOPMENT взят по умолчанию (первый запуск), заглушка при реальном реле не ставится,
#   а замена на STAGING произойдёт при следующем запуске.

set -Eeo pipefail

# Исходные потоки: 3 = stdout, 4 = stderr (терминал), 5 = stdin
exec 3>&1 4>&2 5<&0

DIR_PATH="$PWD"
ENV_FILE="$DIR_PATH/.env"
ENV_TXT="$DIR_PATH/run/env.txt"
CALC_FILE="$DIR_PATH/run/initial_calculations.py"
SEP_LINE='########################## Не обязательные переменные  ########################################'
RE_SEP='^[[:space:]]*#{10,}'
RE_VER='^[0-9]+(\.[0-9]+)*$'

# Заглушка usbrelay
RELAY_BIN="/usr/local/bin/usbrelay"
STUB_SRC="$DIR_PATH/run/stub.txt"
STUB_MARK="usbrelay_mock_state"             # строка-маркер: есть в stub.txt, по ней узнаём свою заглушку
STUB_STATE="/tmp/usbrelay_mock_state.json"  # файл состояния заглушки (см. stub.txt)
APP_ENV_DEFAULTED=false
APP_ENV_DOWNGRADED=false

AUTO=false
case "${RUN_AUTO:-}" in
    1|true|TRUE|True|yes|YES|Yes) AUTO=true ;;
esac

MODE_NEW=false
MODE_CALC=false
IGNORE_ENV=false     # true после -new: переменные окружения не используются
FORCE_FIRST=false    # true после -new: считать старт первым
FIRST_START=false
PRECONSENT=false     # true после согласия со списком первого старта
HAVE_ENVF=false
FIXED=false
LANG_CODE="en"

declare -A M=() E=() TXT_VAL=() ENVF_VAL=() FINAL=() IS_OPT=()
REQ_NAMES=()
defaulted=()
NEW_SRC=()
NEW_CAT=()

#################################### Тексты сообщений ####################################
# Терминал: язык LANG_CODE (M). Журнал: всегда английский (E). Недостающие ключи берутся из английского.
# Строки — формат для printf: %s подставляет параметры, \n — перевод строки.

lang_en() {
    M[usage]='Usage: bash run/run.sh [-new | -calc]\n  (no options)  normal start\n  -new          full reset to base settings (everything is moved to backup/reset_<time>)\n  -calc         after preparation run run/initial_calculations.py and exit'
    M[bad_arg]='Unknown option: %s'
    M[both_modes]='Options -new and -calc cannot be used together.'
    M[new_auto]='-new does not work in automatic mode (RUN_AUTO): there is nobody to confirm.'
    M[need_tty]='-new needs a terminal for confirmation.'
    M[app_running]='The application is running (app.main). Stop it and try again.'
    M[calc_missing]='File %s not found.'
    M[no_env_txt]='File %s not found (run run.sh from the project root).'
    M[no_version_section]='The required part of %s must contain VERSION.'
    M[req_missing]='Required variable %s is empty (set it in the environment, .env or run/env.txt).'
    M[bad_version]="Invalid VERSION='%s' (expected something like 3.0.0)."
    M[first_title]='First start. The following actions will be performed:'
    M[first_python]='Python %s (installed with sudo if missing) and venv/pip packages'
    M[first_venv]='Virtual environment %s and packages from requirements.txt'
    M[first_env]='File .env (values are taken from run/env.txt, then run/env.txt is cleared)'
    M[first_logs]='Logs: %s'
    M[first_db]='Database: %s, backups folder: %s'
    M[first_stub]='usbrelay stub in %s (APP_ENV=DEVELOPMENT, sudo)'
    M[first_ask]='Perform all of the above?'
    M[first_declined]='Cancelled. Nothing was created.'
    M[q_mkdir]='Create folder %s?'
    M[q_mkfile]='Create file %s?'
    M[q_pkg]="Install package '%s'?"
    M[q_python]='Install %s?'
    M[q_venv]='Create virtual environment %s?'
    M[q_stub]='APP_ENV=DEVELOPMENT: install the usbrelay stub to %s (sudo)?'
    M[q_envcreate]='File .env not found. Create it?'
    M[q_envrewrite]='.env lacks variables or values were corrected. Rewrite .env from the template (unknown variables will be removed)?'
    M[q_project_dir]="PROJECT_DIR='%s' but the project is in '%s'. Replace paths (%s) with defaults?"
    M[q_site]="SITE_WEATHER='%s' is unknown. Replace with MET_NO?"
    M[d_project_dir]="Paths point to another project ('%s'). Fix PROJECT_DIR or the paths."
    M[d_site]="Unknown SITE_WEATHER='%s' (allowed: OPENWEATHERMAP, TOMORROW, OPEN_METEO, MET_NO)."
    M[d_env_write]='Could not write %s'
    M[d_log]='Could not open the log %s'
    M[d_dir]='Folder %s was not created'
    M[d_file]='File %s was not created'
    M[d_pkg_auto]="Package '%s' is not installed. Packages are not installed in automatic mode."
    M[d_pkg]="Package '%s' is not installed."
    M[d_py_auto]='%s not found. Python is not installed in automatic mode.'
    M[d_py_cancel]='Installation of %s was cancelled.'
    M[d_pip]='pip is not installed.'
    M[d_venv_mod]='The venv module for %s is not installed.'
    M[d_stub_rm]='Could not remove the stub %s (sudo needed). Remove it manually.'
    M[d_stub_inst]='Could not install the stub to %s (sudo needed).'
    M[d_stub_src]='%s not found: it is required when APP_ENV=DEVELOPMENT.'
    M[d_stub_mark]="%s has no marker '%s': such a stub cannot be removed safely later."
    M[d_tmp]='Could not create a temporary file.'
    M[d_new_mv]='Could not move %s to the archive.'
    M[err_trap]='run.sh: error (code %s), line %s. Details: %s'
    M[new_title]='RESET TO BASE SETTINGS. The following will be moved to the archive:'
    M[new_stub]='usbrelay stub %s will be removed (sudo)'
    M[new_archive]='Archive folder: %s'
    M[new_keep]='The virtual environment (%s) is not touched.'
    M[new_confirm]='Type NEW to confirm (anything else cancels): '
    M[new_cancel]='Cancelled. Nothing was changed.'
    M[new_nothing]='Nothing to archive. Continuing as a first start.'
    M[new_done]='Moved to the archive: %s'
    M[yn_invalid]='Please enter y/n'
    M[calc_done]='Calculations finished.'
}

lang_ru() {
    M[usage]='Использование: bash run/run.sh [-new | -calc]\n  (без параметров)  обычный запуск\n  -new              общий сброс к базовым настройкам (всё переносится в backup/reset_<время>)\n  -calc             после подготовки выполнить run/initial_calculations.py и выйти'
    M[bad_arg]='Неизвестный параметр: %s'
    M[both_modes]='Параметры -new и -calc нельзя использовать вместе.'
    M[new_auto]='-new не работает в автоматическом режиме (RUN_AUTO): подтверждать некому.'
    M[need_tty]='Для -new нужен терминал, чтобы подтвердить сброс.'
    M[app_running]='Приложение запущено (app.main). Остановите его и повторите.'
    M[calc_missing]='Не найден файл %s.'
    M[no_env_txt]='Не найден файл %s (запускайте run.sh из корня проекта).'
    M[no_version_section]='В обязательной части %s должна быть переменная VERSION.'
    M[req_missing]='Обязательная переменная %s пуста (задайте её в окружении, .env или run/env.txt).'
    M[bad_version]="Некорректная VERSION='%s' (ожидается вид 3.0.0)."
    M[first_title]='Первый запуск. Будут выполнены действия:'
    M[first_python]='Python %s (установка через sudo, если его нет) и пакеты venv/pip'
    M[first_venv]='Виртуальное окружение %s и пакеты из requirements.txt'
    M[first_env]='Файл .env (значения берутся из run/env.txt, после чего run/env.txt очищается)'
    M[first_logs]='Журналы: %s'
    M[first_db]='База данных: %s, папка backup: %s'
    M[first_stub]='Заглушка usbrelay в %s (APP_ENV=DEVELOPMENT, sudo)'
    M[first_ask]='Выполнить все действия из списка?'
    M[first_declined]='Отменено. Ничего не создано.'
    M[q_mkdir]='Создать папку %s?'
    M[q_mkfile]='Создать файл %s?'
    M[q_pkg]="Установить пакет '%s'?"
    M[q_python]='Установить %s?'
    M[q_venv]='Создать виртуальное окружение %s?'
    M[q_stub]='APP_ENV=DEVELOPMENT: установить заглушку usbrelay в %s (sudo)?'
    M[q_envcreate]='Файл .env не найден. Создать его?'
    M[q_envrewrite]='В .env не хватает переменных или значения исправлены. Перезаписать .env по шаблону (неизвестные переменные будут удалены)?'
    M[q_project_dir]="PROJECT_DIR='%s', а проект в '%s'. Заменить пути (%s) на значения по умолчанию?"
    M[q_site]="SITE_WEATHER='%s' неизвестен. Заменить на MET_NO?"
    M[d_project_dir]="Пути указывают на другой проект ('%s'). Исправьте PROJECT_DIR или пути."
    M[d_site]="Неизвестный SITE_WEATHER='%s' (допустимо: OPENWEATHERMAP, TOMORROW, OPEN_METEO, MET_NO)."
    M[d_env_write]='Не удалось записать %s'
    M[d_log]='Не удалось открыть журнал %s'
    M[d_dir]='Папка %s не создана'
    M[d_file]='Файл %s не создан'
    M[d_pkg_auto]="Не установлен пакет '%s'. В автоматическом режиме пакеты не ставятся."
    M[d_pkg]="Пакет '%s' не установлен."
    M[d_py_auto]='%s не найден. В автоматическом режиме Python не устанавливается.'
    M[d_py_cancel]='Установка %s отменена.'
    M[d_pip]='pip не установлен.'
    M[d_venv_mod]='Модуль venv для %s не установлен.'
    M[d_stub_rm]='Не удалось удалить заглушку %s (нужны права sudo). Удалите её вручную.'
    M[d_stub_inst]='Не удалось установить заглушку в %s (нужны права sudo).'
    M[d_stub_src]='Не найден %s: он нужен при APP_ENV=DEVELOPMENT.'
    M[d_stub_mark]="В %s нет маркера '%s': такую заглушку потом нельзя безопасно удалить."
    M[d_tmp]='Не удалось создать временный файл.'
    M[d_new_mv]='Не удалось перенести %s в архив.'
    M[err_trap]='run.sh: ошибка (код %s), строка %s. Подробности: %s'
    M[new_title]='СБРОС К БАЗОВЫМ НАСТРОЙКАМ. В архив будет перенесено:'
    M[new_stub]='заглушка usbrelay %s будет удалена (sudo)'
    M[new_archive]='Папка архива: %s'
    M[new_keep]='Виртуальное окружение (%s) не затрагивается.'
    M[new_confirm]='Для подтверждения введите NEW (всё остальное — отмена): '
    M[new_cancel]='Отменено. Ничего не изменено.'
    M[new_nothing]='Архивировать нечего. Продолжаем как первый старт.'
    M[new_done]='Перенесено в архив: %s'
    M[yn_invalid]='Пожалуйста, введите y/n'
    M[calc_done]='Расчёт завершён.'
}

lang_uk() {
    M[usage]='Використання: bash run/run.sh [-new | -calc]\n  (без параметрів)  звичайний запуск\n  -new              загальне скидання до базових налаштувань (усе переноситься в backup/reset_<час>)\n  -calc             після підготовки виконати run/initial_calculations.py і вийти'
    M[bad_arg]='Невідомий параметр: %s'
    M[both_modes]='Параметри -new і -calc не можна використовувати разом.'
    M[new_auto]='-new не працює в автоматичному режимі (RUN_AUTO): підтверджувати нікому.'
    M[need_tty]='Для -new потрібен термінал, щоб підтвердити скидання.'
    M[app_running]='Застосунок запущено (app.main). Зупиніть його і повторіть.'
    M[calc_missing]='Не знайдено файл %s.'
    M[no_env_txt]='Не знайдено файл %s (запускайте run.sh з кореня проєкту).'
    M[no_version_section]='В обовʼязковій частині %s має бути змінна VERSION.'
    M[req_missing]='Обовʼязкова змінна %s порожня (задайте її в оточенні, .env або run/env.txt).'
    M[bad_version]="Некоректна VERSION='%s' (очікується вигляд 3.0.0)."
    M[first_title]='Перший запуск. Буде виконано дії:'
    M[first_python]='Python %s (встановлення через sudo, якщо його немає) і пакети venv/pip'
    M[first_venv]='Віртуальне середовище %s і пакети з requirements.txt'
    M[first_env]='Файл .env (значення беруться з run/env.txt, після чого run/env.txt очищається)'
    M[first_logs]='Журнали: %s'
    M[first_db]='База даних: %s, папка backup: %s'
    M[first_stub]='Заглушка usbrelay у %s (APP_ENV=DEVELOPMENT, sudo)'
    M[first_ask]='Виконати всі дії зі списку?'
    M[first_declined]='Скасовано. Нічого не створено.'
    M[q_mkdir]='Створити папку %s?'
    M[q_mkfile]='Створити файл %s?'
    M[q_pkg]="Встановити пакет '%s'?"
    M[q_python]='Встановити %s?'
    M[q_venv]='Створити віртуальне середовище %s?'
    M[q_stub]='APP_ENV=DEVELOPMENT: встановити заглушку usbrelay у %s (sudo)?'
    M[q_envcreate]='Файл .env не знайдено. Створити його?'
    M[q_envrewrite]='В .env бракує змінних або значення виправлено. Перезаписати .env за шаблоном (невідомі змінні буде видалено)?'
    M[q_project_dir]="PROJECT_DIR='%s', а проєкт у '%s'. Замінити шляхи (%s) на значення за замовчуванням?"
    M[q_site]="SITE_WEATHER='%s' невідомий. Замінити на MET_NO?"
    M[d_project_dir]="Шляхи вказують на інший проєкт ('%s'). Виправте PROJECT_DIR або шляхи."
    M[d_site]="Невідомий SITE_WEATHER='%s' (допустимо: OPENWEATHERMAP, TOMORROW, OPEN_METEO, MET_NO)."
    M[d_env_write]='Не вдалося записати %s'
    M[d_log]='Не вдалося відкрити журнал %s'
    M[d_dir]='Папку %s не створено'
    M[d_file]='Файл %s не створено'
    M[d_pkg_auto]="Не встановлено пакет '%s'. В автоматичному режимі пакети не встановлюються."
    M[d_pkg]="Пакет '%s' не встановлено."
    M[d_py_auto]='%s не знайдено. В автоматичному режимі Python не встановлюється.'
    M[d_py_cancel]='Встановлення %s скасовано.'
    M[d_pip]='pip не встановлено.'
    M[d_venv_mod]='Модуль venv для %s не встановлено.'
    M[d_stub_rm]='Не вдалося видалити заглушку %s (потрібні права sudo). Видаліть її вручну.'
    M[d_stub_inst]='Не вдалося встановити заглушку в %s (потрібні права sudo).'
    M[d_stub_src]='Не знайдено %s: він потрібен при APP_ENV=DEVELOPMENT.'
    M[d_stub_mark]="У %s немає маркера '%s': таку заглушку потім не можна безпечно видалити."
    M[d_tmp]='Не вдалося створити тимчасовий файл.'
    M[d_new_mv]='Не вдалося перенести %s в архів.'
    M[err_trap]='run.sh: помилка (код %s), рядок %s. Подробиці: %s'
    M[new_title]='СКИДАННЯ ДО БАЗОВИХ НАЛАШТУВАНЬ. В архів буде перенесено:'
    M[new_stub]='заглушку usbrelay %s буде видалено (sudo)'
    M[new_archive]='Папка архіву: %s'
    M[new_keep]='Віртуальне середовище (%s) не чіпається.'
    M[new_confirm]='Для підтвердження введіть NEW (усе інше — скасування): '
    M[new_cancel]='Скасовано. Нічого не змінено.'
    M[new_nothing]='Архівувати нічого. Продовжуємо як перший старт.'
    M[new_done]='Перенесено в архів: %s'
    M[yn_invalid]='Будь ласка, введіть y/n'
    M[calc_done]='Розрахунок завершено.'
}

# Результат в REPLY (без подпроцессов): msg — на языке терминала, msg_en — английский для журнала
msg() {
    local key="$1"
    shift
    printf -v REPLY -- "${M[$key]:-$key}" "$@"
}

msg_en() {
    local key="$1"
    shift
    printf -v REPLY -- "${E[$key]:-$key}" "$@"
}

set_language() {
    local k
    LANG_CODE="$1"
    M=()
    lang_en
    if [ "${#E[@]}" -eq 0 ]; then
        for k in "${!M[@]}"; do E[$k]="${M[$k]}"; done
    fi
    case "$LANG_CODE" in
        ru) lang_ru ;;
        uk) lang_uk ;;
    esac
}

# Значение языка → ru / uk / en (REPLY). Вид ru_RU.UTF-8, ru_RU:ru, RU → ru; неизвестный язык → en
normalize_lang() {
    local v="${1%%:*}"
    v="${v,,}"
    v="${v:0:2}"
    case "$v" in
        ru) REPLY="ru" ;;
        uk|ua) REPLY="uk" ;;
        *) REPLY="en" ;;
    esac
}

# Язык системы (REPLY): LC_ALL → LC_MESSAGES → LANG
locale_lang() {
    local v
    REPLY=""
    for v in "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
        if [ -n "$v" ]; then
            REPLY="$v"
            return 0
        fi
    done
    return 0
}

# Предварительный язык: окружение → .env → env.txt → система
early_language() {
    local raw=""
    if [ "$IGNORE_ENV" != true ]; then raw="${LANGUAGE:-}"; fi
    if [ -z "$raw" ]; then raw="${ENVF_VAL[LANGUAGE]:-}"; fi
    if [ -z "$raw" ]; then raw="${TXT_VAL[LANGUAGE]:-}"; fi
    if [ -z "$raw" ]; then
        locale_lang
        raw="$REPLY"
    fi
    normalize_lang "$raw"
    set_language "$REPLY"
}

#################################### Журнал ####################################
# До загрузки конфигурации LOG_DIR неизвестен, поэтому сообщения копятся в LOG_BUF
# и сбрасываются в run_log.log сразу после его открытия. Журнал создаётся только после согласия на первый старт.
LOG_READY=false
LOG_ALLOWED=false
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

# Ошибка до открытия журнала: только в терминал
fail() {
    local key="$1"
    shift
    msg "$key" "$@"
    printf '❌ %s\n' "$REPLY" >&4
    exit 1
}

# Ошибка: в терминал (fd 4) и в журнал, затем стоп
die() {
    local key="$1" text
    shift
    msg "$key" "$@"
    text="$REPLY"
    msg_en "$key" "$@"
    printf '❌ %s\n' "$text" >&4
    note "ERROR: $REPLY"
    if [ "$LOG_ALLOWED" = true ] && [ "$LOG_READY" != true ]; then open_log || true; fi
    exit 1
}

on_err() {
    local rc="$1" line="$2" cmd="$3"
    note "ERROR (code $rc), line $line: $cmd"
    msg err_trap "$rc" "$line" "${RUN_LOG:-log not opened}"
    printf '❌ %s\n' "$REPLY" >&4
}

trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

#################################### Терминал, вопросы ####################################
has_terminal() {
    if ( : </dev/tty ) 2>/dev/null; then return 0; fi
    [ -t 5 ]
}

# Строка с терминала в REPLY. Код 1 — терминала нет или ввод закрыт.
tty_read() {
    local prompt="$1"
    REPLY=""
    if ( : </dev/tty ) 2>/dev/null; then
        printf '%s' "$prompt" > /dev/tty
        IFS= read -r REPLY < /dev/tty || return 1
    elif [ -t 5 ]; then
        printf '%s' "$prompt" >&3
        IFS= read -r REPLY <&5 || return 1
    else
        return 1
    fi
    return 0
}

# Строка в терминал (если терминала нет — в исходный stdout)
tty_out() {
    if ( : </dev/tty ) 2>/dev/null; then
        printf '%s\n' "$1" > /dev/tty
    else
        printf '%s\n' "$1" >&3
    fi
}

# Вопрос да/нет: $1 — ключ текста, дальше параметры. AUTO — всегда «да»; нет терминала — «нет».
ask_confirm() {
    local key="$1" q en_q answer
    shift
    msg "$key" "$@"
    q="$REPLY"
    msg_en "$key" "$@"
    en_q="$REPLY"
    if [ "$AUTO" = true ]; then
        note "AUTO: \"$en_q\" -> yes"
        return 0
    fi
    while true; do
        if ! tty_read "$q [y/N]: "; then
            note "No terminal: \"$en_q\" -> no"
            return 1
        fi
        answer="$REPLY"
        case "$answer" in
            y|Y|yes|Yes|YES|д|Д|да|Да|ДА|так|Так|ТАК|т|Т) return 0 ;;
            n|N|no|No|NO|н|Н|нет|Нет|НЕТ|ні|Ні|НІ|"") return 1 ;;
            *)
                msg yn_invalid
                tty_out "$REPLY"
                ;;
        esac
    done
}

# Вопрос по действию из списка первого старта: после согласия со списком не задаётся
ask_listed() {
    if [ "$PRECONSENT" = true ]; then
        msg_en "$@"
        note "Approved with the first-start list: \"$REPLY\""
        return 0
    fi
    ask_confirm "$@"
}

# Команда с правами root: root — напрямую; AUTO — sudo без пароля (-n, чтобы не зависнуть); иначе обычный sudo
run_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif [ "$AUTO" = true ]; then
        sudo -n "$@"
    else
        sudo "$@"
    fi
}

install_package() {
    local package_name="$1" test_command="$2"
    if eval "$test_command" &>/dev/null; then
        echo "OK: package '$package_name' is already installed"
        return 0
    fi
    echo "Package '$package_name' is not installed"
    if [ "$AUTO" = true ]; then
        die d_pkg_auto "$package_name"
    fi
    ask_listed q_pkg "$package_name" || { echo "Installation of '$package_name' cancelled"; return 1; }
    echo "Updating package cache..."
    run_sudo apt update -q || return 1
    echo "Installing $package_name..."
    # shellcheck disable=SC2086
    run_sudo apt install -y $package_name || { echo "Error installing package '$package_name'!" >&2; return 1; }
    eval "$test_command" &>/dev/null || { echo "Package '$package_name' installed, but the check failed!" >&2; return 1; }
    echo "OK: package '$package_name' installed"
}

check_or_create_dir() {
    local dir_path="$1"
    if [ -d "$dir_path" ]; then
        echo "Folder $dir_path already exists."
        return 0
    fi
    echo "Folder $dir_path does not exist."
    if ask_listed q_mkdir "$dir_path"; then
        mkdir -p -- "$dir_path" || return 1
        echo "Folder $dir_path created."
        return 0
    fi
    echo "Creation of $dir_path cancelled."
    return 1
}

check_or_create_file() {
    local file_path="$1" template="$2"
    if [ ! -d "${file_path%/*}" ]; then
        echo "Folder '${file_path%/*}' does not exist: the file cannot be created"
        return 1
    fi
    if [ -f "$file_path" ]; then
        echo "File '$file_path' exists"
        return 0
    fi
    echo "File '$file_path' not found"
    if ask_listed q_mkfile "$file_path"; then
        if [ -n "$template" ] && [ -f "$template" ]; then
            cp -- "$template" "$file_path" || return 1
        else
            : > "$file_path" || return 1
        fi
        echo "File '$file_path' created"
        return 0
    fi
    echo "Creation of the file cancelled"
    return 1
}

# Запущено ли приложение (python -m app.main)
app_running() {
    if ! command -v pgrep &>/dev/null; then return 1; fi
    pgrep -f -- 'm app\.main' &>/dev/null
}

#################################### Заглушка usbrelay ####################################
# Состояние файла $RELAY_BIN → REPLY:
#   none    — файла нет
#   stub    — наша заглушка (обычный файл с маркером $STUB_MARK)
#   foreign — любой другой файл (реальный usbrelay, ссылка и т.п.): его не трогаем
relay_state() {
    if [ ! -e "$RELAY_BIN" ] && [ ! -L "$RELAY_BIN" ]; then
        REPLY="none"
    elif [ -f "$RELAY_BIN" ] && [ ! -L "$RELAY_BIN" ] && grep -qaF -- "$STUB_MARK" "$RELAY_BIN" 2>/dev/null; then
        REPLY="stub"
    else
        REPLY="foreign"
    fi
}

# Установка/удаление заглушки по итоговому APP_ENV и режиму
manage_relay_stub() {
    local st tmp
    relay_state
    st="$REPLY"

    # Заглушка не нужна: сервер (AUTO) или APP_ENV не DEVELOPMENT
    if [ "$AUTO" = true ] || [ "${FINAL[APP_ENV]}" != "DEVELOPMENT" ]; then
        if [ "$st" = stub ]; then
            note "APP_ENV=${FINAL[APP_ENV]} (AUTO=$AUTO): stub found at $RELAY_BIN, removing"
            run_sudo rm -f -- "$RELAY_BIN" || die d_stub_rm "$RELAY_BIN"
            rm -f -- "$STUB_STATE" 2>/dev/null || note "Warning: could not remove $STUB_STATE"
            note "Stub $RELAY_BIN removed"
        fi
        return 0
    fi

    # APP_ENV=DEVELOPMENT, обычный режим
    if [ "$st" = foreign ]; then
        note "APP_ENV=DEVELOPMENT, but $RELAY_BIN is not a stub (real usbrelay): stub is not installed"
        return 0
    fi

    [ -f "$STUB_SRC" ] || die d_stub_src "$STUB_SRC"
    grep -qF -- "$STUB_MARK" "$STUB_SRC" || die d_stub_mark "$STUB_SRC" "$STUB_MARK"

    tmp="$(mktemp)" || die d_tmp
    tr -d '\r' < "$STUB_SRC" > "$tmp"   # на случай CRLF (иначе «bad interpreter»)

    if [ "$st" = stub ] && [ -x "$RELAY_BIN" ] && cmp -s "$tmp" "$RELAY_BIN"; then
        rm -f -- "$tmp"
        note "Stub $RELAY_BIN is already installed and up to date"
        return 0
    fi

    if [ "$st" = none ]; then
        if ! ask_listed q_stub "$RELAY_BIN"; then
            rm -f -- "$tmp"
            note "Stub installation declined: the application will work without usbrelay"
            return 0
        fi
    else
        note "Stub $RELAY_BIN differs from $STUB_SRC, updating"
    fi

    if ! run_sudo install -m 755 -- "$tmp" "$RELAY_BIN"; then
        rm -f -- "$tmp"
        die d_stub_inst "$RELAY_BIN"
    fi
    rm -f -- "$tmp"
    note "usbrelay stub installed: $RELAY_BIN (APP_ENV=DEVELOPMENT)"
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
    "# Язык сообщений run.sh (ru, uk, en). Пусто — язык системы"
    LANGUAGE
    "# Сайт погоды (OPENWEATHERMAP, TOMORROW, OPEN_METEO или MET_NO)"
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
    "# Режим приложения: DEVELOPMENT — разработка (заглушка usbrelay), иначе (STAGING и т.д.) — реальное реле"
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
        LANGUAGE)          locale_lang ;;
        SITE_WEATHER)      REPLY="MET_NO" ;;
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
        APP_ENV)           if [ "$AUTO" = true ]; then REPLY="STAGING"; else REPLY="DEVELOPMENT"; fi ;;
        PROJECT_DIR)       REPLY="$DIR_PATH" ;;
        RELAY_ID)          REPLY="959BI_1" ;;
        RELAY_INVERTED)    REPLY="false" ;;
        RELAY_TIMEOUT)     REPLY="2.0" ;;
        RELAY_MAX_RETRIES) REPLY="3" ;;
        *)                 REPLY="" ;;
    esac
}

# Запись .env: обязательная часть — из env.txt как есть, необязательная — из таблицы выше.
# Значения берутся из итоговых FINAL.
write_env_file() {
    local tmp="$ENV_FILE.tmp" line v s
    (
        umask 077
        {
            while IFS= read -r line || [ -n "$line" ]; do
                if [[ $line =~ $RE_SEP ]]; then break; fi
                if parse_assign "$line"; then
                    v="${FINAL[$P_NAME]:-$P_VAL}"
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

# Проверка записанного .env: все переменные на месте и значения совпадают с итоговыми
verify_env_file() {
    local line n ok=true
    local -A seen=()
    [ -f "$ENV_FILE" ] || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        if parse_assign "$line"; then seen["$P_NAME"]="$P_VAL"; fi
    done < "$ENV_FILE"
    for n in "${REQ_NAMES[@]}" "${OPT_NAMES[@]}"; do
        if [ "${seen[$n]-__none__}" != "${FINAL[$n]-}" ]; then ok=false; fi
    done
    [ "$ok" = true ]
}

# Очистка env.txt: в обязательной части (VERSION) всё как есть, в необязательной значения обнуляются,
# имена и комментарии остаются. Файл переписывается, только если в нём были значения.
clear_env_txt() {
    local tmp="$ENV_TXT.tmp" line in_req=true changed=false
    {
        while IFS= read -r line || [ -n "$line" ]; do
            if [[ $line =~ $RE_SEP ]]; then
                in_req=false
                printf '%s\n' "${line%$'\r'}"
            elif [ "$in_req" = false ] && parse_assign "$line"; then
                if [ -n "$P_VAL" ]; then changed=true; fi
                printf "%s = ''%s\n" "$P_NAME" "$P_TAIL"
            else
                printf '%s\n' "${line%$'\r'}"
            fi
        done < "$ENV_TXT"
    } > "$tmp"
    if [ "$changed" = true ]; then
        chmod --reference="$ENV_TXT" -- "$tmp" 2>/dev/null || true
        if mv -f -- "$tmp" "$ENV_TXT"; then
            note "run/env.txt cleared (values moved to .env)"
        else
            rm -f -- "$tmp"
            note "Warning: could not clear run/env.txt"
        fi
    else
        rm -f -- "$tmp"
    fi
    return 0
}

# Точечная замена APP_ENV в существующем .env (остальное содержимое не меняется, права сохраняются)
set_app_env_in_file() {
    local new="$1" tmp="$ENV_FILE.tmp" found line
    (
        umask 077
        found=false
        {
            while IFS= read -r line || [ -n "$line" ]; do
                if parse_assign "$line" && [ "$P_NAME" = "APP_ENV" ]; then
                    printf "APP_ENV = '%s'%s\n" "$new" "$P_TAIL"
                    found=true
                else
                    printf '%s\n' "${line%$'\r'}"
                fi
            done < "$ENV_FILE"
            if [ "$found" = false ]; then printf "APP_ENV = '%s'\n" "$new"; fi
        } > "$tmp"
    ) || return 1
    chmod --reference="$ENV_FILE" -- "$tmp" 2>/dev/null || true
    mv -f -- "$tmp" "$ENV_FILE"
}

#################################### Параметр -new: общий сброс ####################################
reset_add() {
    if [ -e "$2" ] || [ -L "$2" ]; then
        NEW_CAT+=("$1")
        NEW_SRC+=("$2")
    fi
}

do_reset() {
    local ver prefix db_dir db_name log_dir backup f base ts archive i n dest stub_found=false
    local work_log api_log

    if [ "$AUTO" = true ]; then fail new_auto; fi
    if ! has_terminal; then fail need_tty; fi
    if app_running; then fail app_running; fi

    # Пути берём из .env максимально терпимо: при испорченных настройках сброс тоже должен работать.
    ver="${ENVF_VAL[VERSION]:-${TXT_VAL[VERSION]:-}}"
    prefix=""
    if [[ $ver =~ $RE_VER ]]; then prefix="${ver//./_}_"; fi
    db_dir="${ENVF_VAL[DB_DIR]:-$DIR_PATH}"
    db_name="${ENVF_VAL[DB_NAME]:-${prefix}climate_data.sqlite3}"
    log_dir="${ENVF_VAL[LOG_DIR]:-$DIR_PATH/logs}"
    backup="${ENVF_VAL[BACKUP]:-$DIR_PATH/backup}"
    work_log="${ENVF_VAL[WORK_LOG]:-$log_dir/work_log.log}"
    api_log="${ENVF_VAL[API_LOG]:-$log_dir/api_log.log}"

    NEW_SRC=()
    NEW_CAT=()
    reset_add env "$ENV_FILE"
    for f in "$db_dir/$db_name" "$db_dir/$db_name-wal" "$db_dir/$db_name-shm" "$db_dir/$db_name-journal"; do
        reset_add db "$f"
    done
    for f in "$backup"/*; do
        [ -f "$f" ] || continue
        case "$f" in
            *.sqlite3|*.db) reset_add backup "$f" ;;
        esac
    done
    for base in "$work_log" "$api_log" "$log_dir/run_log.log"; do
        for f in "$base"*; do
            if [ -f "$f" ]; then reset_add logs "$f"; fi
        done
    done
    relay_state
    if [ "$REPLY" = stub ]; then stub_found=true; fi

    if [ "${#NEW_SRC[@]}" -eq 0 ] && [ "$stub_found" = false ]; then
        msg new_nothing
        tty_out "$REPLY"
    else
        printf -v ts '%(%Y%m%d_%H%M%S)T' -1
        archive="$backup/reset_$ts"
        msg new_title
        tty_out "$REPLY"
        for n in "${NEW_SRC[@]}"; do tty_out "  - $n"; done
        if [ "$stub_found" = true ]; then
            msg new_stub "$RELAY_BIN"
            tty_out "  - $REPLY"
        fi
        msg new_archive "$archive"
        tty_out "$REPLY"
        msg new_keep "${ENVF_VAL[VENV_DIR]:-$DIR_PATH/venv}/${ENVF_VAL[VENV_NAME]:-venv_smart_home_climate}"
        tty_out "$REPLY"

        msg new_confirm
        if ! tty_read "$REPLY" || [ "$REPLY" != "NEW" ]; then
            msg new_cancel
            tty_out "$REPLY"
            exit 0
        fi

        for i in "${!NEW_SRC[@]}"; do
            dest="$archive/${NEW_CAT[$i]}"
            if ! { mkdir -p -- "$dest" && mv -- "${NEW_SRC[$i]}" "$dest/"; }; then
                fail d_new_mv "${NEW_SRC[$i]}"
            fi
        done
        if [ "$stub_found" = true ]; then
            run_sudo rm -f -- "$RELAY_BIN" || fail d_stub_rm "$RELAY_BIN"
            rm -f -- "$STUB_STATE" 2>/dev/null || true
        fi
        note "RESET: ${#NEW_SRC[@]} item(s) moved to $archive"
        msg new_done "$archive"
        tty_out "$REPLY"
    fi

    # Дальше старт как с нуля: окружение и старый .env не используются
    for n in "${REQ_NAMES[@]}" "${OPT_NAMES[@]}"; do unset "$n" || true; done
    IGNORE_ENV=true
    FORCE_FIRST=true
    ENVF_VAL=()
    HAVE_ENVF=false
}

#################################### Определение первого старта ####################################
detect_first_start() {
    local n
    FIRST_START=false
    if [ "$FORCE_FIRST" = true ]; then
        FIRST_START=true
        return 0
    fi
    if [ -f "$ENV_FILE" ]; then return 0; fi
    for n in "${REQ_NAMES[@]}" "${OPT_NAMES[@]}"; do
        if [ "$n" != "LANGUAGE" ] && [ -n "${!n:-}" ]; then return 0; fi
    done
    FIRST_START=true
    return 0
}

#################################### Итоговая конфигурация ####################################
resolve_config() {
    local n cand site
    FINAL=()
    defaulted=()
    FIXED=false
    APP_ENV_DEFAULTED=false
    APP_ENV_DOWNGRADED=false

    # 1. Обязательные: окружение → .env → env.txt
    for n in "${REQ_NAMES[@]}"; do
        cand=""
        if [ "$IGNORE_ENV" != true ] && [ -n "${!n:-}" ]; then
            cand="${!n}"
        else
            cand="${ENVF_VAL[$n]:-}"
            if [ -z "$cand" ]; then cand="${TXT_VAL[$n]:-}"; fi
        fi
        if [ -z "$cand" ]; then die req_missing "$n"; fi
        FINAL["$n"]="$cand"
    done

    # 2. VERSION → префикс имени БД (3.0.0 → 3_0_0_)
    VERSION="${FINAL[VERSION]}"
    [[ $VERSION =~ $RE_VER ]] || die bad_version "$VERSION"
    VERSION_PREFIX="${VERSION//./_}_"
    if [ -n "${ENVF_VAL[VERSION]:-}" ] && [ -n "${TXT_VAL[VERSION]:-}" ] && [ "${ENVF_VAL[VERSION]}" != "${TXT_VAL[VERSION]}" ]; then
        note "Warning: VERSION in .env ('${ENVF_VAL[VERSION]}') differs from env.txt ('${TXT_VAL[VERSION]}')"
    fi
    for n in "${!ENVF_VAL[@]}"; do
        if [ -z "${IS_OPT[$n]:-}" ] && [[ " ${REQ_NAMES[*]} " != *" $n "* ]]; then
            note "Warning: variable $n from .env is unknown and ignored"
        fi
    done

    # 3. Необязательные: окружение → .env → env.txt → по умолчанию
    for n in "${OPT_NAMES[@]}"; do
        cand=""
        if [ "$IGNORE_ENV" != true ] && [ -n "${!n:-}" ]; then
            cand="${!n}"
        else
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
    if [ "${#defaulted[@]}" -gt 0 ]; then note "Defaults used: ${defaulted[*]}"; fi

    # 3a. Язык: ru, uk или en
    normalize_lang "${FINAL[LANGUAGE]}"
    FINAL[LANGUAGE]="$REPLY"
    set_language "$REPLY"

    # 4. PROJECT_DIR: .env/окружение от другого проекта → сбрасываем только пути
    if [ "${FINAL[PROJECT_DIR]}" != "$DIR_PATH" ]; then
        note "PROJECT_DIR='${FINAL[PROJECT_DIR]}' does not match the project folder '$DIR_PATH'"
        if ask_confirm q_project_dir "${FINAL[PROJECT_DIR]}" "$DIR_PATH" "${PATH_VARS[*]}"; then
            FINAL[LOG_DIR]="$DIR_PATH/logs"
            for n in "${PATH_VARS[@]}"; do
                get_default "$n"
                FINAL["$n"]="$REPLY"
            done
            FIXED=true
            note "Paths reset to defaults"
        else
            die d_project_dir "${FINAL[PROJECT_DIR]}"
        fi
        FINAL[PROJECT_DIR]="$DIR_PATH"
    fi

    # 5. DB_NAME = префикс VERSION + базовая часть имени (старый префикс версии отрезается)
    local db_base="${FINAL[DB_NAME]}" re_pref='^[0-9]+(_[0-9]+)+_'
    if [[ $db_base =~ $re_pref ]]; then db_base="${db_base#"${BASH_REMATCH[0]}"}"; fi
    if [ -z "$db_base" ] || [[ $db_base == */* ]]; then db_base="climate_data.sqlite3"; fi
    if [ "${FINAL[DB_NAME]}" != "${VERSION_PREFIX}${db_base}" ]; then
        note "DB_NAME corrected: '${FINAL[DB_NAME]}' -> '${VERSION_PREFIX}${db_base}'"
        FINAL[DB_NAME]="${VERSION_PREFIX}${db_base}"
        FIXED=true
    fi

    # 6. PYTHON_VERSION подставляется в команды — проверяем формат
    local re_py='^3\.[0-9]+$'
    if ! [[ ${FINAL[PYTHON_VERSION]} =~ $re_py ]]; then
        note "PYTHON_VERSION='${FINAL[PYTHON_VERSION]}' is invalid, default used: 3.12"
        FINAL[PYTHON_VERSION]="3.12"
        FIXED=true
    fi

    # 7. Сайт погоды. Ключи ему больше не нужны здесь (OPEN_METEO и MET_NO работают без ключа).
    site="${FINAL[SITE_WEATHER]^^}"
    case "$site" in
        OPENWEATHERMAP|TOMORROW|OPEN_METEO|MET_NO)
            if [ "$site" != "${FINAL[SITE_WEATHER]}" ]; then FINAL[SITE_WEATHER]="$site"; FIXED=true; fi
            ;;
        *)
            note "SITE_WEATHER='${FINAL[SITE_WEATHER]}' is unknown (allowed: OPENWEATHERMAP, TOMORROW, OPEN_METEO, MET_NO)"
            if ask_confirm q_site "${FINAL[SITE_WEATHER]}"; then
                FINAL[SITE_WEATHER]="MET_NO"
                FIXED=true
            else
                die d_site "${FINAL[SITE_WEATHER]}"
            fi
            ;;
    esac

    # 8. APP_ENV: регистр; DEVELOPMENT при реальном usbrelay → STAGING
    #    (в режиме AUTO ничего не меняем: заглушка там не ставится, а наша заглушка удаляется)
    FINAL[APP_ENV]="${FINAL[APP_ENV]^^}"
    for n in "${defaulted[@]}"; do
        if [ "$n" = "APP_ENV" ]; then APP_ENV_DEFAULTED=true; fi
    done
    if [ "${FINAL[APP_ENV]}" = "DEVELOPMENT" ] && [ "$AUTO" != true ]; then
        relay_state
        if [ "$REPLY" = foreign ]; then
            if [ "$APP_ENV_DEFAULTED" = true ]; then
                note "APP_ENV defaults to DEVELOPMENT (first start), but $RELAY_BIN is a real usbrelay: stub not installed, APP_ENV becomes STAGING on the next start"
            else
                note "Warning: APP_ENV=DEVELOPMENT, but $RELAY_BIN is a real usbrelay. APP_ENV replaced with STAGING"
                FINAL[APP_ENV]="STAGING"
                APP_ENV_DOWNGRADED=true
            fi
        elif [ "$APP_ENV_DEFAULTED" = true ]; then
            note "APP_ENV not set: DEVELOPMENT by default (normal mode), the usbrelay stub will be offered"
        fi
    fi

    # 9. Экспорт (LANGUAGE не экспортируем: это переменная gettext, приложение читает её из .env)
    for n in "${OPT_NAMES[@]}"; do
        if [ "$n" != "LANGUAGE" ]; then export "$n=${FINAL[$n]}"; fi
    done
    export VERSION
    RUN_LOG="${RUN_LOG:-${FINAL[LOG_DIR]}/run_log.log}"
    export RUN_LOG
}

#################################### Согласие на первый старт ####################################
confirm_first_start() {
    msg first_title;  tty_out "$REPLY"
    msg first_python "${FINAL[PYTHON_VERSION]}";               tty_out "  - $REPLY"
    msg first_venv "${FINAL[VENV_DIR]}/${FINAL[VENV_NAME]}";   tty_out "  - $REPLY"
    msg first_env;                                             tty_out "  - $REPLY"
    msg first_logs "${FINAL[LOG_DIR]}";                        tty_out "  - $REPLY"
    msg first_db "${FINAL[DB_DIR]}/${FINAL[DB_NAME]}" "${FINAL[BACKUP]}"; tty_out "  - $REPLY"
    if [ "${FINAL[APP_ENV]}" = "DEVELOPMENT" ] && [ "$AUTO" != true ]; then
        msg first_stub "$RELAY_BIN"
        tty_out "  - $REPLY"
    fi
    note "First start: Python ${FINAL[PYTHON_VERSION]}, venv ${FINAL[VENV_DIR]}/${FINAL[VENV_NAME]}, .env, logs ${FINAL[LOG_DIR]}, database ${FINAL[DB_DIR]}/${FINAL[DB_NAME]}"
    if ask_confirm first_ask; then
        PRECONSENT=true
        note "First-start list approved"
        return 0
    fi
    msg first_declined
    printf '%s\n' "$REPLY" >&4
    exit 1
}

# .env после согласия: создать или обновить, проверить и очистить env.txt
finish_env_write() {
    HAVE_ENVF=true
    if verify_env_file; then
        clear_env_txt
    else
        note "Warning: the written .env failed verification, run/env.txt left unchanged"
    fi
}

handle_env_file() {
    local n need_update=false
    if [ "$HAVE_ENVF" = false ]; then
        if ask_listed q_envcreate; then
            write_env_file || die d_env_write "$ENV_FILE"
            note ".env created"
            finish_env_write
        else
            note ".env not created: values are used for this run only"
        fi
        return 0
    fi
    if [ "$FIXED" = true ]; then need_update=true; fi
    for n in "${REQ_NAMES[@]}" "${OPT_NAMES[@]}"; do
        if [ -z "${ENVF_VAL[$n]:-}" ]; then need_update=true; fi
    done
    if [ "$need_update" = true ]; then
        if [ "$AUTO" = true ]; then
            note "AUTO: .env lacks variables or they were corrected; the file is not changed, values are applied to this process"
        elif ask_confirm q_envrewrite; then
            write_env_file || die d_env_write "$ENV_FILE"
            note ".env updated"
            finish_env_write
        fi
    fi
    return 0
}

######################################## Старт ########################################
# Язык до чтения файлов: окружение → система
early_language

for arg in "$@"; do
    case "$arg" in
        -new|--new)   MODE_NEW=true ;;
        -calc|--calc) MODE_CALC=true ;;
        -h|--help)
            msg usage
            printf '%s\n' "$REPLY" >&3
            exit 0
            ;;
        *)
            msg bad_arg "$arg"
            printf '❌ %s\n' "$REPLY" >&4
            msg usage
            printf '%s\n' "$REPLY" >&4
            exit 1
            ;;
    esac
done
if [ "$MODE_NEW" = true ] && [ "$MODE_CALC" = true ]; then fail both_modes; fi
if [ "$MODE_CALC" = true ]; then
    [ -f "$CALC_FILE" ] || fail calc_missing "$CALC_FILE"
    if app_running; then fail app_running; fi
fi

note "RUN START"
if [ "$AUTO" = true ]; then note "Mode: automatic (server)"; else note "Mode: normal (questions in the terminal)"; fi

[ -f "$ENV_TXT" ] || fail no_env_txt "$ENV_TXT"
load_env_txt
case " ${REQ_NAMES[*]} " in
    *" VERSION "*) ;;
    *) fail no_version_section "$ENV_TXT" ;;
esac
if [ -f "$ENV_FILE" ]; then
    load_envf
    HAVE_ENVF=true
    note "Found $ENV_FILE"
else
    note "$ENV_FILE not found"
fi
early_language

if [ "$MODE_NEW" = true ]; then
    do_reset
    early_language
fi

detect_first_start
if [ "$FIRST_START" != true ]; then LOG_ALLOWED=true; fi

resolve_config

if [ "$FIRST_START" = true ]; then
    confirm_first_start
    LOG_ALLOWED=true
fi

handle_env_file

# APP_ENV DEVELOPMENT → STAGING: точечно, без вопросов (остальной .env не трогаем)
if [ "$APP_ENV_DOWNGRADED" = true ] && [ -f "$ENV_FILE" ] && [ "$AUTO" != true ]; then
    if set_app_env_in_file "STAGING"; then
        note "APP_ENV replaced with STAGING in $ENV_FILE"
    else
        note "Warning: could not update APP_ENV in $ENV_FILE"
    fi
fi

################################ Журнал и вывод ################################
open_log || die d_log "${RUN_LOG:-}"
exec 1>> "$RUN_LOG" 2>&1

LOG_DIR="${FINAL[LOG_DIR]}"
WORK_LOG="${FINAL[WORK_LOG]}"
API_LOG="${FINAL[API_LOG]}"
DB_DIR="${FINAL[DB_DIR]}"
BACKUP="${FINAL[BACKUP]}"
VENV_DIR="${FINAL[VENV_DIR]}"
VENV_NAME="${FINAL[VENV_NAME]}"
VENV_PATH="$VENV_DIR/$VENV_NAME"
PY="python${FINAL[PYTHON_VERSION]}"

############################ Папки и файлы логов/БД ############################
check_or_create_dir "$LOG_DIR"  || die d_dir "$LOG_DIR"
check_or_create_file "$WORK_LOG" "run/log.txt" || die d_file "$WORK_LOG"
check_or_create_file "$API_LOG"  "run/log.txt" || die d_file "$API_LOG"
check_or_create_dir "$DB_DIR"   || die d_dir "$DB_DIR"
check_or_create_dir "$BACKUP"   || die d_dir "$BACKUP"

############################ Реле usbrelay ############################
manage_relay_stub

########################### Проверка Python ###########################
if command -v "$PY" &>/dev/null; then
    echo "OK: $PY is already installed."
else
    echo "$PY not found."
    if [ "$AUTO" = true ]; then
        die d_py_auto "$PY"
    fi
    ask_listed q_python "$PY" || die d_py_cancel "$PY"
    run_sudo apt-get update
    run_sudo apt-get install -y software-properties-common
    run_sudo add-apt-repository -y ppa:deadsnakes/ppa
    run_sudo apt-get update
    run_sudo apt-get install -y "$PY" "${PY}-venv" "${PY}-dev"
fi

############################ Проверка пакетов ############################
install_package "python3-pip" "pip3 --version" || die d_pip
install_package "${PY}-venv ${PY}-dev" "$PY -c 'import ensurepip, venv'" || die d_venv_mod "$PY"

########################### Виртуальное окружение ###########################
check_or_create_dir "$VENV_DIR" || die d_dir "$VENV_DIR"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "Virtual environment $VENV_NAME does not exist."
    if ask_listed q_venv "$VENV_PATH"; then
        "$PY" -m venv "$VENV_PATH"
        echo "Virtual environment created in $VENV_PATH"
        # shellcheck disable=SC1091
        source "$VENV_PATH/bin/activate"
        if [ -f "requirements.txt" ]; then
            pip install -r requirements.txt
        fi
    else
        echo "Virtual environment not created."
    fi
else
    echo "Virtual environment $VENV_NAME already exists in $VENV_DIR"
fi

############################### Запуск приложения ###############################
if [ -f "$VENV_PATH/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_PATH/bin/activate"
fi

note "RUN run_program.py"
echo "################################----------- run_program.py #############################"
"$PY" run/run_program.py

note "RUN migrator.py"
echo "################################----------- migrator.py #############################"
"$PY" run/migrator.py

# Параметр -calc: резервная копия БД, расчёт и выход без запуска main.py
if [ "$MODE_CALC" = true ]; then
    note "Database backup before calculations"
    "$PY" -c "import sys; sys.path.insert(0, 'run'); import run_program as r; sys.exit(0 if r.create_backup(r.database_file, r.backup_dir) else 1)"
    note "RUN initial_calculations.py"
    echo "################################----------- initial_calculations.py #############################"
    PYTHONPATH="$DIR_PATH${PYTHONPATH:+:$PYTHONPATH}" "$PY" "$CALC_FILE"
    note "initial_calculations.py finished"
    trap - ERR
    exec 1>&3 2>&4 3>&- 4>&- 5<&-
    msg calc_done
    printf '%s\n' "$REPLY"
    exit 0
fi

note "RUN main.py"
# Восстановление стандартных потоков (systemd / консоль)
trap - ERR
exec 1>&3 2>&4 3>&- 4>&- 5<&-

echo "######################## Starting the main program: main.py ######################"
exec "$PY" -m app.main