# app/routers/gas.py
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import get_templates, get_template_path
from app.schemas.gas_schem import GasUpdateInputSchema
from app.services.gas_engine import GasEngineService

logger = logging.getLogger("api_app.routers.gas")
templates = get_templates()

router = APIRouter(tags=["Gas"])


@router.get("/gas", response_class=HTMLResponse, summary="Страница ввода показаний газа")
@router.get("/gas/", response_class=HTMLResponse, include_in_schema=False)
async def get_gas_page(
    request: Request,
    service: GasEngineService = Depends()
):
    context = await service.get_gas_page_context()
    template_name = get_template_path("gas.html", request)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context
    )


@router.post("/api/gas/update")
@router.post("/gas/add")
@router.post("/gas/update")
async def update_gas_meter(
    request: Request,
    gas_meter: Optional[float] = Form(None),
    value: Optional[float] = Form(None),
    start_of_month_gas_meter: Optional[float] = Form(None),
    start_of_month_gas: Optional[float] = Form(None),
    start_gas: Optional[float] = Form(None),
    service: GasEngineService = Depends()
):
    actual_gas_meter = gas_meter if gas_meter is not None else value
    actual_start_gas = (
        start_of_month_gas_meter
        if start_of_month_gas_meter is not None
        else (start_of_month_gas if start_of_month_gas is not None else start_gas)
    )

    if actual_gas_meter is None:
        context = await service.get_gas_page_context(error="Не заполнено поле показаний счетчика газа")
        template_name = get_template_path("gas.html", request)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=context,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    try:
        input_dto = GasUpdateInputSchema(
            gas_meter=actual_gas_meter,
            start_of_month_gas_meter=actual_start_gas
        )
        await service.update_gas_meter(input_dto)
        return RedirectResponse(url="/gas", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        logger.warning("Ошибка при обновлении показателей газа: %s", str(e))
        context = await service.get_gas_page_context(error=str(e))
        template_name = get_template_path("gas.html", request)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=context,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@router.get("/gas/table", response_class=HTMLResponse, summary="Таблица данных по газу")
async def get_gas_table_page(
    request: Request,
    service: GasEngineService = Depends()
):
    context = await service.get_gas_table_context()
    template_name = get_template_path("gas_table.html", request)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context
    )