# app/core/db_settings.py

"""
Доступ к системным настройкам в БД (settings_table) через app/db/crud.py.

Замена функций get_settings_db / update_settings из app/db/repository.py.

Публичный интерфейс:
- get_settings_db(log_to_api=False) -> Optional[SystemSettings]: Чтение настроек (id=1).
- update_settings(update_dto, settings_id=1, log_to_api=False) -> Optional[SystemSettings]: Частичное обновление настроек.

Отличия от repository.py:
- Если записи нет, функции возвращают None (раньше SystemSettings() без аргументов
  падал с ValidationError, так как у большинства полей нет значений по умолчанию).
- В update_settings данные валидируются ДО записи в БД: некорректное значение
  (например, явный None) не попадёт в таблицу, ValidationError пробрасывается вызывающему.
"""

import logging
from datetime import datetime
from typing import Optional

from app.db import crud
from app.schemas.settings_schema import SystemSettings, SystemSettingsUpdate

work_log = logging.getLogger("climat_app.db_settings")
api_log = logging.getLogger("api_app.db_settings")


def _logger(log_to_api: bool) -> logging.Logger:
    """Возвращает api_log (True) или work_log (False)."""
    return api_log if log_to_api else work_log


async def _read_settings(settings_id: int, log_to_api: bool) -> Optional[SystemSettings]:
    """
    Читает запись настроек по id и валидирует её через SystemSettings.

    :param settings_id: Идентификатор записи настроек.
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Объект SystemSettings или None, если записи нет.
    :raises pydantic.ValidationError: Если запись в БД не проходит валидацию (например, есть NULL).
    """
    rows = await crud.get("settings_table", pk=settings_id, pk_col="id", log_to_api=log_to_api)
    if not rows:
        _logger(log_to_api).warning(f"Запись настроек id={settings_id} в 'settings_table' не найдена.")
        return None
    return SystemSettings.model_validate(rows[0])


async def get_settings_db(log_to_api: bool = False) -> Optional[SystemSettings]:
    """
    Получает системные настройки (запись id=1) из базы данных.

    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Объект SystemSettings или None, если записи нет.
    :raises pydantic.ValidationError: Если запись в БД некорректна.
    """
    return await _read_settings(1, log_to_api)


async def update_settings(
    update_dto: SystemSettingsUpdate,
    settings_id: int = 1,
    log_to_api: bool = False,
) -> Optional[SystemSettings]:
    """
    Частично обновляет системные настройки: меняются только явно переданные поля DTO.

    Порядок: чтение текущей записи, наложение изменений, обновление timestamp,
    валидация, запись (upsert). Если DTO пустой, запись в БД не выполняется.

    :param update_dto: DTO с изменяемыми полями.
    :param settings_id: Идентификатор записи настроек (по умолчанию 1).
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Обновлённый SystemSettings; текущий, если изменений нет; None, если записи нет.
    :raises pydantic.ValidationError: Если итоговые данные некорректны (в БД ничего не пишется).
    """
    logger = _logger(log_to_api)

    current = await _read_settings(settings_id, log_to_api)
    if current is None:
        logger.error(f"Обновление настроек невозможно: запись id={settings_id} отсутствует.")
        return None

    changes = update_dto.model_dump(exclude_unset=True)
    if not changes:
        return current

    data = current.model_dump()
    data.update(changes)
    data["id"] = settings_id
    data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    updated = SystemSettings.model_validate(data)

    await crud.upsert("settings_table", [updated.model_dump()], pk_col="id", log_to_api=log_to_api)
    logger.debug(f"Настройки id={settings_id} обновлены: {sorted(changes)}.")
    return updated