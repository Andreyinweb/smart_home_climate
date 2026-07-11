#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

import sys
import asyncio
import uvicorn
import logging
from datetime import datetime

from settings import config
from ble_receiver import XiaomiBLEReceiver
from api import app, shared_data
from models import write_climate_data, get_average_difference_temp

work_log = logging.getLogger(f"{config.work_log.name}.main")
work_log.name = "main"
work_log.info(f"Программа запущена. MODE = {config.MODE}.")
print(f"main запущена. MODE = {config.MODE}.")

receiver = XiaomiBLEReceiver()

# data_sensors_all = {"street":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "basement":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "floor":{"temp":0.0, "humi":0.0, "voltage":0.0},
#         "difference_temp":0.0,
#         "average_temp":0.0,
#         "Date": ""
#         }

data_sensors_all = {}

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков и сохранение результатов в БД."""
    work_log.info("Запуск фонового циклического опроса датчиков...")
    
    
    while True:
        data_sensors_all = {}  # Сброс данных перед каждой итерацией опроса
        
        # 1. Сбор данных со всех датчиков
        for name in config.NAME_SENSOR:
            if config.MAC_DICT[name]:                
                try:
                    data = {}
                    data["temp"] = False
                    retries = 0
                    
                    # Опрос датчика с ограничением по количеству попыток
                    while not data["temp"] and retries < config.MAX_RETRIES:
                        retries += 1
                        try:
                            data = await receiver.get_sensor_data(config.MAC_DICT[name])
                            print(f"[{name}] Попытка {retries}: {data}")  # TODO: Удалить после тестирования
                        except Exception as sensor_err:
                            work_log.warning(f"[{name}] Попытка {retries} не удалась: {sensor_err}")
                            await asyncio.sleep(1) # Короткая пауза перед повторной попыткой
                    
                    if data and "temp" in data and "humi" in data:
                        data_sensors_all[name[:-4].lower()] = data
                        work_log.info(f"[{name}] Данные успешно получены: T={data['temp']}°C, H={data['humi']}%")
                    else:
                        work_log.error(f"[{name}] Не удалось получить данные за {config.MAX_RETRIES} попыток.")
                        
                except Exception as e:
                    work_log.error(f"[{name}] Ошибка опроса в цикле: {e}")
                    print(f"[{name}] Ошибка опроса в цикле: {e}")
                
                await asyncio.sleep(2)  # Задержка между опросами датчиков в группе

        # 2. Обработка собранных данных (после того, как опрос ВСЕХ датчиков завершен)
        if data_sensors_all:
            data_sensors_all["Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Вычисление difference_temp в зависимости от режима работы
            if config.MODE == "T_FLOOR_MAC_DIFF":
                data_sensors_all["difference_temp"] = config.T_FLOOR_MAC_DIFF
            elif config.MODE == "FLOOR_MAC":
                # Проверяем наличие необходимых данных перед расчетом
                if 'basement' in data_sensors_all and 'floor' in data_sensors_all:
                    data_sensors_all["difference_temp"] = round(
                        data_sensors_all['basement']['temp'] - data_sensors_all['floor']['temp'], 2
                    )
                else:
                    data_sensors_all["difference_temp"] = 0.0
                    work_log.warning("Расчет difference_temp невозможен: отсутствуют данные с датчиков basement или floor")
            else:
                data_sensors_all["difference_temp"] = config.T_FLOOR_MAC_DIFF
                data_sensors_all["average_temp"] = config.T_FLOOR_MAC_DIFF

            # Получение среднего исторического значения разницы температур из БД
            data_sensors_all["average_temp"] = get_average_difference_temp()

            # 3. Запись транзакции в SQLite
            try:
                print(f"Запись в БД: {data_sensors_all}")
                success = write_climate_data(data_sensors_all)
                if success:
                    work_log.info("[БД] Данные успешно записаны в таблицу 'table_climate'")
            except Exception as db_err:
                work_log.error(f"[БД] Ошибка подготовки данных для записи: {db_err}")

        work_log.info(f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса...")
        print(f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса...")
        await asyncio.sleep(config.INTERVAL_SECONDS)

async def start_services():
    """Асинхронный запуск веб-сервера и фонового опроса одновременно."""
    server_config = uvicorn.Config(
        app=app, 
        host=config.SERVER_HOST, 
        port=config.SERVER_PORT, 
        loop="asyncio"
    )
    server = uvicorn.Server(server_config)
    
    await asyncio.gather(
        server.serve(),
        polling_task()
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        work_log.info("Программа завершена пользователем.")