#  python3 main.py  # Точка входа для запуска сервера и фонового опроса

import asyncio
import uvicorn
from api import app, shared_data
import config

# Безопасный импорт BLE-ресивера
try:
    from ble_receiver import XiaomiBLEReceiver
except ImportError:
    # Заглушка-генератор эмуляции данных при локальном тестировании без BLE
    class XiaomiBLEReceiver:
        async def get_sensor_data(self, mac: str) -> dict:
            import random
            if mac == "A4:C1:38:53:82:0F": # Улица
                return {"temp": 0.48, "humi": 5.0, "voltage": 1}
            elif mac == "A4:C1:38:51:C3:0D": # Подвал
                return {"temp": 0.2, "humi": 5.0, "voltage": 1}
            else: # Спальня (кухня)
                return {"temp": 0.48, "humi": 5.0, "voltage": 1}

async def polling_task():
    """Фоновый асинхронный опрос BLE датчиков."""
    receiver = XiaomiBLEReceiver()
    print("Запуск фонового циклического опроса датчиков...")
    
    while True:
        for mac in config.TARGET_MAC_LIST:
            name = config.NAME_SENSOR.get(mac, mac)
            try:
                data = await receiver.get_sensor_data(mac)
                if data and "temp" in data and "humi" in data:
                    # Атомарное обновление разделяемого кэша для API
                    shared_data[mac] = {
                        "temp": data["temp"],
                        "humi": data["humi"],
                        "voltage": data.get("voltage", 0.0)
                    }
                    print(f"[{name}] Данные обновлены: T={data['temp']}°C, H={data['humi']}%")
            except Exception as e:
                print(f"[{name}] Ошибка опроса: {e}")
            
            await asyncio.sleep(2)  # Задержка между опросами датчиков в группе

        print(f"Ожидание {config.INTERVAL_SECONDS} секунд до следующей итерации опроса...")
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
        print("\nПрограмма завершена пользователем.")