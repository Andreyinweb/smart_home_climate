# app/services/backup_service.py

import asyncio
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional, Union

from app.core.config import settings

work_log = logging.getLogger("climat_app.backup_service")


def create_backup(
    source_file: Optional[Union[str, Path]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    max_backups: int = 100,
) -> Optional[Path]:
    """
    Создает резервную копию файла базы данных и удаляет старые бэкапы.
    Если пути не переданы, берутся значения из конфигурации (settings.db_path, settings.backup).
    """
    try:
        src_path = Path(source_file) if source_file else settings.db_path
        dst_dir = Path(backup_dir) if backup_dir else settings.backup

        if not src_path.is_file():
            raise FileNotFoundError(f"Файл не найден: {src_path}")

        dst_dir.mkdir(parents=True, exist_ok=True)

        filename = src_path.name
        name, ext = src_path.stem, src_path.suffix

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = dst_dir / backup_name

        with open(src_path, "rb") as src, open(backup_path, "wb") as dst:
            dst.write(src.read())

        prefix = f"{name}_"
        backups = sorted(
            [f for f in dst_dir.iterdir() if f.is_file() and f.name.startswith(prefix) and f.name.endswith(ext)],
            key=lambda p: p.name,
        )

        if len(backups) > max_backups - 1:
            for old_backup in backups[:-max_backups]:
                old_backup.unlink()
                work_log.info(f"Удалён старый бэкап: {old_backup.name}")
                print(f"Удалён старый бэкап: {old_backup.name}")

        work_log.info(f"Резервная копия создана: {backup_path}")
        print(f"Резервная копия создана: {backup_path}")
        return backup_path

    except Exception as e:
        work_log.error(f"Ошибка при создании резервной копии: {e}")
        print(f"Ошибка: {e}")
        return None


async def create_backup_async(
    source_file: Optional[Union[str, Path]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    max_backups: int = 100,
) -> Optional[Path]:
    """
    Асинхронная обертка для вызова резервного копирования без блокировки event loop.
    """
    return await asyncio.to_thread(create_backup, source_file, backup_dir, max_backups)