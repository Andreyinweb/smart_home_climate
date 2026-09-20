# app/routers/graphs.py

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.routers.dashboard import get_template_path
from app.services.graph_service import update_graphs_cache_if_needed

api_log = logging.getLogger("api_app.routers.graphs")
templates = Jinja2Templates(directory="templates")

router = APIRouter(
    tags=["Graphs"],
)


@router.get("/graphs/temperature", response_class=HTMLResponse, summary="График температуры")
async def get_temperature_page(request: Request, background_tasks: BackgroundTasks) -> Any:
    """Страница с графиком температуры."""
    api_log.info("GET /graphs/temperature -> открытие страницы графика температуры")
    background_tasks.add_task(update_graphs_cache_if_needed)
    return templates.TemplateResponse(
        request=request,
        name=get_template_path("temperature.html", request),
        context={"graph_url": "/static/graphs/temperature.png"},
    )


@router.get("/graphs/humidity", response_class=HTMLResponse, summary="График влажности")
async def get_humidity_page(request: Request, background_tasks: BackgroundTasks) -> Any:
    """Страница с графиком влажности."""
    api_log.info("GET /graphs/humidity -> открытие страницы графика влажности")
    background_tasks.add_task(update_graphs_cache_if_needed)
    return templates.TemplateResponse(
        request=request,
        name=get_template_path("humidity.html", request),
        context={"graph_url": "/static/graphs/humidity.png"},
    )