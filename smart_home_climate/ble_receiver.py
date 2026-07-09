# python3 

import asyncio
import struct
from bleak import BleakClient
import logging
from settings import config

work_log = logging.getLogger(f"{config.work_log.name}.ble_receiver")
work_log.name = "ble_receiver"
# Использование: work_log.info("Сообщение")
work_log.info("Проверяю  наличие BLE-ресивера и его работоспособность...")

class XiaomiBLEReceiver:
    """Класс для опроса датчиков Xiaomi Mijia по протоколу BLE"""
    
    REALTIME_DATA_CHAR = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"

    def __init__(self, connection_timeout: float = 15.0, read_timeout: float = 10.0):
        self.connection_timeout = connection_timeout
        self.read_timeout = read_timeout

    @staticmethod
    def _parse_xiaomi_pack(data: bytes) -> tuple:
        """
        Разбор стандартного 5-байтового пакета LYWSD03MMC:
        Возвращает кортеж (temp, humi, voltage) или (None, None, None)
        """
        if len(data) >= 5:
            temp = struct.unpack("<h", data[0:2])[0] / 100.0
            humi = data[2]
            voltage = struct.unpack("<H", data[3:5])[0] / 1000.0
            return temp, humi, voltage
        return None, None, None

    async def get_sensor_data(self, mac_address: str) -> dict:
        """
        Подключение к датчику и получение одного замера данных.
        Возвращает словарь с параметрами при успехе, либо генерирует исключение.
        """
        data_received = asyncio.Event()
        result = {}
        
        # Защита от случайного создания кортежа из-за запятой
        mac = mac_address[0] if isinstance(mac_address, tuple) else mac_address
        mac = str(mac).strip()

        def notification_handler(sender, data: bytes):
            temp, humi, voltage = self._parse_xiaomi_pack(data)
            if temp is not None:
                result["temp"] = temp
                result["humi"] = humi
                result["voltage"] = voltage
                data_received.set()

        async with BleakClient(mac, timeout=self.connection_timeout) as client:
            if not client.is_connected:
                raise ConnectionError(f"Не удалось установить соединение")
            
            await client.start_notify(self.REALTIME_DATA_CHAR, notification_handler)
            try:
                await asyncio.wait_for(data_received.wait(), timeout=self.read_timeout)
            except asyncio.TimeoutError:
                raise TimeoutError("Превышено время ожидания данных от датчика")
            finally:
                await client.stop_notify(self.REALTIME_DATA_CHAR)
                
        return result