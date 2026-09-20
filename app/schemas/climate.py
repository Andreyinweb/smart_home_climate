# app/schemas/climate.py
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SensorReading(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    timestamp: str
    street_temp: Optional[float] = None
    basement_temp: Optional[float] = None
    floor_temp: Optional[float] = None
    difference_temp: Optional[float] = None
    average_temp: Optional[float] = None
    street_humi: Optional[float] = None
    basement_humi: Optional[float] = None
    floor_humi: Optional[float] = None
    street_voltage: Optional[float] = None
    basement_voltage: Optional[float] = None
    floor_voltage: Optional[float] = None
    sensor_or_calc_street: int = 1
    sensor_or_calc_basement: int = 1
    sensor_or_calc_floor: int = 1


class HourlyCoefficient(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hour: int
    delta_temp: float = 0.0
    delta_ah: float = 0.0
    samples_count: int = 0
    updated_at: str


class GraphSensorPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: str
    street_temp: Optional[float] = None
    basement_temp: Optional[float] = None
    floor_temp: Optional[float] = None
    street_humi: Optional[float] = None
    basement_humi: Optional[float] = None
    floor_humi: Optional[float] = None
    vent_status: int = 0
    heat_status: int = 0