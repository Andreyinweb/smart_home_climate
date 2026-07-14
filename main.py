#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

import sys
import asyncio
import uvicorn
import logging
from datetime import datetime

from settings import config
from ble_receiver import XiaomiBLEReceiver
import operations
from api import app
from models import write_climate_data, get_average_difference_temp

work_log = logging.getLogger("climat_app.main")
work_log.info(f"Программа запущена. MODE = {config.MODE}.")
print(f"main запущена. MODE = {config.MODE}.")

receiver = XiaomiBLEReceiver()

# data_sensors_all = {"street":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "basement":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "floor":{"temp":0.0, "humi":0.0, "voltage":0.0},
#         "difference_temp":0.0,
#         "average_temp":0.0,
#         "timestamp": ""
#         }

data_sensors_all = {}

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков и сохранение результатов в БД."""
    work_log.info("Запуск фонового циклического опроса датчиков...")
    
    
    while True:
        # Запрос ко всем датчикам.
        data_sensors_all = await receiver.sensor_get_sensors_all()

        # 2. Обработка собранных данных (после того, как опрос ВСЕХ датчиков завершен)
        if data_sensors_all:
            data_sensors_all["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Вычисление difference_temp в зависимости от режима работы
            if config.MODE == "TWO_SENSORS":
                data_sensors_all["difference_temp"] = config.T_FLOOR_MAC_DIFF
            elif config.MODE == "FLOOR":
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

            print(f"Запись в БД: {data_sensors_all}") #TODO
        # 3. Запись датчиков в table_sensor_data
            
            try:
                success = write_climate_data("table_sensor_data", data_sensors_all)
                if success:
                    work_log.info("[БД] Данные успешно записаны в таблицу 'table_sensor_data'")
            except Exception as db_err:
                work_log.error(f"[БД] Ошибка подготовки данных для записи: {db_err}")
##########################################################################################################################################
        # 4. Расчёт данных
            db_data ={}
            db_data = dict(data_sensors_all)
            for name in config.sensor_name:
                # Расчет абсолютных влажностей
                db_data["a_" + name + "_humi"] = operations.calculate_absolute_humidity(db_data[name + "_temp"], db_data[name + "_humi"])
                # Расчет точек росы
                db_data["dp_" + name] = operations.calculate_dew_point(db_data[name + "_temp"], db_data[name + "_humi"])

            # Расчет проветривания с учетом абсолютной погрешности ABSOLUTE_HUMIDITY_TOLERANCE (0.5 г/м³)
            db_data["humidity_difference"] = round(db_data["a_basement_humi"] - db_data["a_street_humi"], 2)

            if db_data["humidity_difference"] >= config.ABSOLUTE_HUMIDITY_TOLERANCE:        
                db_data["vent_status"] = True
                if abs(db_data["basement_temp"] - db_data["street_temp"]):
                    db_data["vent_time_val"] = round(10.4 / math.sqrt(abs(db_data["basement_temp"] - db_data["street_temp"])))
                else:
                    db_data["vent_time_val"] = 0
            else:
                db_data["vent_status"] = False
                db_data["vent_time_val"] = 0
            
            # Моделирование замещения (Проветривание)
            db_data["sim_a_basement_humi"] = db_data["a_street_humi"]
            db_data["sim_basement_humi"] = operations.calculate_relative_humidity(db_data["basement_temp"], db_data["sim_a_basement_humi"])
            db_data["sim_floor_humi"] = operations.calculate_relative_humidity(db_data["floor_temp"], db_data["sim_a_basement_humi"])

            # Расчет компенсационного нагрева (Отопление)
            db_data["heating_delta"] = 0.0

            if db_data["vent_status"] and db_data["floor_humi"] > config.TARGET_RH:
                db_data["heat_status"] = True
                db_data["floor_temp_heated"], db_data["heating_delta"] = operations.calculating_temperature_from_humidity(db_data["floor_temp"], db_data["a_street_humi"])
                db_data["basement_temp_heated"] = round(db_data["basement_temp"] + db_data["heating_delta"], 1)
                db_data["basement_humi_heated"] = operations.calculate_relative_humidity(db_data["basement_temp_heated"], db_data["a_street_humi"])
                db_data["a_basement_humi_heated"] = db_data["a_street_humi"]
                db_data["floor_humi_heated"] = operations.calculate_relative_humidity(db_data["floor_temp_heated"], db_data["a_street_humi"])
                db_data["a_floor_humi_heated"] = db_data["a_street_humi"]

            elif not db_data["vent_status"] and db_data["floor_humi"] > config.TARGET_RH:
                db_data["heat_status"] = True
                db_data["floor_temp_heated"], db_data["heating_delta"] = operations.calculating_temperature_from_humidity(db_data["floor_temp"], db_data["a_floor_humi"])
                db_data["basement_temp_heated"] = round(db_data["basement_temp"] + db_data["heating_delta"], 1)
                db_data["basement_humi_heated"] = operations.calculate_relative_humidity(db_data["basement_temp_heated"], db_data["a_basement_humi"])
                db_data["a_basement_humi_heated"] = db_data["a_basement_humi"]
                db_data["floor_humi_heated"] = operations.calculate_relative_humidity(db_data["floor_temp_heated"], db_data["a_floor_humi"])
                db_data["a_floor_humi_heated"] = db_data["a_floor_humi"]
            else:
                db_data["heat_status"] = False
                db_data["basement_temp_heated"] = db_data["basement_temp"]
                db_data["basement_humi_heated"] = db_data["basement_humi"]
                db_data["a_basement_humi_heated"] = db_data["a_basement_humi"]
                db_data["floor_temp_heated"] = db_data["floor_temp"]
                db_data["floor_humi_heated"] = db_data["floor_humi"]
                db_data["a_floor_humi_heated"] = db_data["a_floor_humi"]
        # 5. Запись датчиков в api_table
            try:
                success = write_climate_data("api_table", db_data)
                if success:
                    work_log.info("[БД] Данные успешно записаны в таблицу 'api_table'")
            except Exception as db_err:
                work_log.error(f"[БД] Ошибка подготовки данных для записи: {db_err}")

        # 6. Пауза
        work_log.info(f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса...")
        print(f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса...")
        await asyncio.sleep(config.INTERVAL_SECONDS)

async def start_services():
    """Асинхронный запуск веб-сервера и фонового опроса одновременно."""
    server_config = uvicorn.Config(
        app=app, 
        host=config.SERVER_HOST, 
        port=config.SERVER_PORT, 
        loop="asyncio",
        log_config=None  # Отключаем дефолтный конфиг Uvicorn, сохраняя наши настройки логирования
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