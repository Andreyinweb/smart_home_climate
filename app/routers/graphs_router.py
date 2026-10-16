# app/routers/graphs_router.py

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_template_path, get_templates
from app.services.graph_service import (
    update_abs_humidity_graph_cache_if_needed,
    update_gas_graph_cache_if_needed,
    update_humidity_graph_cache_if_needed,
    update_temperature_graph_cache_if_needed,
)

api_log = logging.getLogger("api_app.routers.graphs_router")

router = APIRouter(
    tags=["Graphs"],
)


@router.get("/graphs", response_class=HTMLResponse, summary="Графики климата и газа")
async def get_graphs_page(
    request: Request,
    background_tasks: BackgroundTasks,
    graph_type: str = Query("temperature", description="Тип графика: temperature, humidity, abs_humidity, gas"),
    target_date: Optional[str] = Query(None, description="Дата в формате YYYY-MM-DD"),
    target_month: Optional[str] = Query(None, description="Месяц в формате YYYY-MM"),
    templates: Jinja2Templates = Depends(get_templates),
) -> Any:
    """Единая страница для просмотра всех графиков с выбором периода."""
    api_log.debug(f"GET /graphs -> тип: {graph_type}, дата: {target_date}, месяц: {target_month}")

    # Определяем имя базового файла и вызываем соответствующую задачу
    if graph_type == "humidity":
        filename = "humidity.png"
        background_tasks.add_task(update_humidity_graph_cache_if_needed, target_date=target_date, target_month=target_month)
    elif graph_type == "abs_humidity":
        filename = "abs_humidity.png"
        background_tasks.add_task(update_abs_humidity_graph_cache_if_needed, target_date=target_date, target_month=target_month)
    elif graph_type == "gas":
        filename = "gas.png"
        background_tasks.add_task(update_gas_graph_cache_if_needed, target_date=target_date, target_month=target_month)
    else:
        graph_type = "temperature"
        filename = "temperature.png"
        background_tasks.add_task(update_temperature_graph_cache_if_needed, target_date=target_date, target_month=target_month)

    # Формируем имя файла с учетом кэша за сутки или месяц (как сохраняет graph_service)
    if target_date:
        base, ext = os.path.splitext(filename)
        display_filename = f"{base}_{target_date}{ext}"
    elif target_month:
        base, ext = os.path.splitext(filename)
        display_filename = f"{base}_{target_month}{ext}"
    else:
        display_filename = filename

    graph_url = f"/static/graphs/{display_filename}"

    return templates.TemplateResponse(
        request=request,
        name=get_template_path("graph.html", request),
        context={
            "graph_url": graph_url,
            "graph_type": graph_type,
            "target_date": target_date or "",
            "target_month": target_month or "",
        },
    )