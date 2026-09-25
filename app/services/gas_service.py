# app/services/gas_service.py
import calendar
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import Depends

from app.core.config import settings
from app.db.repository import BaseRepository, get_repository
from app.schemas.gas_schema import GasUpdateInputSchema

logger = logging.getLogger("api_app.services.gas")


class GasEngineService:
    def __init__(self, repo: BaseRepository = Depends(get_repository)):
        self.repo = repo

    @staticmethod
    def calculate_hours_passed(timestamp_str: str) -> float:
        """Количество часов, прошедших с начала месяца до указанной даты."""
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            hours = (dt.day - 1) * 24 + dt.hour + dt.minute / 60.0 + dt.second / 3600.0
            return max(0.0, hours)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def get_days_in_month(timestamp_str: str) -> int:
        """Количество дней в месяце для указанной даты."""
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            return calendar.monthrange(dt.year, dt.month)[1]
        except (ValueError, TypeError):
            return 30

    @classmethod
    def calculate_full_record(
        cls,
        record_id: int,
        timestamp_str: str,
        gas_meter: float,
        start_of_month_gas_meter: float,
        price_gas: float,
        hot_water_per_hour: float,
        avg_street_temp: Optional[float] = None,
        avg_basement_temp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Расчет всех 17 полей для записи в gas_table."""
        days_in_month = cls.get_days_in_month(timestamp_str)
        hours_passed = cls.calculate_hours_passed(timestamp_str)

        gas_difference = round(gas_meter - start_of_month_gas_meter, 3)
        hot_water_per_month = round(hot_water_per_hour * 24 * days_in_month, 3)

        avg_street = avg_street_temp if avg_street_temp is not None else 0.0
        avg_basement = avg_basement_temp if avg_basement_temp is not None else 0.0
        delta_t = round(avg_basement - avg_street, 2)

        if hours_passed > 0:
            gas_per_hour_raw = (gas_difference / hours_passed) - hot_water_per_hour
            gas_per_hour = max(0.0, round(gas_per_hour_raw, 3))
        else:
            gas_per_hour = 0.0

        gas_per_month = round(gas_per_hour * 24 * days_in_month, 3)

        if delta_t != 0.0:
            coefficient_gas = round(gas_per_month / delta_t, 3)
        else:
            coefficient_gas = 0.0

        cost_of_gas = round(gas_difference * price_gas, 2)
        gas_forecast = round(gas_per_month + hot_water_per_month, 2)
        projected_price = round(gas_forecast * price_gas, 2)

        return {
            "id": record_id,
            "timestamp": timestamp_str,
            "gas_meter": gas_meter,
            "start_of_month_gas_meter": start_of_month_gas_meter,
            "gas_difference": gas_difference,
            "average_street_temp": avg_street_temp,
            "average_basement_temp": avg_basement_temp,
            "delta_T": delta_t,
            "gas_per_hour": gas_per_hour,
            "gas_per_month": gas_per_month,
            "hot_water_per_month": hot_water_per_month,
            "hot_water_per_hour": hot_water_per_hour,
            "coefficient_gas": coefficient_gas,
            "price_gas": price_gas,
            "cost_of_gas": cost_of_gas,
            "gas_forecast": gas_forecast,
            "projected_price": projected_price,
        }

    async def get_gas_page_context(self, error: Optional[str] = None) -> Dict[str, Any]:
        sys_settings = await self.repo.get_or_create_settings(log_to_api=False)
        website_return_time = getattr(sys_settings, "website_return_time", 60)
        price_gas = getattr(sys_settings, "price_gas", 0.0) or 0.0

        config_start_gas = getattr(
            settings,
            "start_of_month_gas_meter",
            getattr(settings, "START_OF_MONTH_GAS_METER", getattr(settings, "START_GAS", 0.0)),
        )
        latest_gas = await self.repo.get_latest_record("gas_table", order_by_col="id", log_to_api=False)

        if not latest_gas:
            gas_display = "Не установлено"
            start_gas_val = config_start_gas
            start_gas_display = f"{start_gas_val:.3f} м³"
            gas_input_val = ""
            start_gas_input_val = f"{start_gas_val:.3f}"
            timestamp_val = "Первое число текущего месяца"
            gas_diff_display = "0.000 м³"
            cost_display = "0.00"
        else:
            gas_val = latest_gas.get("gas_meter")
            start_gas_val = latest_gas.get("start_of_month_gas_meter")

            if start_gas_val is None:
                start_gas_val = config_start_gas

            gas_display = f"{gas_val:.3f} м³" if gas_val is not None else "Не установлено"
            start_gas_display = f"{start_gas_val:.3f} м³" if start_gas_val is not None else "0.000 м³"
            gas_input_val = f"{gas_val:.3f}" if gas_val is not None else ""
            start_gas_input_val = f"{start_gas_val:.3f}" if start_gas_val is not None else ""
            timestamp_val = latest_gas.get("timestamp", "—")

            gas_diff = latest_gas.get("gas_difference")
            if gas_diff is None and gas_val is not None and start_gas_val is not None:
                gas_diff = round(gas_val - start_gas_val, 3)

            gas_diff_display = f"{gas_diff:.3f} м³" if gas_diff is not None else "0.000 м³"

            cost_val = latest_gas.get("cost_of_gas")
            if cost_val is None and gas_diff is not None:
                cost_val = round(gas_diff * price_gas, 2)

            cost_display = f"{cost_val:.2f}" if cost_val is not None else "0.00"

        return {
            "website_return_time": website_return_time,
            "current_gas": gas_display,
            "start_of_month_gas": start_gas_display,
            "gas_input_value": gas_input_val,
            "start_gas_input_value": start_gas_input_val,
            "gas_difference": gas_diff_display,
            "cost_of_gas": cost_display,
            "timestamp": timestamp_val,
            "error": error,
        }

    async def update_gas_meter(self, input_dto: GasUpdateInputSchema) -> Dict[str, Any]:
        gas_meter = input_dto.gas_meter
        start_of_month_input = input_dto.start_of_month_gas_meter

        latest_sensor = await self.repo.get_latest_record("table_sensor_data", order_by_col="id", log_to_api=False)
        if not latest_sensor or "id" not in latest_sensor or "timestamp" not in latest_sensor:
            raise ValueError("Таблица table_sensor_data пуста. Невозможно привязать показания.")

        sensor_id = latest_sensor["id"]
        timestamp_str = latest_sensor["timestamp"]
        target_month = timestamp_str[:7]

        latest_gas = await self.repo.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
        if latest_gas and latest_gas.get("gas_meter") is not None:
            last_gas_meter = float(latest_gas["gas_meter"])
            if gas_meter < last_gas_meter:
                raise ValueError(
                    f"Введенное значение ({gas_meter:.3f}) меньше последнего записанного ({last_gas_meter:.3f})"
                )

        records_this_month = await self.repo.fetch_by_date(
            "gas_table", target_date=target_month, interval_type="month", order_asc=True, log_to_api=False
        )

        table_start_gas = latest_gas.get("start_of_month_gas_meter") if latest_gas else None
        config_start_gas = getattr(
            settings,
            "start_of_month_gas_meter",
            getattr(settings, "START_OF_MONTH_GAS_METER", getattr(settings, "START_GAS", 0.0)),
        )

        if start_of_month_input is not None:
            start_gas = start_of_month_input
        elif table_start_gas is not None:
            start_gas = float(table_start_gas)
        else:
            start_gas = float(config_start_gas)

        if records_this_month:
            first_record_month = records_this_month[0]
            first_gas_meter = first_record_month.get("gas_meter")
            if first_gas_meter is not None and start_gas > float(first_gas_meter):
                raise ValueError(
                    f"Значение на начало месяца ({start_gas:.3f}) превышает первое записанное показание месяца ({first_gas_meter:.3f})"
                )

        sys_settings = await self.repo.get_or_create_settings(log_to_api=False)
        price_gas = float(getattr(sys_settings, "price_gas", 0.0) or 0.0)
        hot_water_per_hour = float(getattr(sys_settings, "hot_water_per_hour", 0.0) or 0.0)

        if start_of_month_input is not None and records_this_month:
            for rec in records_this_month:
                rec_id = rec["id"]
                rec_ts = rec["timestamp"]
                rec_gas_meter = float(rec.get("gas_meter", 0.0))
                rec_month = rec_ts[:7]

                rec_avg_street = await self.repo.get_aggregate(
                    "table_sensor_data", "street_temp", function="AVG", interval_type="month", target_time=rec_month
                )
                rec_avg_basement = await self.repo.get_aggregate(
                    "table_sensor_data", "basement_temp", function="AVG", interval_type="month", target_time=rec_month
                )

                updated_rec = self.calculate_full_record(
                    record_id=rec_id,
                    timestamp_str=rec_ts,
                    gas_meter=rec_gas_meter,
                    start_of_month_gas_meter=start_gas,
                    price_gas=price_gas,
                    hot_water_per_hour=hot_water_per_hour,
                    avg_street_temp=rec_avg_street,
                    avg_basement_temp=rec_avg_basement,
                )
                await self.repo.upsert_record("gas_table", updated_rec, pk_col="id", log_to_api=False)

        avg_street_temp = await self.repo.get_aggregate(
            "table_sensor_data", "street_temp", function="AVG", interval_type="month", target_time=target_month
        )
        avg_basement_temp = await self.repo.get_aggregate(
            "table_sensor_data", "basement_temp", function="AVG", interval_type="month", target_time=target_month
        )

        record_to_write = self.calculate_full_record(
            record_id=sensor_id,
            timestamp_str=timestamp_str,
            gas_meter=gas_meter,
            start_of_month_gas_meter=start_gas,
            price_gas=price_gas,
            hot_water_per_hour=hot_water_per_hour,
            avg_street_temp=avg_street_temp,
            avg_basement_temp=avg_basement_temp,
        )

        await self.repo.upsert_record("gas_table", record_to_write, pk_col="id", log_to_api=False)
        logger.info("Успешно обновлен и рассчитан счетчик газа: %s м³ (id: %s)", gas_meter, sensor_id)
        return record_to_write

    async def get_gas_table_context(self) -> Dict[str, Any]:
        sys_settings = await self.repo.get_or_create_settings(log_to_api=False)
        website_return_time = getattr(sys_settings, "website_return_time", 60)

        latest_gas = await self.repo.get_latest_record("gas_table", order_by_col="id", log_to_api=False)
        gas_data = dict(latest_gas) if latest_gas else {}

        return {
            "website_return_time": website_return_time,
            "gas_data": gas_data,
        }