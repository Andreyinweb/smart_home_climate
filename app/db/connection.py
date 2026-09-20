# app/db/connection.py

import sqlite3
from contextlib import contextmanager
from typing import Generator
from app.core.config import settings


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Контекстный менеджер для подключения к базе данных SQLite.
    
    Автоматически активирует WAL-режим и приводит результаты выборки
    к формату sqlite3.Row для удобного преобразования в Pydantic-модели.
    """
    conn = sqlite3.connect(
        settings.db_path,
        check_same_thread=False,
        timeout=10.0
    )
    conn.row_factory = sqlite3.Row
    
    try:
        # Оптимизации работы SQLite
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()