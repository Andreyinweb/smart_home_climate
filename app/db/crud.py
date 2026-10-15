# app/db/crud.py

"""
Универсальный слой доступа к данным SQLite.

Четыре функции работают с любой таблицей. Режим работы определяется
переданными параметрами. У каждой функции есть синхронная версия (`*_sync`,
ядро) и асинхронная обёртка поверх неё через asyncio.to_thread.

Публичный интерфейс:
- get(table, pk=None, pk_col="id", where=None, start=None, stop=None, order_col=None, order_asc=True, limit=None, offset=None, conn=None, log_to_api=False) -> List[Dict[str, Any]]: Выборка строк. Всегда возвращает список словарей.
- upsert(table, rows, pk_col="id", conn=None, log_to_api=False) -> int: Вставка или обновление списка строк. Возвращает число затронутых строк.
- delete(table, pk=None, pk_col="id", where=None, conn=None, log_to_api=False) -> int: Удаление по ключу, списку ключей или условию. Возвращает число удалённых строк.
- query(sql, params=(), conn=None, log_to_api=False) -> List[Dict[str, Any]]: Любой SQL-запрос (тексты запросов лежат в app/db/queries.py).

Транзакция: передайте одно соединение в несколько вызовов.

    with get_db_connection() as conn:
        upsert_sync("table_a", rows_a, conn=conn)
        delete_sync("table_b", pk=[1, 2], conn=conn)
    # commit один раз при выходе из блока, при ошибке откат всего

Если `conn` передан, функция не делает commit и не закрывает соединение.
Если не передан, открывает своё через get_db_connection() (commit на каждый вызов).

Безопасность:
- Значения передаются только плейсхолдерами "?" / именованными параметрами.
- Имена таблиц и колонок проверяются на допустимые символы (_check_identifier).
- SQL в query() принимается только из кода, никогда из пользовательского ввода.

TODO: добавить белый список таблиц и колонок в _check_identifier.
"""

import asyncio
import logging
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

from app.db.connection import get_db_connection

work_log = logging.getLogger("climat_app.crud")
api_log = logging.getLogger("api_app.crud")

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LIST_TYPES = (list, tuple, set, frozenset)


# --- Внутренние помощники ---

def _logger(log_to_api: bool) -> logging.Logger:
    """Возвращает api_log (True) или work_log (False)."""
    return api_log if log_to_api else work_log


def _check_identifier(name: str) -> str:
    """
    Проверяет имя таблицы или колонки и возвращает его без изменений.

    TODO: заменить проверкой по белому списку таблиц и колонок.

    :param name: Имя таблицы или колонки.
    :return: То же имя, если оно допустимо.
    :raises ValueError: Если имя содержит недопустимые символы.
    """
    if not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Недопустимое имя таблицы или колонки: {name!r}")
    return name


@contextmanager
def _use_conn(conn: Optional[sqlite3.Connection]) -> Generator[sqlite3.Connection, None, None]:
    """
    Отдаёт переданное соединение либо открывает собственное.

    Чужое соединение не коммитится и не закрывается: этим управляет вызывающий код.
    """
    if conn is not None:
        yield conn
    else:
        with get_db_connection() as own_conn:
            yield own_conn


def _conditions(pk: Any, pk_col: str, where: Optional[Dict[str, Any]]) -> Tuple[List[str], List[Any]]:
    """
    Собирает условия WHERE по ключу (скаляр или список) и словарю равенств.

    :param pk: Значение ключа, список значений или None.
    :param pk_col: Колонка первичного ключа.
    :param where: Словарь {колонка: значение}. Значение None даёт `IS NULL`.
    :return: Кортеж (список условий, список параметров).
    """
    conds: List[str] = []
    params: List[Any] = []

    if pk is not None:
        col = _check_identifier(pk_col)
        if isinstance(pk, _LIST_TYPES):
            values = list(pk)
            if values:
                conds.append(f"{col} IN ({', '.join('?' * len(values))})")
                params.extend(values)
            else:
                conds.append("1 = 0")  # пустой список ключей: ничего не найдено
        else:
            conds.append(f"{col} = ?")
            params.append(pk)

    for key, value in (where or {}).items():
        col = _check_identifier(key)
        if value is None:
            conds.append(f"{col} IS NULL")
        else:
            conds.append(f"{col} = ?")
            params.append(value)

    return conds, params


# --- Синхронное ядро ---

def get_sync(
    table: str,
    pk: Any = None,
    pk_col: str = "id",
    where: Optional[Dict[str, Any]] = None,
    start: Any = None,
    stop: Any = None,
    order_col: Optional[str] = None,
    order_asc: bool = True,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    """
    Синхронно выбирает строки таблицы. Всегда возвращает список словарей.

    Режим определяется параметрами:
    - нет pk, where, start, stop: последняя строка по order_col (по умолчанию pk_col),
      сортировка DESC; limit=N вернёт последние N строк;
    - pk: строка по ключу, либо строки по списку ключей (IN);
    - where: фильтр по равенству колонок (значение None даёт IS NULL);
    - start / stop: диапазон по order_col, границы включительно;
    - условия комбинируются через AND; без limit возвращаются все подходящие строки.

    :param table: Имя таблицы.
    :param pk: Значение ключа или список значений.
    :param pk_col: Колонка первичного ключа.
    :param where: Словарь {колонка: значение}.
    :param start: Нижняя граница диапазона по order_col.
    :param stop: Верхняя граница диапазона по order_col.
    :param order_col: Колонка сортировки и диапазона (по умолчанию pk_col).
    :param order_asc: Сортировка ASC (True) или DESC (False). В режиме «последняя строка» всегда DESC.
    :param limit: Максимум строк.
    :param offset: Смещение (для пагинации).
    :param conn: Внешнее соединение для транзакции.
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Список словарей, при отсутствии строк пустой список.
    """
    logger = _logger(log_to_api)
    table = _check_identifier(table)
    order = _check_identifier(order_col or pk_col)

    conds, params = _conditions(pk, pk_col, where)
    if start is not None:
        conds.append(f"{order} >= ?")
        params.append(start)
    if stop is not None:
        conds.append(f"{order} <= ?")
        params.append(stop)

    latest_mode = not conds
    direction = "DESC" if (latest_mode or not order_asc) else "ASC"
    if latest_mode and limit is None:
        limit = 1

    sql = f"SELECT * FROM {table}"
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += f" ORDER BY {order} {direction}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    elif offset is not None:
        sql += " LIMIT -1"  # SQLite требует LIMIT перед OFFSET
    if offset is not None:
        sql += " OFFSET ?"
        params.append(int(offset))

    with _use_conn(conn) as c:
        rows = [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]
    logger.debug(f"get '{table}': {len(rows)} строк.")
    return rows


def upsert_sync(
    table: str,
    rows: List[Dict[str, Any]],
    pk_col: str = "id",
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> int:
    """
    Синхронно вставляет строки, а при конфликте по pk_col обновляет их (UPSERT).

    Колонки берутся из ключей первого словаря, у остальных набор ключей должен
    совпадать. Если в словарях только pk_col, при конфликте строка не меняется.
    Все строки пишутся одним executemany.

    :param table: Имя таблицы.
    :param rows: Список словарей {колонка: значение}, даже если строка одна.
    :param pk_col: Колонка, по которой определяется конфликт.
    :param conn: Внешнее соединение для транзакции.
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Число затронутых строк (0 при пустом списке).
    :raises TypeError: Если rows не список словарей.
    :raises ValueError: Если у словарей разный набор ключей.
    """
    logger = _logger(log_to_api)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise TypeError("rows должен быть списком словарей.")
    if not rows:
        return 0

    table = _check_identifier(table)
    pk = _check_identifier(pk_col)
    cols = list(rows[0].keys())
    if not cols:
        return 0
    for name in cols:
        _check_identifier(name)
    if any(set(r.keys()) != set(cols) for r in rows):
        raise ValueError("У всех строк в rows должен быть одинаковый набор колонок.")

    placeholders = ", ".join(f":{c}" for c in cols)
    update_cols = [c for c in cols if c != pk]
    if update_cols:
        update_str = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
        conflict = f"DO UPDATE SET {update_str}"
    else:
        conflict = "DO NOTHING"
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) {conflict};"
    )

    with _use_conn(conn) as c:
        count = c.executemany(sql, rows).rowcount
    logger.debug(f"upsert '{table}': {count} строк.")
    return count


def delete_sync(
    table: str,
    pk: Any = None,
    pk_col: str = "id",
    where: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> int:
    """
    Синхронно удаляет строки по ключу, списку ключей или условию.

    Условия pk и where комбинируются через AND. Вызов без pk и без where
    отклоняется, чтобы случайно не очистить таблицу (для этого есть query).

    :param table: Имя таблицы.
    :param pk: Значение ключа или список значений.
    :param pk_col: Колонка первичного ключа.
    :param where: Словарь {колонка: значение} (None даёт IS NULL).
    :param conn: Внешнее соединение для транзакции.
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Число удалённых строк.
    :raises ValueError: Если не передан ни pk, ни where.
    """
    logger = _logger(log_to_api)
    table = _check_identifier(table)
    conds, params = _conditions(pk, pk_col, where)
    if not conds:
        raise ValueError("delete требует pk или where.")

    sql = f"DELETE FROM {table} WHERE " + " AND ".join(conds) + ";"
    with _use_conn(conn) as c:
        count = c.execute(sql, tuple(params)).rowcount
    logger.debug(f"delete '{table}': {count} строк.")
    return count


def query_sync(
    sql: str,
    params: Any = (),
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    """
    Синхронно выполняет любой одиночный SQL-оператор.

    Принимает SELECT, WITH, INSERT, UPDATE, DELETE, PRAGMA и т.д. Один вызов
    выполняет один оператор (sqlite3 не принимает несколько через `;`):
    для цепочки операций делайте несколько вызовов с одним conn.
    Текст SQL должен приходить только из кода (app/db/queries.py), не из пользовательского ввода.

    :param sql: Текст запроса с плейсхолдерами "?" или ":name".
    :param params: Кортеж или словарь параметров для одного выполнения,
                   либо список кортежей для executemany.
    :param conn: Внешнее соединение для транзакции.
    :param log_to_api: Использовать api_log (True) или work_log (False).
    :return: Список словарей, если оператор вернул строки, иначе пустой список.
    """
    logger = _logger(log_to_api)
    with _use_conn(conn) as c:
        if isinstance(params, list):
            cursor = c.executemany(sql, params)
        else:
            cursor = c.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()] if cursor.description is not None else []
    logger.debug(f"query: {len(rows)} строк.")
    return rows


# --- Асинхронные обёртки ---

async def get(
    table: str,
    pk: Any = None,
    pk_col: str = "id",
    where: Optional[Dict[str, Any]] = None,
    start: Any = None,
    stop: Any = None,
    order_col: Optional[str] = None,
    order_asc: bool = True,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    """Асинхронная обёртка над get_sync (параметры и логика те же)."""
    return await asyncio.to_thread(
        get_sync, table, pk, pk_col, where, start, stop, order_col, order_asc, limit, offset, conn, log_to_api
    )


async def upsert(
    table: str,
    rows: List[Dict[str, Any]],
    pk_col: str = "id",
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> int:
    """Асинхронная обёртка над upsert_sync (параметры и логика те же)."""
    return await asyncio.to_thread(upsert_sync, table, rows, pk_col, conn, log_to_api)


async def delete(
    table: str,
    pk: Any = None,
    pk_col: str = "id",
    where: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> int:
    """Асинхронная обёртка над delete_sync (параметры и логика те же)."""
    return await asyncio.to_thread(delete_sync, table, pk, pk_col, where, conn, log_to_api)


async def query(
    sql: str,
    params: Any = (),
    conn: Optional[sqlite3.Connection] = None,
    log_to_api: bool = False,
) -> List[Dict[str, Any]]:
    """Асинхронная обёртка над query_sync (параметры и логика те же)."""
    return await asyncio.to_thread(query_sync, sql, params, conn, log_to_api)