# app/core/config.py

import sys
import logging
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, SecretStr, model_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WeatherProvider(str, Enum):
    TOMORROW = "TOMORROW"
    OPENWEATHERMAP = "OPENWEATHERMAP"


class SensorMode(str, Enum):
    BASEMENT_STREET_FLOOR = "BASEMENT_STREET_FLOOR"
    BASEMENT_STREET = "BASEMENT_STREET"
    BASEMENT_FLOOR = "BASEMENT_FLOOR"
    BASEMENT = "BASEMENT"


class ProgrammerMode(str, Enum):
    PROGRAMMER_CONST = "PROGRAMMER_CONST"
    PROGRAMMER_TEMPORARILY_CONST = "PROGRAMMER_TEMPORARILY_CONST"
    PROGRAMMER_TEMPORARILY_WEEK = "PROGRAMMER_TEMPORARILY_WEEK"
    PROGRAMMER_WEEK = "PROGRAMMER_WEEK"


class AppEnv(str, Enum):
    PRODUCTION = "PRODUCTION"
    STAGING = "STAGING"
    DEVELOPMENT = "DEVELOPMENT"


class ClimatePhysicsDefaults(BaseModel):
    """
    ВАЖНО: Переменные в этом классе можно менять прямо здесь в коде.
    Значения по умолчанию для физики и программатора задаются здесь.
    """
    t_floor_mac_diff: float = Field(default=2.0, description="Дельта температур пола и датчика")
    absolute_humidity_tolerance: float = Field(default=0.5, description="Допуск абсолютной влажности")
    minimum_humidity: float = Field(default=65.0, description="Минимальная допустимая влажность")
    target_rh: float = Field(default=70.0, description="Целевая относительная влажность")
    dangerous_humidity: float = Field(default=75.0, description="Опасный порог влажности")

    price_gas: float = Field(default=7.96, description="Тариф на газ")
    hot_water_per_hour: float = Field(default=0.0457, description="Расход горячей воды в час")
    start_of_month_gas_meter: float = Field(default=36870.0, description="Начальные показания счетчика газа")

    minimum_temperature: float = Field(default=13.0, description="Минимальная допустимая температура")
    target_temperature: float = Field(default=22.0, description="Целевая температура")
    maximum_temperature: float = Field(default=26.0, description="Опасная минимальная температура")
    hysteresis_temperature: float = Field(default=1.0, description="Гистерезис температуры")
    programmer_mode: ProgrammerMode = Field(default=ProgrammerMode.PROGRAMMER_CONST, description="Режим работы программатора")
    days_week_mode: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "week": ["Mo_Su"],
            "weekdays": ["Mo_Fr", "Sa_Su"],
            "weekdays_weekend": ["Mo_Fr", "Sa", "Su"],
            "day": ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
        },
        description="Режимы дней недели программатора",
    )


class Settings(BaseSettings, ClimatePhysicsDefaults):
    model_config = SettingsConfigDict(
        env_file=(
            "/etc/climat_app/config.env",
            Path.home() / ".config/climat_app/config.env",
            ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- Режимы приложения и железа ---
    app_env: AppEnv = Field(default=AppEnv.DEVELOPMENT, alias="APP_ENV")
    sensor_mode: SensorMode = Field(default=SensorMode.BASEMENT_STREET_FLOOR, alias="SENSOR_MODE")

    # --- Пути (AppConfig & DatabaseConfig) ---
    project_dir: Path = Field(default_factory=Path.cwd)
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    work_log: Optional[Path] = Field(default=None, alias="WORK_LOG")
    api_log: Optional[Path] = Field(default=None, alias="API_LOG")
    backup: Path = Field(default=Path("backup"), alias="BACKUP")

    db_dir: Path = Field(default=Path("."), alias="DB_DIR")
    db_name: str = Field(default="climate_data.sqlite3", alias="DB_NAME")

    # --- Выбор источника погоды и API ключи ---
    site_weather: WeatherProvider = Field(default=WeatherProvider.TOMORROW, alias="SITE_WEATHER")
    openweathermap_api_key: Optional[SecretStr] = Field(default=None, alias="OPENWEATHERMAP_API_KEY")
    tomorrow_api_key: Optional[SecretStr] = Field(default=None, alias="TOMORROW_API_KEY")

    # --- Интервалы и таймауты ---
    interval_seconds: int = Field(default=300, alias="INTERVAL_SECONDS", ge=1)
    previous_interval_in_seconds: int = Field(default=300, alias="INTERVAL_SECONDS", ge=1)
    max_retries: int = Field(default=5, alias="MAX_RETRIES", ge=1)
    website_return_time: int = Field(default=300, alias="WEBSITE_RETURN_TIME", ge=0)

    # --- BLE MAC-адреса (входные значения из env файлов) ---
    street_mac: Optional[str] = Field(default=None, alias="STREET_MAC")
    basement_mac: Optional[str] = Field(default=None, alias="BASEMENT_MAC")
    floor_mac: Optional[str] = Field(default=None, alias="FLOOR_MAC")

    # --- Настройки USB-реле котла ---
    relay_id: Optional[str] = Field(default=None, alias="RELAY_ID")
    relay_inverted: bool = Field(default=False, alias="RELAY_INVERTED")
    relay_timeout: float = Field(default=2.0, alias="RELAY_TIMEOUT")
    relay_max_retries: int = Field(default=3, alias="RELAY_MAX_RETRIES")

    # --- Настройки сервера и геолокации ---
    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    server_port: int = Field(default=8000, alias="SERVER_PORT", ge=1, le=65535)
    location_lat: float = Field(default=50.4501, alias="LOCATION_LAT")
    location_lon: float = Field(default=30.5234, alias="LOCATION_LON")

    # --- Вычисляемые свойства ---
    @computed_field
    @property
    def db_path(self) -> Path:
        return self.db_dir / self.db_name

    @computed_field
    @property
    def active_weather_api_key(self) -> Optional[SecretStr]:
        if self.site_weather == WeatherProvider.OPENWEATHERMAP:
            return self.openweathermap_api_key
        elif self.site_weather == WeatherProvider.TOMORROW:
            return self.tomorrow_api_key
        return None

    @computed_field
    @property
    def mac_dict(self) -> Dict[str, str]:
        required_sensors = [s.lower() for s in self.sensor_mode.value.split("_")]
        return {
            sensor: getattr(self, f"{sensor}_mac").strip()
            for sensor in required_sensors
            if getattr(self, f"{sensor}_mac")
        }

    # --- Валидация путей, ключей и MAC-адресов ---
    @model_validator(mode="after")
    def validate_all_dependencies(self) -> "Settings":
        if not self.log_dir.is_absolute():
            self.log_dir = self.project_dir / self.log_dir

        if not self.backup.is_absolute():
            self.backup = self.project_dir / self.backup

        if not self.db_dir.is_absolute():
            self.db_dir = self.project_dir / self.db_dir

        if self.work_log is None:
            self.work_log = self.log_dir / "work_log.log"
        elif not self.work_log.is_absolute():
            self.work_log = self.project_dir / self.work_log

        if self.api_log is None:
            self.api_log = self.log_dir / "api_log.log"
        elif not self.api_log.is_absolute():
            self.api_log = self.project_dir / self.api_log

        active_key = self.active_weather_api_key
        if not active_key or not active_key.get_secret_value().strip():
            raise ValueError(
                f"Для выбранного провайдера SITE_WEATHER='{self.site_weather.value}' "
                f"не задан валидный API-ключ."
            )

        required_sensors = [s.lower() for s in self.sensor_mode.value.split("_")]
        for sensor_name in required_sensors:
            attr_name = f"{sensor_name}_mac"
            mac_val = getattr(self, attr_name, None)
            if not mac_val or not str(mac_val).strip():
                raise ValueError(
                    f"Для режима SENSOR_MODE='{self.sensor_mode.value}' не задан MAC-адрес '{sensor_name.upper()}_MAC' в конфигурационном файле. "
                    f"Заполните адрес или измените SENSOR_MODE."
                )
        
        return self

    def create_required_directories(self) -> None:
        for folder in [self.log_dir, self.backup, self.db_dir]:
            folder.mkdir(parents=True, exist_ok=True)


try:
    settings = Settings()
    settings.create_required_directories()
except Exception as e:
    print(f"Ошибка загрузки конфигурации: {e}")
    sys.exit(1)