#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

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
#         "average_temp":0.0
#         }

data_sensors_all = {}

# data_sensors_all["Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# write_climate_data(data_sensors_all) # TODO: YDALI
# exit()  # TODO: YDALI

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков и сохранение результатов в БД."""
    work_log.info("Запуск фонового циклического опроса датчиков...")
    
    while True:
        # Обходим датчики, настроенные в системе
        data_sensors_all = {}  # Сброс данных перед каждой итерацией опроса
        for name in config.NAME_SENSOR:
            if config.MAC_DICT[name]:                
                try:
                    data = {}
                    data["temp"] = False
                    while not data["temp"]: # TODO: Нужно ограничить количество. Надо в энв дописать количество запросов на один датчик, чтобы не зависать на одном датчике.
                        data = await receiver.get_sensor_data(config.MAC_DICT[name])
                        print(f"[{name}]: {data}")  # TODO: Удалить после тестирования
                        if data and "temp" in data and "humi" in data:
                            # Атомарное обновление разделяемого кэша для API
                            data_sensors_all[name.lower()] = data  # TODO: shared_data[config.MAC_DICT[name]] = data # 
                            work_log.info(f"[{name}] Данные обновлены: T={data['temp']}°C, H={data['humi']}%")
                    data_sensors_all["Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if config.MODE == "T_FLOOR_DIFF":
                        data_sensors_all["difference_temp"] = config.T_FLOOR_DIFF
                    elif config.MODE == "FLOOR":
                        data_sensors_all["difference_temp"] = data_sensors_all['basement']['temp'] - data_sensors_all['floor']['temp']
                    else:
                        data_sensors_all["difference_temp"] = config.T_FLOOR_DIFF
                        data_sensors_all["average_temp"] = config.T_FLOOR_DIFF
                    data_sensors_all["average_temp"] = get_average_difference_temp()
                except Exception as e:
                    work_log.error(f"[{name}] Ошибка опроса: {e}")
                    print(f"[{name}] Ошибка опроса: {e}")
                
                await asyncio.sleep(2)  # Задержка между опросами датчиков в группе

        # После завершения опроса всех датчиков в группе выполняем запись в БД
        try:
            print(data_sensors_all)
            # # Получение MAC-адресов из конфигурации
            # street_mac = config.MAC_DICT.get("STREET", "False")
            # basement_mac = config.MAC_DICT.get("BASEMENT", "False")
            # floor_mac = config.MAC_DICT.get("FLOOR", "False")

            # # Получение данных по MAC-адресам
            # u_data = shared_data.get(street_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if street_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}
            # p_data = shared_data.get(basement_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if basement_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}
            # s_data = shared_data.get(floor_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if floor_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}

            # street_temp = u_data["temp"]
            # street_humi = u_data["humi"]
            # street_voltage = u_data.get("voltage", 0.0)

            # basement_temp = p_data["temp"]
            # basement_humi = p_data["humi"]
            # basement_voltage = p_data.get("voltage", 0.0)

            # floor_temp = s_data["temp"]
            # floor_humi = s_data["humi"]
            # floor_voltage = s_data.get("voltage", 0.0)

            # # Вычисление дополнительных параметров
            # difference_temp = round(street_temp - basement_temp, 2)
            # average_temp = round((street_temp + basement_temp + floor_temp) / 3, 2)

            # # Запись транзакции в SQLite
            # success = write_climate_data(
            #     street_temp=street_temp,
            #     street_humi=street_humi,
            #     street_voltage=street_voltage,
            #     basement_temp=basement_temp,
            #     basement_humi=basement_humi,
            #     basement_voltage=basement_voltage,
            #     floor_temp=floor_temp,
            #     floor_humi=floor_humi,
            #     floor_voltage=floor_voltage,
            #     difference_temp=difference_temp,
            #     average_temp=average_temp
            # )
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
    # Запускаем uvicorn без дефолтной конфигурации логирования, чтобы применились наши глобальные настройки
    server_config = uvicorn.Config(
        app=app, 
        host=config.SERVER_HOST, 
        port=config.SERVER_PORT, 
        loop="asyncio"
        # log_config=None
    )
    server = uvicorn.Server(server_config)
    
    # Запуск конкурентных тасок в рамках одного процесса
    await asyncio.gather(
        server.serve(),
        polling_task()
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        work_log.info("Программа завершена пользователем.")