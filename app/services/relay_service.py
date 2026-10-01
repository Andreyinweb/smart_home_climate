import asyncio
from datetime import datetime
import logging
import shutil
import subprocess
from typing import Optional

from app.core.config import settings
import app.db.repository as db

logger = logging.getLogger("climat_app.relay_service")


class RelayError(Exception):
    """Базовое исключение модуля управления реле."""
    pass


class RelayDependencyError(RelayError):
    """Генерируется при отсутствии системной утилиты usbrelay."""
    pass


class RelayConfigError(RelayError):
    """Генерируется при ошибках конфигурации реле."""
    pass


class RelayExecutionError(RelayError):
    """Генерируется при сбоях выполнения системных команд usbrelay."""
    pass


class RelayParseError(RelayError):
    """Генерируется при нецелевом формате ответа утилиты usbrelay."""
    pass


class RelayController:
    """
    Класс управления USB-реле через системную утилиту usbrelay.
    Поддерживает асинхронные вызовы, инверсию логики (NO/NC),
    повторные попытки при сбоях USB, защиту котла от частого переключения
    и принудительное отключение при остановке приложения.
    """

    def __init__(
        self,
        relay_id: Optional[str] = None,
        inverted: Optional[bool] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        self._check_dependency()
        self.relay_id: str = (relay_id or settings.relay_id or "").strip()
        if not self.relay_id:
            raise RelayConfigError(
                "Идентификатор реле (RELAY_ID) не задан в конфигурации или переменных окружения."
            )

        self.inverted: bool = settings.relay_inverted if inverted is None else inverted
        self.timeout: float = settings.relay_timeout if timeout is None else timeout
        self.max_retries: int = settings.relay_max_retries if max_retries is None else max_retries

    @staticmethod
    def _check_dependency() -> None:
        """Проверяет наличие утилиты usbrelay в PATH."""
        if shutil.which("usbrelay") is None:
            raise RelayDependencyError(
                "Утилита 'usbrelay' не найдена в системном PATH. "
                "Установите её с помощью команды: sudo apt install usbrelay"
            )

    def _map_logical_to_physical(self, state: bool) -> int:
        """Транслирует логическое состояние прибора в физический сигнал (0 или 1)."""
        if self.inverted:
            return 0 if state else 1
        return 1 if state else 0

    def _map_physical_to_logical(self, physical_val: int) -> bool:
        """Преобразует физическое состояние реле (0 или 1) в логическое состояние прибора."""
        if self.inverted:
            return physical_val == 0
        return physical_val == 1

    def _exec_usbrelay_sync(self, args: list[str]) -> subprocess.CompletedProcess:
        """Синхронный запуск процесса usbrelay."""
        cmd = ["usbrelay"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )

    async def get_state(self) -> bool:
        """
        Возвращает текущее логическое состояние реле (True = включено, False = выключено).
        Выполняет парсинг stdout утилиты usbrelay.
        """
        try:
            result = await asyncio.to_thread(self._exec_usbrelay_sync, [])
        except subprocess.TimeoutExpired as e:
            logger.error(f"[USB-Relay] Таймаут чтения статуса реле (timeout={self.timeout}s).")
            raise RelayExecutionError(f"Превышено время ожидания ответа реле: {e}") from e
        except Exception as e:
            logger.error(f"[USB-Relay] Ошибка исполнения usbrelay: {e}")
            raise RelayExecutionError(f"Ошибка вызова системной утилиты: {e}") from e

        if result.returncode != 0:
            stderr_clean = result.stderr.strip()
            raise RelayExecutionError(
                f"Команда 'usbrelay' завершилась с ошибкой (code {result.returncode}): {stderr_clean}"
            )

        stdout_str = result.stdout.strip()
        target_prefix = f"{self.relay_id}="

        for line in stdout_str.splitlines():
            line = line.strip()
            if line.startswith(target_prefix):
                val_str = line[len(target_prefix):].strip()
                if val_str in ("1", "0"):
                    physical_val = int(val_str)
                    return self._map_physical_to_logical(physical_val)
                raise RelayParseError(f"Некорректное значение реле в строке '{line}'. Ожидалось 0 или 1.")

        raise RelayParseError(
            f"Идентификатор реле '{self.relay_id}' не найден в выводе usbrelay:\n{stdout_str}"
        )

    async def set_state(self, state: bool) -> bool:
        """
        Устанавливает логическое состояние реле с повторными попытками при сбоях связи по USB.
        """
        physical_val = self._map_logical_to_physical(state)
        arg = f"{self.relay_id}={physical_val}"

        last_exception: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    f"[USB-Relay] Попытка {attempt}/{self.max_retries}: установка state={state} (physical={physical_val})"
                )
                result = await asyncio.to_thread(self._exec_usbrelay_sync, [arg])

                if result.returncode == 0:
                    current_state = await self.get_state()
                    if current_state == state:
                        logger.info(f"[USB-Relay] Состояние реле '{self.relay_id}' успешно установлено в {state}.")
                        return current_state
                    else:
                        logger.warning(
                            f"[USB-Relay] Попытка {attempt}: команда state={state} отправлена, "
                            f"но фактический ответ {current_state}."
                        )
                else:
                    logger.warning(
                        f"[USB-Relay] Попытка {attempt}: usbrelay вернул код {result.returncode}. stderr: {result.stderr.strip()}"
                    )
            except (subprocess.TimeoutExpired, RelayExecutionError, RelayParseError) as e:
                last_exception = e
                logger.warning(f"[USB-Relay] Сбой USB на попытке {attempt}/{self.max_retries}: {e}")

            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * attempt)

        msg = f"Не удалось установить состояние state={state} для реле '{self.relay_id}' за {self.max_retries} попыток."
        logger.error(f"[USB-Relay] {msg}")
        if last_exception:
            raise RelayExecutionError(msg) from last_exception
        raise RelayExecutionError(msg)

    async def turn_on(self, min_off_interval: int = 180) -> bool:
        """
        Включает котел с проверкой минимального времени простоя (по умолчанию 180 сек / 3 мин).
        При успешном включении записывает timestamp_start в relay_table (id=1).
        """
        record = await db.get_record_by_id("relay_table", 1, pk_col="id")
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        if record and record.get("timestamp_stop"):
            try:
                last_stop = datetime.strptime(record["timestamp_stop"], "%Y-%m-%d %H:%M:%S")
                elapsed = (now - last_stop).total_seconds()
                if elapsed < min_off_interval:
                    remaining = int(min_off_interval - elapsed)
                    logger.warning(
                        f"[USB-Relay] Блокировка включения: с момента выключения прошло {int(elapsed)} с. "
                        f"Минимальный интервал простоя {min_off_interval} с. Повторите попытку через {remaining} с."
                    )
                    return False
            except ValueError as e:
                logger.error(f"[USB-Relay] Ошибка формата timestamp_stop в БД '{record.get('timestamp_stop')}': {e}")

        success = await self.set_state(True)
        if success:
            stop_ts = record.get("timestamp_stop") if record else None
            relay_data = {
                "id": 1,
                "timestamp_start": now_str,
                "timestamp_stop": stop_ts,
            }
            await db.upsert_record("relay_table", relay_data, pk_col="id")
            logger.info(f"[USB-Relay] Зафиксирован запуск котла в relay_table (id=1): timestamp_start={now_str}")
        return success

    async def turn_off(self, stop_programm: int = 0, min_on_interval: int = 180) -> bool:
        """
        Выключает котел.
        Если stop_programm == 0, проверяет минимальное время работы котла (180 сек / 3 мин).
        Если stop_programm != 0, выполняет принудительное аварийное отключение без проверок.
        При выключении записывает timestamp_stop в relay_table (id=1).
        """
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        record = await db.get_record_by_id("relay_table", 1, pk_col="id")

        if stop_programm == 0:
            if record and record.get("timestamp_start"):
                try:
                    last_start = datetime.strptime(record["timestamp_start"], "%Y-%m-%d %H:%M:%S")
                    elapsed = (now - last_start).total_seconds()
                    if elapsed < min_on_interval:
                        remaining = int(min_on_interval - elapsed)
                        logger.warning(
                            f"[USB-Relay] Блокировка выключения: с момента запуска прошло {int(elapsed)} с. "
                            f"Минимальный интервал работы {min_on_interval} с. Повторите попытку через {remaining} с."
                        )
                        return False
                except ValueError as e:
                    logger.error(f"[USB-Relay] Ошибка формата timestamp_start в БД '{record.get('timestamp_start')}': {e}")

        success = await self.set_state(False)
        if success or stop_programm != 0:
            start_ts = record.get("timestamp_start") if record else None
            relay_data = {
                "id": 1,
                "timestamp_start": start_ts,
                "timestamp_stop": now_str,
            }
            await db.upsert_record("relay_table", relay_data, pk_col="id")
            logger.info(
                f"[USB-Relay] Зафиксирована остановка котла в relay_table (id=1): "
                f"timestamp_stop={now_str} (stop_programm={stop_programm})"
            )
            return True
        return False