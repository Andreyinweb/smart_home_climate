# app/main.py

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
import app.db.repository as db
from app.routers import dashboard, gas, graphs, setting, heating

from app.services.ble_service import fetch_all_ble_sensors
from app.services.climate_engine import build_sensor_record, build_api_record
from app.services import weather_service


async def check_and_run_calibration():
    """Проверяет необходимость перерасчета коэффициентов в 00:00."""
    now = datetime.now()
    coeff_0 = await db.get_record_by_id("hourly_coefficients_table", 0, pk_col="hour", log_to_api=False)
    updated_at_str = coeff_0.get("updated_at") if coeff_0 else None
    today_str = now.strftime("%Y-%m-%d")
    if not updated_at_str or not updated_at_str.startswith(today_str):
        await weather_service.calibrate_hourly_coefficients()


@asynccontextmanager
async def lifespan(app: FastAPI):
    work_log = logging.getLogger("climat_app.main")
    work_log.info("-" * 80)
    work_log.info(
        f"Запуск Smart Home Climate API  app_env={settings.app_env.value}     "
        f"sensor_mode={settings.sensor_mode.value}    site_weather={settings.site_weather.value}"
    )
    print(
        f"Запуск Smart Home Climate API  app_env={settings.app_env.value}     "
        f"sensor_mode={settings.sensor_mode.value}    site_weather={settings.site_weather.value}"
    )

    async def ble_polling_loop():
        while True:
            interval = settings.interval_seconds
            try:
                sys_settings = await db.get_or_create_settings(log_to_api=False)
                interval = getattr(sys_settings, "interval_seconds", settings.interval_seconds)

                latest = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
                now_id = (latest["id"] + 1) if latest and "id" in latest else 1

                work_log.info("[Цикл] Опрос BLE-датчиков...")
                ble_data = await asyncio.wait_for(fetch_all_ble_sensors(sys_settings), timeout=180.0)

                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if ble_data:
                    ble_data["timestamp"] = timestamp_str

                    if ble_data.get("street_temp") is None or not ble_data.get("sensor_or_calc_street", True):
                        c_temp, c_rh, c_flag = await weather_service.get_calculated_street_climate(datetime.now().hour)
                        ble_data["street_temp"] = c_temp
                        ble_data["street_humi"] = c_rh
                        ble_data["sensor_or_calc_street"] = c_flag

                    # 1. Запись в table_sensor_data
                    avg_diff_temp = await db.get_aggregate("table_sensor_data", "difference_temp", "AVG") or 0.0
                    sensor_record = build_sensor_record(ble_data, sys_settings, avg_diff_temp)
                    await db.upsert_record("table_sensor_data", sensor_record, pk_col="id", log_to_api=False)

                    # 2. Запись в api_table
                    api_record = build_api_record(sensor_record, now_id, sys_settings)
                    await db.upsert_record("api_table", api_record, pk_col="id", log_to_api=False)

                    # 3. Асинхронная запись погоды (ждет появления now_id в table_sensor_data)
                    asyncio.create_task(weather_service.record_site_weather(timestamp_str, now_id))

                    work_log.info(f"[Цикл] Данные ID={now_id} успешно записаны в table_sensor_data и api_table.")
                else:
                    work_log.warning("[Цикл] Данные с BLE-датчиков не получены.")

                # Вызов проверки ежедневной калибровки
                await check_and_run_calibration()

            except asyncio.TimeoutError:
                work_log.error("[Цикл] Превышено время ожидания BLE-датчиков (Timeout).")
            except asyncio.CancelledError:
                work_log.info("[Цикл] Остановлена фоновая задача опроса BLE-датчиков.")
                break
            except Exception as e:
                work_log.error(f"[Цикл] Ошибка при опросе и расчете данных: {e}", exc_info=True)
            work_log.info(f"[Цикл] Ожидание {interval} секунд до следующего опроса BLE-датчиков...")
            await asyncio.sleep(interval)

    polling_task = asyncio.create_task(ble_polling_loop())

    yield

    work_log.info("Остановка Smart Home Climate API")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Smart Home Climate API",
    description="Сервер управления климатом",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(dashboard.router)
app.include_router(gas.router)
app.include_router(graphs.router)
app.include_router(setting.router)
app.include_router(heating.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.server_host, port=settings.server_port, reload=True)