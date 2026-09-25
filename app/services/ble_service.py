# app/services/ble_service.py

import asyncio
import logging
import struct
from typing import Any, Dict, Optional, Tuple

from bleak import BleakClient

from app.core.config import settings as config_settings
from app.schemas.schema_settings import SystemSettings

work_log = logging.getLogger("climat_app.ble_service")

# UUID характеристики получения показаний в реальном времени Xiaomi LYWSD03MMC
REALTIME_DATA_CHAR = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"


def _parse_xiaomi_packet(data: bytes) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Разбор 5-байтового пакета Xiaomi LYWSD03MMC (температура, влажность, напряжение).
    
    Структура пакета:
    - Байты 0-1: Температура (signed short, x100, little-endian)
    - Байт 2: Относительная влажность (unsigned char)
    - Байты 3-4: Напряжение батареи (unsigned short, mV, x1000, little-endian)
    """
    if len(data) >= 5:
        try:
            temp = struct.unpack("<h", data[0:2])[0] / 100.0
            humi = float(data[2])
            voltage = struct.unpack("<H", data[3:5])[0] / 1000.0
            return round(temp, 1), round(humi, 1), round(voltage, 3)
        except Exception as e:
            work_log.debug(f"Ошибка распаковки BLE-пакета: {e}")
            return None, None, None
    return None, None, None


async def read_single_sensor(
    mac_address: str, 
    connection_timeout: float = 15.0, 
    read_timeout: float = 10.0
) -> Dict[str, float]:
    """
    Подключается к BLE-датчику по MAC-адресу и считывает текущие климатические параметры.
    
    Returns:
        Dict с ключами 'temp', 'humi', 'voltage'.
    """
    data_received = asyncio.Event()
    result: Dict[str, float] = {}
    mac = str(mac_address).strip()

    def notification_handler(_, data: bytes):
        temp, humi, voltage = _parse_xiaomi_packet(data)
        if temp is not None:
            result["temp"] = temp
            result["humi"] = humi
            result["voltage"] = voltage
            data_received.set()

    async with BleakClient(mac, timeout=connection_timeout) as client:
        if not client.is_connected:
            raise ConnectionError("Соединение с BLE-устройством не установлено")

        await client.start_notify(REALTIME_DATA_CHAR, notification_handler)
        try:
            await asyncio.wait_for(data_received.wait(), timeout=read_timeout)
        finally:
            await client.stop_notify(REALTIME_DATA_CHAR)

    return result


async def fetch_all_ble_sensors(sys_settings: SystemSettings) -> Dict[str, Any]:
    """
    Опрашивает все активные датчики согласно sys_settings.mode и mac_dict из конфигурации.
    
    Возвращает словарь с ключами формата:
    {sensor_name}_temp, {sensor_name}_humi, {sensor_name}_voltage.
    """
    # Выделяем список датчиков в нижнем регистре (например: ['basement', 'street', 'floor'])
    sensor_names = [part.strip().lower() for part in sys_settings.mode.split("_") if part.strip()]
    
    # Считываем словарь MAC-адресов {'basement': '...', 'street': '...', ...}
    mac_dict = config_settings.mac_dict

    all_data: Dict[str, Any] = {}
    successful_sensors = []

    for sensor_name in sensor_names:
        # Ищем MAC в mac_dict или напрямую через атрибут <sensor>_mac в config_settings
        mac = mac_dict.get(sensor_name) or getattr(config_settings, f"{sensor_name}_mac", None)

        if not mac:
            work_log.warning(f"[{sensor_name}] MAC-адрес не найден в конфигурации.")
            continue

        data = {}
        retries = 0

        while "temp" not in data and retries < sys_settings.max_retries:
            retries += 1
            try:
                data = await read_single_sensor(mac)
            except Exception as e:
                err_msg = str(e).strip() or type(e).__name__
                work_log.debug(f"[{sensor_name}] Попытка {retries}/{sys_settings.max_retries} не удалась: {err_msg}")
                await asyncio.sleep(1)

        if data and "temp" in data:
            for key, val in data.items():
                all_data[f"{sensor_name}_{key}"] = val
            successful_sensors.append(sensor_name)
            work_log.debug(
                f"[{sensor_name}] T={data['temp']}°C, H={data['humi']}%, V={data['voltage']}V (попытка {retries})"
            )
        else:
            work_log.error(f"[{sensor_name}] Не удалось получить данные за {retries} попыток.")

        await asyncio.sleep(1)

    if successful_sensors:
        work_log.info(f"Датчики [{', '.join(successful_sensors)}]: значения получены.")
    else:
        work_log.error("Ни с одного BLE-датчика не удалось получить данные.")

    return all_data