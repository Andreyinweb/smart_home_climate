# smart_home_climate/app/services/gas_engine.py

import calendar
from datetime import datetime
from typing import Any, Dict, Optional


class GasEngine:
    """Сервис вычисления расхода газа и теплофизических показателей."""

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