# app/db/connection.py

import sqlite3
from contextlib import contextmanager
from typing import Generator
from app.core.config import settings


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Контекстный менеджер для подключения к базе данных SQLite.
    
    Автоматически активирует WAL-режим, поддержку внешних ключей (Foreign Keys)
    и приводит результаты выборки к формату sqlite3.Row.
    """
    conn = sqlite3.connect(
        settings.db_path,
        check_same_thread=False,
        timeout=10.0
    )
    conn.row_factory = sqlite3.Row
    
    try:
        # Включение внешних ключей и оптимизаций SQLite
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()