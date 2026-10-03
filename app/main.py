# app/main.py

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import AppEnv, settings
import app.services.logs_service as logs_service
import app.db.repository as db
from app.db.connection import get_db_connection
from app.dependencies import (
    get_relay_controller,
    get_repository,
    get_heating_controller,
    get_programmer,
)
from app.core.db_start_config import init_db_start_data
from app.routers import (
    dashboard_router,
    debug_router,
    gas_router,
    graphs_router,
    heating_router,
    settings_router,
    programmer_router
)

from app.services.ble_service import fetch_all_ble_sensors
from app.services.climate_service import build_sensor_record, build_api_record
from app.services import weather_service
from app.services import backup_service


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
    # Стартовые установки.
    relay_ctrl = get_relay_controller()
    await init_db_start_data()
    async def ble_polling_loop():
        while True:
            try:
                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                sys_settings = await db.get_or_create_settings(log_to_api=False)

                latest = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
                now_id = (latest["id"] + 1) if latest and "id" in latest else 1
                logs_service.set_current_cycle_id(now_id)

                work_log.info("[Цикл] Опрос BLE-датчиков...")
                ble_data = await asyncio.wait_for(fetch_all_ble_sensors(sys_settings), timeout=180.0)
                
                if ble_data:
                    ble_data["timestamp"] = timestamp_str

                    if ble_data.get("street_temp") is None or not ble_data.get("sensor_or_calc_street", True):
                        c_temp, c_rh, c_flag = await weather_service.get_calculated_street_climate(datetime.now().hour)
                        ble_data["street_temp"] = c_temp
                        ble_data["street_humi"] = c_rh
                        ble_data["sensor_or_calc_street"] = c_flag

                    avg_diff_temp = await db.get_aggregate("table_sensor_data", "difference_temp", "AVG") or 0.0
                    sensor_record = build_sensor_record(ble_data, sys_settings, avg_diff_temp)
                    sensor_record["id"] = now_id
                    await db.upsert_record("table_sensor_data", sensor_record, pk_col="id", log_to_api=False)

                    api_record = build_api_record(sensor_record, now_id, sys_settings)
                    await db.upsert_record("api_table", api_record, pk_col="id", log_to_api=False)

                    asyncio.create_task(weather_service.record_site_weather(timestamp_str, now_id))

                    work_log.info(f"[Цикл] Данные ID={now_id} успешно записаны в table_sensor_data и api_table.")

                    # Проверка условий автоматического управления отоплением в основном цикле
                    try:
                        repo = get_repository()
                        heating_ctrl = get_heating_controller(repo=repo, relay=relay_ctrl)
                        programmer = get_programmer(repo=repo, heating_controller=heating_ctrl)

                        # 1. Запуск логики программатора
                        await programmer.evaluate(sensor_record)

                        # 2. Защитная проверка пределов (минимум и максимум)
                        await heating_ctrl.check_temperature(sensor_record["basement_temp"])
                        await heating_ctrl.min_max_temperature(sensor_record)
                    except Exception as e:
                        work_log.error(f"[Цикл] Ошибка при проверке автоматики отопления: {e}")

                else:
                    work_log.warning("[Цикл] Данные с BLE-датчиков не получены.")

                await relay_ctrl.verification_relay()

                coeff_hour = await db.get_record_by_id("hourly_coefficients_table", int(timestamp_str[11:13]), pk_col="hour", log_to_api=False)
                updated_at_str = coeff_hour.get("updated_at") if coeff_hour else None

                if not updated_at_str or not updated_at_str.startswith(timestamp_str[:10]):
                    asyncio.create_task(weather_service.calibrate_hourly_coefficients())
                    await backup_service.create_backup_async(settings.db_path, settings.backup, max_backups=100, max_daily_backups=1)

            except asyncio.TimeoutError:
                work_log.error("[Цикл] Превышено время ожидания BLE-датчиков (Timeout).")
            except asyncio.CancelledError:
                work_log.info("[Цикл] Остановлена фоновая задача опроса BLE-датчиков.")
                break
            except Exception as e:
                work_log.error(f"[Цикл] Ошибка при опросе и расчете данных: {e}", exc_info=True)

            sys_settings = await db.get_or_create_settings(log_to_api=False)
            interval_settings = getattr(sys_settings, "interval_seconds", settings.interval_seconds)
            delta_time = round((datetime.now() - datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")).total_seconds())
            interval = 60 if (interval_settings - delta_time) < 60 else interval_settings - delta_time
            work_log.info(f"[Цикл] Ожидание до {datetime.now() + timedelta(seconds=interval):%H:%M:%S} (следующий опрос BLE-датчиков). Пауза в базе данных {interval_settings}")
            await asyncio.sleep(interval)

    polling_task = asyncio.create_task(ble_polling_loop())

    yield

    work_log.info("Остановка Smart Home Climate API")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    # Аварийное / программное выключение реле при остановке приложения
    try:
        work_log.info("[Lifespan] Выполнение принудительного выключения реле котла (stop_programm=1)...")
        await relay_ctrl.turn_off(stop_programm=1)
    except Exception as e:
        work_log.error(f"[Lifespan] Ошибка при аварийном выключении реле: {e}")

    await backup_service.create_backup_async(settings.db_path, settings.backup, max_backups=100)

    def _truncate_wal():
        try:
            with get_db_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as e:
            work_log.error(f"Ошибка при сбросе WAL-журнала: {e}")

    await asyncio.to_thread(_truncate_wal)


app = FastAPI(
    title="Smart Home Climate API",
    description="Сервер управления климатом",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(dashboard_router.router)
app.include_router(gas_router.router)
app.include_router(graphs_router.router)
app.include_router(settings_router.router)
app.include_router(heating_router.router)
app.include_router(programmer_router.router)

if settings.app_env == AppEnv.DEVELOPMENT:
    app.include_router(debug_router.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.server_host, port=settings.server_port, reload=True)





# # app/main.py

# import asyncio
# from contextlib import asynccontextmanager
# from datetime import datetime, timedelta
# import logging
# from fastapi import FastAPI
# from fastapi.staticfiles import StaticFiles

# from app.core.config import AppEnv, settings
# import app.services.logs_service as logs_service
# import app.db.repository as db
# # from app.core.db_start_config import init_db_start_data
# from app.db.connection import get_db_connection
# from app.dependencies import (
#     get_relay_controller,
#     get_repository,
#     get_heating_controller,
# )
# from app.core.db_start_config import init_db_start_data
# from app.routers import (
#     dashboard_router,
#     debug_router,
#     gas_router,
#     graphs_router,
#     heating_router,
#     settings_router,
#     programmer_router
# )

# from app.services.ble_service import fetch_all_ble_sensors
# from app.services.climate_service import build_sensor_record, build_api_record
# from app.services import weather_service
# from app.services import backup_service


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     work_log = logging.getLogger("climat_app.main")
#     work_log.info("-" * 80)
#     work_log.info(
#         f"Запуск Smart Home Climate API  app_env={settings.app_env.value}     "
#         f"sensor_mode={settings.sensor_mode.value}    site_weather={settings.site_weather.value}"
#     )
#     print(
#         f"Запуск Smart Home Climate API  app_env={settings.app_env.value}     "
#         f"sensor_mode={settings.sensor_mode.value}    site_weather={settings.site_weather.value}"
#     )
#     # Стартовые установки.
#     relay_ctrl = get_relay_controller()
#     await init_db_start_data()
#     async def ble_polling_loop():
#         while True:
#             try:
#                 timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#                 sys_settings = await db.get_or_create_settings(log_to_api=False)

#                 latest = await db.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
#                 now_id = (latest["id"] + 1) if latest and "id" in latest else 1
#                 logs_service.set_current_cycle_id(now_id)

#                 work_log.info("[Цикл] Опрос BLE-датчиков...")
#                 ble_data = await asyncio.wait_for(fetch_all_ble_sensors(sys_settings), timeout=180.0)
                
#                 if ble_data:
#                     ble_data["timestamp"] = timestamp_str

#                     if ble_data.get("street_temp") is None or not ble_data.get("sensor_or_calc_street", True):
#                         c_temp, c_rh, c_flag = await weather_service.get_calculated_street_climate(datetime.now().hour)
#                         ble_data["street_temp"] = c_temp
#                         ble_data["street_humi"] = c_rh
#                         ble_data["sensor_or_calc_street"] = c_flag

#                     avg_diff_temp = await db.get_aggregate("table_sensor_data", "difference_temp", "AVG") or 0.0
#                     sensor_record = build_sensor_record(ble_data, sys_settings, avg_diff_temp)
#                     sensor_record["id"] = now_id
#                     await db.upsert_record("table_sensor_data", sensor_record, pk_col="id", log_to_api=False)

#                     api_record = build_api_record(sensor_record, now_id, sys_settings)
#                     await db.upsert_record("api_table", api_record, pk_col="id", log_to_api=False)

#                     asyncio.create_task(weather_service.record_site_weather(timestamp_str, now_id))

#                     work_log.info(f"[Цикл] Данные ID={now_id} успешно записаны в table_sensor_data и api_table.")

#                     # Проверка условий автоматического управления отоплением в основном цикле
#                     try:
#                         repo = get_repository()
#                         heating_ctrl = get_heating_controller(repo=repo, relay=relay_ctrl)
#                         await heating_ctrl.min_max_temperature(sensor_record)
#                     except Exception as e:
#                         work_log.error(f"[Цикл] Ошибка при проверке автоматики отопления: {e}")

#                 else:
#                     work_log.warning("[Цикл] Данные с BLE-датчиков не получены.")

#                 await relay_ctrl.verification_relay()

#                 coeff_hour = await db.get_record_by_id("hourly_coefficients_table", int(timestamp_str[11:13]), pk_col="hour", log_to_api=False)
#                 updated_at_str = coeff_hour.get("updated_at") if coeff_hour else None

#                 if not updated_at_str or not updated_at_str.startswith(timestamp_str[:10]):
#                     asyncio.create_task(weather_service.calibrate_hourly_coefficients())
#                     await backup_service.create_backup_async(settings.db_path, settings.backup, max_backups=100, max_daily_backups=1)

#             except asyncio.TimeoutError:
#                 work_log.error("[Цикл] Превышено время ожидания BLE-датчиков (Timeout).")
#             except asyncio.CancelledError:
#                 work_log.info("[Цикл] Остановлена фоновая задача опроса BLE-датчиков.")
#                 break
#             except Exception as e:
#                 work_log.error(f"[Цикл] Ошибка при опросе и расчете данных: {e}", exc_info=True)

#             sys_settings = await db.get_or_create_settings(log_to_api=False)
#             interval_settings = getattr(sys_settings, "interval_seconds", settings.interval_seconds)
#             delta_time = round((datetime.now() - datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")).total_seconds())
#             interval = 60 if (interval_settings - delta_time) < 60 else interval_settings - delta_time
#             work_log.info(f"[Цикл] Ожидание до {datetime.now() + timedelta(seconds=interval):%H:%M:%S} (следующий опрос BLE-датчиков). Пауза в базе данных {interval_settings}")
#             await asyncio.sleep(interval)

#     polling_task = asyncio.create_task(ble_polling_loop())

#     yield

#     work_log.info("Остановка Smart Home Climate API")
#     polling_task.cancel()
#     try:
#         await polling_task
#     except asyncio.CancelledError:
#         pass

#     # Аварийное / программное выключение реле при остановке приложения
#     try:
#         work_log.info("[Lifespan] Выполнение принудительного выключения реле котла (stop_programm=1)...")
#         await relay_ctrl.turn_off(stop_programm=1)
#     except Exception as e:
#         work_log.error(f"[Lifespan] Ошибка при аварийном выключении реле: {e}")

#     await backup_service.create_backup_async(settings.db_path, settings.backup, max_backups=100)

#     def _truncate_wal():
#         try:
#             with get_db_connection() as conn:
#                 conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
#         except Exception as e:
#             work_log.error(f"Ошибка при сбросе WAL-журнала: {e}")

#     await asyncio.to_thread(_truncate_wal)


# app = FastAPI(
#     title="Smart Home Climate API",
#     description="Сервер управления климатом",
#     lifespan=lifespan,
# )

# app.mount("/static", StaticFiles(directory="static"), name="static")
# app.include_router(dashboard_router.router)
# app.include_router(gas_router.router)
# app.include_router(graphs_router.router)
# app.include_router(settings_router.router)
# app.include_router(heating_router.router)
# app.include_router(programmer_router.router)

# if settings.app_env == AppEnv.DEVELOPMENT:
#     app.include_router(debug_router.router)


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run("app.main:app", host=settings.server_host, port=settings.server_port, reload=True)