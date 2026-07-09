#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

import asyncio
import uvicorn
from settings import config, work_log
from api import app, shared_data
from models import write_climate_data

# Безопасный импорт BLE-ресивера
try:
    from ble_receiver import XiaomiBLEReceiver
except ImportError:
    # Заглушка-генератор эмуляции данных при локальном тестировании без BLE
    class XiaomiBLEReceiver:
        async def get_sensor_data(self, mac: str) -> dict:
            import random
            # Находим имя сенсора по MAC-адресу для корректной эмуляции
            sensor_type = "UNKNOWN"
            for key, val in config.TARGET_MAC_DICT.items():
                if val == mac:
                    sensor_type = key
                    break
            
            if sensor_type == "STREET":
                return {"temp": 0.48, "humi": 5.0, "voltage": 1.1}
            elif sensor_type == "BASEMENT":
                return {"temp": 0.2, "humi": 5.0, "voltage": 1.2}
            elif sensor_type == "FLOOR":
                return {"temp": 0.48, "humi": 5.0, "voltage": 1.3}
            return {"temp": 0.0, "humi": 0.0, "voltage": 0.0}

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков и сохранение результатов в БД."""
    receiver = XiaomiBLEReceiver()
    msg = "Запуск фонового циклического опроса датчиков..."
    print(msg)
    work_log.info(msg)
    
    while True:
        # Обходим датчики, настроенные в системе
        for name in config.NAME_SENSOR:
            mac = config.TARGET_MAC_DICT.get(name, "False")
            if not mac or mac == "False":
                continue  # Пропускаем отключенные датчики
                
            try:
                data = await receiver.get_sensor_data(mac)
                if data and "temp" in data and "humi" in data:
                    # Атомарное обновление разделяемого кэша для API
                    shared_data[mac] = {
                        "temp": data["temp"],
                        "humi": data["humi"],
                        "voltage": data.get("voltage", 0.0)
                    }
                    log_msg = f"[{name}] Данные обновлены: T={data['temp']}°C, H={data['humi']}%"
                    print(log_msg)
                    work_log.info(log_msg)
            except Exception as e:
                err_msg = f"[{name}] Ошибка опроса: {e}"
                print(err_msg)
                work_log.error(err_msg)
            
            await asyncio.sleep(2)  # Задержка между опросами датчиков в группе

        # После завершения опроса всех датчиков в группе выполняем запись в БД
        try:
            # Получение MAC-адресов из конфигурации
            street_mac = config.TARGET_MAC_DICT.get("STREET", "False")
            basement_mac = config.TARGET_MAC_DICT.get("BASEMENT", "False")
            floor_mac = config.TARGET_MAC_DICT.get("FLOOR", "False")

            # Получение данных по MAC-адресам
            u_data = shared_data.get(street_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if street_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}
            p_data = shared_data.get(basement_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if basement_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}
            s_data = shared_data.get(floor_mac, {"temp": 0.0, "humi": 0.0, "voltage": 0.0}) if floor_mac != "False" else {"temp": 0.0, "humi": 0.0, "voltage": 0.0}

            street_temp = u_data["temp"]
            street_humi = u_data["humi"]
            street_voltage = u_data.get("voltage", 0.0)

            basement_temp = p_data["temp"]
            basement_humi = p_data["humi"]
            basement_voltage = p_data.get("voltage", 0.0)

            floor_temp = s_data["temp"]
            floor_humi = s_data["humi"]
            floor_voltage = s_data.get("voltage", 0.0)

            # Вычисление дополнительных параметров
            difference_temp = round(street_temp - basement_temp, 2)
            average_temp = round((street_temp + basement_temp + floor_temp) / 3, 2)

            # Запись транзакции в SQLite
            success = write_climate_data(
                street_temp=street_temp,
                street_humi=street_humi,
                street_voltage=street_voltage,
                basement_temp=basement_temp,
                basement_humi=basement_humi,
                basement_voltage=basement_voltage,
                floor_temp=floor_temp,
                floor_humi=floor_humi,
                floor_voltage=floor_voltage,
                difference_temp=difference_temp,
                average_temp=average_temp
            )
            if success:
                db_msg = "[БД] Данные успешно записаны в таблицу 'table_climate'"
                print(db_msg)
                work_log.info(db_msg)
        except Exception as db_err:
            db_err_msg = f"[БД] Ошибка подготовки данных для записи: {db_err}"
            print(db_err_msg)
            work_log.error(db_err_msg)

        wait_msg = f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса..."
        print(wait_msg)
        work_log.info(wait_msg)
        await asyncio.sleep(config.INTERVAL_SECONDS)

async def start_services():
    """Асинхронный запуск веб-сервера и фонового опроса одновременно."""
    # Конфигурация запуска веб-сервера uvicorn внутри общего asyncio event loop
    server_config = uvicorn.Config(
        app=app, 
        host=config.SERVER_HOST, 
        port=config.SERVER_PORT, 
        loop="asyncio"
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
        term_msg = "Программа завершена пользователем."
        print(f"\n{term_msg}")
        work_log.info(term_msg)