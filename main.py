#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

import math
import asyncio
import uvicorn
import logging
from datetime import datetime

from settings import config
from models import write_climate_data, get_average_difference_temp, get_latest_climate_data
import operations
from ble_receiver import XiaomiBLEReceiver
from api import app

work_log = logging.getLogger("climat_app.main")

receiver = XiaomiBLEReceiver()

print(f"main запущена. MODE = {config.MODE}.")

# data_sensors_all = {"street":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "basement":{"temp":0.0, "humi":0.0, "voltage":0.0}, 
#         "floor":{"temp":0.0, "humi":0.0, "voltage":0.0},
#         'difference_temp':0.0,
#         'average_temp':0.0,
#         'timestamp': ""
#         }

data_sensors_all = {}

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков и сохранение результатов в БД."""
    work_log.info("Запуск фонового циклического опроса датчиков...")

    while True:
        # Загрузка переменных из базы данных
        (DATE_SETINGS, MODE, INTERVAL_SECONDS, WEBSITE_RETURN_TIME,
             MAX_RETRIES, T_FLOOR_MAC_DIFF, ABSOLUTE_HUMIDITY_TOLERANCE, 
             MINIMUM_HUMIDITY, TARGET_RH, DANGEROUS_HUMIDITY, PRICE_GAS) = operations.settings_in_db()
        
        # Запрос ко всем датчикам.
        data_sensors_all = await receiver.sensor_get_sensors_all()

        # 2. Обработка собранных данных (после того, как опрос ВСЕХ датчиков завершен)
        if data_sensors_all:
            data_sensors_all['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Вычисление difference_temp в зависимости от режима работы
            if MODE == 'TWO_SENSORS':
                data_sensors_all['difference_temp'] = T_FLOOR_MAC_DIFF
            elif MODE == 'FLOOR':
                # Проверяем наличие необходимых данных перед расчетом
                if 'basement_temp' in data_sensors_all and 'floor_temp' in data_sensors_all:
                    data_sensors_all['difference_temp'] = round(
                        data_sensors_all['basement_temp'] - data_sensors_all['floor_temp'], 2
                    )
                    data_sensors_all['sensor_or_calc_street'] = True
                    data_sensors_all['sensor_or_calc_basement'] = True
                    data_sensors_all['sensor_or_calc_floor'] = True
                elif 'basement_temp' in data_sensors_all and not ('floor_temp' in data_sensors_all):
                    data_sensors_all['floor_temp'] = data_sensors_all['basement_temp'] - T_FLOOR_MAC_DIFF           
                    abs_basement_humi = operations.calculate_absolute_humidity(data_sensors_all['basement_temp'], data_sensors_all['basement_humi'])
                    data_sensors_all['floor_humi'] = operations.calculate_relative_humidity(data_sensors_all['floor_temp'], abs_basement_humi)
                    data_sensors_all['floor_voltage'] = 0.0
                    data_sensors_all['difference_temp'] = round(
                        data_sensors_all['basement_temp'] - data_sensors_all['floor_temp'], 2
                    )
                    data_sensors_all['sensor_or_calc_street'] = True
                    data_sensors_all['sensor_or_calc_basement'] = True
                    data_sensors_all['sensor_or_calc_floor'] = False
                else:
                    data_sensors_all['difference_temp'] = T_FLOOR_MAC_DIFF
                    work_log.warning("Расчет difference_temp невозможен: отсутствуют данные с датчикa basement")
            else: # MODE == 'SENSORS_ONE'
                data_sensors_all['difference_temp'] = T_FLOOR_MAC_DIFF
                data_sensors_all['average_temp'] = T_FLOOR_MAC_DIFF
                data_sensors_all['sensor_or_calc_street'] = False
                data_sensors_all['sensor_or_calc_basement'] = True
                data_sensors_all['sensor_or_calc_floor'] = False

            # Получение среднего исторического значения разницы температур из БД
            data_sensors_all['average_temp'] = get_average_difference_temp()
            
            print(f"Запись в БД: {data_sensors_all}") #TODO
        # 3. Запись датчиков в table_sensor_data         
            write_climate_data('table_sensor_data', data_sensors_all)          
########################################################################################
        # 4. Расчёт данных
            db_data ={}
            db_data['timestamp'] = data_sensors_all['timestamp']
            for name in config.sensor_name:
                # Расчет абсолютных влажностей
                db_data["a_" + name + "_humi"] = operations.calculate_absolute_humidity(data_sensors_all[name + "_temp"], data_sensors_all[name + "_humi"])
                # Расчет точек росы
                db_data["dp_" + name] = operations.calculate_dew_point(data_sensors_all[name + "_temp"], data_sensors_all[name + "_humi"])

            # Расчет проветривания с учетом абсолютной погрешности ABSOLUTE_HUMIDITY_TOLERANCE (0.5 г/м³)
            db_data['humidity_difference'] = round(db_data['a_basement_humi'] - db_data['a_street_humi'], 2)

            if db_data['humidity_difference'] >= ABSOLUTE_HUMIDITY_TOLERANCE:        
                db_data['vent_status'] = True
                if abs(data_sensors_all['basement_temp'] - data_sensors_all["street_temp"]):
                    db_data['vent_time_val'] = round(10.4 / math.sqrt(abs(data_sensors_all['basement_temp'] - data_sensors_all["street_temp"])))
                else:
                    db_data['vent_time_val'] = 0
            else:
                db_data['vent_status'] = False
                db_data['vent_time_val'] = 0
            
            # Моделирование замещения (Проветривание)
            db_data['sim_a_basement_humi'] = db_data['a_street_humi']
            db_data['sim_basement_humi'] = operations.calculate_relative_humidity(data_sensors_all['basement_temp'], db_data['sim_a_basement_humi'])
            db_data['sim_floor_humi'] = operations.calculate_relative_humidity(data_sensors_all['floor_temp'], db_data['sim_a_basement_humi'])

            # Расчет компенсационного нагрева (Отопление)
            db_data['heating_delta'] = 0.0

            if db_data['vent_status'] and db_data['sim_floor_humi'] > TARGET_RH:
                db_data['floor_temp_heated'], db_data['heating_delta'] = operations.calculating_temperature_from_humidity(data_sensors_all['floor_temp'], db_data['a_street_humi'])
                db_data['heat_status'] = True
                db_data['basement_temp_heated'] = round((data_sensors_all['basement_temp'] + db_data['heating_delta']), 1)
                db_data['basement_humi_heated'] = operations.calculate_relative_humidity(db_data['basement_temp_heated'], db_data['a_street_humi'])
                db_data['a_basement_humi_heated'] = db_data['a_street_humi']
                db_data['floor_humi_heated'] = operations.calculate_relative_humidity(db_data['floor_temp_heated'], db_data['a_street_humi'])
                db_data['a_floor_humi_heated'] = db_data['a_street_humi']

            elif not db_data['vent_status'] and data_sensors_all['floor_humi'] > TARGET_RH:
                db_data['floor_temp_heated'], db_data['heating_delta'] = operations.calculating_temperature_from_humidity(data_sensors_all['floor_temp'], db_data['a_floor_humi'])
                db_data['heat_status'] = True
                db_data['basement_temp_heated'] = round(data_sensors_all['basement_temp'] + db_data['heating_delta'], 1)
                db_data['basement_humi_heated'] = operations.calculate_relative_humidity(db_data['basement_temp_heated'], db_data['a_basement_humi'])
                db_data['a_basement_humi_heated'] = db_data['a_basement_humi']
                db_data['floor_humi_heated'] = operations.calculate_relative_humidity(db_data['floor_temp_heated'], db_data['a_floor_humi'])
                db_data['a_floor_humi_heated'] = db_data['a_floor_humi']
            else:
                db_data['heat_status'] = False
                db_data['heating_delta'] = 0.0
                db_data['basement_temp_heated'] = data_sensors_all['basement_temp']
                db_data['basement_humi_heated'] = data_sensors_all['basement_humi']
                db_data['a_basement_humi_heated'] = db_data['a_basement_humi']
                db_data['floor_temp_heated'] = data_sensors_all['floor_temp']
                db_data['floor_humi_heated'] = data_sensors_all['floor_humi']
                db_data['a_floor_humi_heated'] = db_data['a_floor_humi']
        # 5. Запись датчиков в api_table
            write_climate_data('api_table', db_data)

        # 6. Пауза
        work_log.info(f"Ожидание {INTERVAL_SECONDS} секунд до следующей итерации опроса...")
        print(f"Ожидание {INTERVAL_SECONDS} секунд до следующей итерации опроса...") # TODO
        await asyncio.sleep(INTERVAL_SECONDS)

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
