# app/schemas/settings.py

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class SystemSettings(BaseModel):
    """Модель представления записи настроек из БД (settings_table)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(default=1, description="ID единственной записи настроек")
    timestamp: str = Field(description="Время последнего обновления записи (YYYY-MM-DD HH:MM:SS)")
    mode: str = Field(description="Текущий режим работы датчиков (SENSOR_MODE)")
    interval_seconds: int = Field(ge=1, description="Интервал опроса в секундах")
    previous_interval_in_seconds: int = Field(ge=1, description="Предидущий интервал опроса в секундах")
    max_retries: int = Field(ge=1, description="Максимальное количество повторных попыток")
    website_return_time: int = Field(ge=0, description="Время возврата на главный экран (сек)")
    
    # Физические и климатические параметры
    t_floor_mac_diff: float = Field(description="Дельта температур пола и датчика")
    absolute_humidity_tolerance: float = Field(description="Допуск абсолютной влажности")
    minimum_humidity: float = Field(description="Минимальная допустимая влажность")
    target_rh: float = Field(description="Целевая относительная влажность")
    dangerous_humidity: float = Field(description="Опасный порог влажности")
    
    # Тарифы и расход ресурсов
    price_gas: float = Field(description="Тариф на газ")
    hot_water_per_hour: float = Field(description="Расход горячей воды в час")


class SystemSettingsUpdate(BaseModel):
    """Схема для частичного обновления настроек в settings_table."""

    mode: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=1)
    previous_interval_in_seconds: Optional[int] = Field(default=None, ge=1)
    max_retries: Optional[int] = Field(default=None, ge=1)
    website_return_time: Optional[int] = Field(default=None, ge=0)
    
    t_floor_mac_diff: Optional[float] = None
    absolute_humidity_tolerance: Optional[float] = None
    minimum_humidity: Optional[float] = None
    target_rh: Optional[float] = None
    dangerous_humidity: Optional[float] = None
    
    price_gas: Optional[float] = None
    hot_water_per_hour: Optional[float] = None