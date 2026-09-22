# app/schemas/gas_schem.py
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class GasUpdateInputSchema(BaseModel):
    gas_meter: float = Field(..., gt=0, description="Текущее значение счетчика газа (м³)")
    start_of_month_gas_meter: Optional[float] = Field(
        None, ge=0, description="Показания счетчика на начало месяца (м³)"
    )

    @field_validator("gas_meter")
    @classmethod
    def validate_gas_meter(cls, v: float) -> float:
        return round(v, 3)

    @field_validator("start_of_month_gas_meter")
    @classmethod
    def validate_start_of_month(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return round(v, 3)
        return v


class GasRecordSchema(BaseModel):
    id: int
    timestamp: str
    gas_meter: Optional[float] = None
    gas_difference: Optional[float] = None
    start_of_month_gas_meter: Optional[float] = None
    average_street_temp: Optional[float] = None
    average_basement_temp: Optional[float] = None
    delta_T: Optional[float] = None
    gas_per_hour: Optional[float] = None
    gas_per_month: Optional[float] = None
    hot_water_per_month: Optional[float] = None
    hot_water_per_hour: Optional[float] = None
    coefficient_gas: Optional[float] = None
    price_gas: Optional[float] = None
    cost_of_gas: Optional[float] = None
    gas_forecast: Optional[float] = None
    projected_price: Optional[float] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True


class GasPageContextSchema(BaseModel):
    website_return_time: int = 60
    current_gas: str = "Не установлено"
    start_of_month_gas: str = "0.000 м³"
    gas_input_value: str = ""
    start_gas_input_value: str = ""
    gas_difference: str = "0.000 м³"
    cost_of_gas: str = "0.00"
    timestamp: str = "—"
    error: Optional[str] = None