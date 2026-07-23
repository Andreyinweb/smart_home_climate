# python3 ble_receiver.py

import asyncio
import struct
import logging
from bleak import BleakClient
from settings import config
import operations

work_log = logging.getLogger("climat_app.ble_receiver")


class XiaomiBLEReceiver:
    """Класс для опроса датчиков Xiaomi Mijia по протоколу BLE"""
    
    REALTIME_DATA_CHAR = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"

    def __init__(self, connection_timeout: float = 20.0, read_timeout: float = 15.0):
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

        try:
            async with BleakClient(mac, timeout=self.connection_timeout) as client:
                if not client.is_connected:
                    raise ConnectionError("Не удалось установить соединение")
                
                await client.start_notify(self.REALTIME_DATA_CHAR, notification_handler)
                try:
                    await asyncio.wait_for(data_received.wait(), timeout=self.read_timeout)
                except asyncio.TimeoutError:
                    raise TimeoutError("Превышено время ожидания данных от датчика")
                finally:
                    await client.stop_notify(self.REALTIME_DATA_CHAR)
        except asyncio.TimeoutError as e:
            # Ловим таймаут при попытке подключения в BleakClient
            raise TimeoutError("Превышено время ожидания при подключении к датчику") from e
        except Exception as e:
            # Оборачиваем остальные исключения, чтобы гарантировать наличие текста ошибки
            err_msg = str(e).strip()
            if not err_msg:
                err_msg = type(e).__name__
            raise Exception(err_msg) from e
      
        return result

    async def sensor_get_sensors_all(self):
        # Загрузка переменных из базы данных
        MAX_RETRIES = operations.settings_in_db()[4]
        data_sensors_all = {} 
        # 1. Сбор данных со всех датчиков
        for name in config.NAME_SENSOR_MAC:
            if config.MAC_DICT.get(name):                
                try:
                    data = {}
                    retries = 0
                    
                    # Опрос датчика с ограничением по количеству попыток
                    while "temp" not in data and retries < MAX_RETRIES:
                        retries += 1
                        try:
                            data = await self.get_sensor_data(config.MAC_DICT[name])
                        except Exception as sensor_err:
                            # Если у исключения нет строкового представления (типа TimeoutError), берем имя класса
                            err_msg = str(sensor_err).strip()
                            if not err_msg:
                                err_msg = type(sensor_err).__name__
                                
                            work_log.warning(f"[{name}] Попытка {retries} не удалась: {err_msg}")
                            await asyncio.sleep(1) # Короткая пауза перед повторной попыткой
                    
                    if data and "temp" in data and "humi" in data:
                        for sensor_variable in data: 
                            data_sensors_all[name[:-4].lower() + "_" + sensor_variable] = data[sensor_variable]
                        work_log.info(f"[{name}] Попытка {retries}. Данные: T={data['temp']}°C, H={data['humi']}%")
                    else:
                        work_log.error(f"[{name}] Не удалось получить данные за {retries} попыток.")
                        
                except Exception as e:
                    err_msg = str(e).strip() or type(e).__name__
                    work_log.error(f"[{name}] Попытка {retries}. Ошибка опроса в цикле: {err_msg}")
                    print(f"[{name}] Ошибка опроса в цикле: {err_msg}")
                
                await asyncio.sleep(2)  # Задержка между опросами датчиков в группе
        return data_sensors_all
