# app/dependencies.py

import os
from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from app.db.repository import BaseRepository

_templates = Jinja2Templates(directory="templates")


def get_templates() -> Jinja2Templates:
    """Возвращает настроенный объект Jinja2Templates."""
    return _templates


def get_template_path(template_name: str, request: Request) -> str:
    """Определяет путь к шаблону с учетом User-Agent и наличия файла в web."""
    user_agent = request.headers.get("user-agent", "").lower()
    legacy_keywords = [
        "smart-tv", "smarttv", "opera tv", "netcast",
        "viera", "tizen/2", "tizen/3", "web0s/1", "web0s/2"
    ]
    is_legacy_device = any(keyword in user_agent for keyword in legacy_keywords)
    web_template_file = os.path.join("templates", "web", template_name)

    if not is_legacy_device and os.path.exists(web_template_file):
        return f"web/{template_name}"

    return f"legacy/{template_name}"


def get_repository() -> BaseRepository:
    """Провайдер экземпляра репозитория для работы с БД."""
    return BaseRepository()