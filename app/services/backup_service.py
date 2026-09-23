# app/services/backup_service.py

import asyncio
import logging
from pathlib import Path
import sqlite3
from datetime import datetime
from typing import Optional, Union

from app.core.config import settings

work_log = logging.getLogger("climat_app.backup_service")


def create_backup(
    source_file: Optional[Union[str, Path]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    max_backups: int = 100,
) -> Optional[Path]:
    """
    Создает горячую резервную копию SQLite через Online Backup API,
    корректно обрабатывая WAL-журнал и гарантированно закрывая соединения.
    """
    src_conn = None
    dst_conn = None
    try:
        src_path = Path(source_file) if source_file else settings.db_path
        dst_dir = Path(backup_dir) if backup_dir else settings.backup

        if not src_path.is_file():
            raise FileNotFoundError(f"Файл БД не найден: {src_path}")

        dst_dir.mkdir(parents=True, exist_ok=True)

        name, ext = src_path.stem, src_path.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = dst_dir / f"{name}_{timestamp}{ext}"

        # Открытие соединения с исходной БД в режиме чтения
        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)

        # Принудительный сброс WAL-журнала в основной файл БД перед снятием копии
        try:
            src_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        except Exception as e:
            work_log.warning(f"Не удалось выполнить wal_checkpoint: {e}")

        # Открытие соединения с целевым файлом резервной копии
        dst_conn = sqlite3.connect(backup_path)

        with dst_conn:
            src_conn.backup(dst_conn)

        # Ротация старых бэкапов
        prefix = f"{name}_"
        backups = sorted(
            [f for f in dst_dir.iterdir() if f.is_file() and f.name.startswith(prefix) and f.name.endswith(ext)],
            key=lambda p: p.name,
        )

        if len(backups) > max_backups - 1:
            for old_backup in backups[:-max_backups]:
                old_backup.unlink()
                work_log.info(f"Удалён старый бэкап: {old_backup.name}")

        work_log.info(f"Резервная копия успешно создана: {backup_path}")
        return backup_path

    except Exception as e:
        work_log.error(f"Ошибка при создании резервной копии: {e}")
        return None

    finally:
        # Гарантированное закрытие подключений при любом исходе
        if dst_conn:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn:
            try:
                src_conn.close()
            except Exception:
                pass


async def create_backup_async(
    source_file: Optional[Union[str, Path]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    max_backups: int = 100,
) -> Optional[Path]:
    return await asyncio.to_thread(create_backup, source_file, backup_dir, max_backups)









# # app/services/backup_service.py

# import asyncio
# import logging
# from pathlib import Path
# import sqlite3
# from datetime import datetime
# from typing import Optional, Union

# from app.core.config import settings

# work_log = logging.getLogger("climat_app.backup_service")


# def create_backup(
#     source_file: Optional[Union[str, Path]] = None,
#     backup_dir: Optional[Union[str, Path]] = None,
#     max_backups: int = 100,
# ) -> Optional[Path]:
#     """
#     Создает горячую резервную копию SQLite через Online Backup API,
#     корректно обрабатывая WAL-журнал и блокировки записи.
#     """
#     try:
#         src_path = Path(source_file) if source_file else settings.db_path
#         dst_dir = Path(backup_dir) if backup_dir else settings.backup

#         if not src_path.is_file():
#             raise FileNotFoundError(f"Файл БД не найден: {src_path}")

#         dst_dir.mkdir(parents=True, exist_ok=True)

#         filename = src_path.name
#         name, ext = src_path.stem, src_path.suffix

#         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#         backup_path = dst_dir / f"{name}_{timestamp}{ext}"

#         # Горячее копирование SQLite (безопасно при параллельной записи)
#         src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
#         dst_conn = sqlite3.connect(backup_path)

#         with dst_conn:
#             src_conn.backup(dst_conn)

#         dst_conn.close()
#         src_conn.close()

#         # Ротация старых бэкапов
#         prefix = f"{name}_"
#         backups = sorted(
#             [f for f in dst_dir.iterdir() if f.is_file() and f.name.startswith(prefix) and f.name.endswith(ext)],
#             key=lambda p: p.name,
#         )

#         if len(backups) > max_backups - 1:
#             for old_backup in backups[:-max_backups]:
#                 old_backup.unlink()
#                 work_log.info(f"Удалён старый бэкап: {old_backup.name}")

#         work_log.info(f"Резервная копия успешно создана: {backup_path}")
#         return backup_path

#     except Exception as e:
#         work_log.error(f"Ошибка при создании резервной копии: {e}")
#         return None


# async def create_backup_async(
#     source_file: Optional[Union[str, Path]] = None,
#     backup_dir: Optional[Union[str, Path]] = None,
#     max_backups: int = 100,
# ) -> Optional[Path]:
#     return await asyncio.to_thread(create_backup, source_file, backup_dir, max_backups)