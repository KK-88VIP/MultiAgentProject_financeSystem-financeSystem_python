# -*- coding: utf-8 -*-
"""
@file: dashboard.py
@version: 0.2.0
@purpose: 看板相关接口，包含 KPI 与图表数据查询入口。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.common import ApiResponse
from app.models.dashboard import ChartResponse, KpiResponse
from app.services.dashboard_service import DashboardService
from app.services.dashboard_filters_service import DashboardFiltersService

router = APIRouter()
service = DashboardService()
_filters_service = DashboardFiltersService()


@router.get("/filters", response_model=ApiResponse[dict])
async def get_dashboard_filters(
    user_id: str | None = Header(None, alias="X-User-Id"),
    user_role: str = Header("user", alias="X-User-Role"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """
    筛选器统一数据源：当前用户可见公司列表 + 库内可用年份（number[]，降序）。
    无公司权限时返回 companies=[], years=[]，HTTP 与业务码仍为 200/success。
    管理员需同时或单独使用 X-User-Role: admin（与 /ask 契约一致）。
    本地若前端未带头，可在 .env 设置 DEV_ASSUME_ADMIN_FOR_FILTERS=true（仅 dev）。
    """
    effective_role = user_role
    if (
        settings.DEV_ASSUME_ADMIN_FOR_FILTERS
        and settings.APP_ENV == "dev"
        and (user_role or "").strip().lower() == "user"
    ):
        effective_role = "admin"

    data = await _filters_service.get_filters(db, user_id, effective_role)
    return ApiResponse.success(data=data)


@router.get("/kpi", response_model=ApiResponse[KpiResponse])
async def get_kpi(
    company_codes: str = Query(..., description="公司编码 company_code，逗号分隔"),
    period_ids: str = Query(..., description="年份/期间，逗号分隔"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[KpiResponse]:
    data = await service.get_kpi_data(db=db, company_codes=company_codes, period_ids=period_ids)
    return ApiResponse.success(data=data)


@router.get("/chart", response_model=ApiResponse[ChartResponse])
async def get_chart(
    chart_type: str = Query(..., description="图表类型"),
    metric: str = Query(..., description="指标名称"),
    company_codes: str = Query(..., description="公司编码 company_code，逗号分隔"),
    period_ids: str = Query(..., description="年份/期间，逗号分隔"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChartResponse]:
    data = await service.get_chart_data(
        db=db,
        chart_type=chart_type,
        metric=metric,
        company_codes=company_codes,
        period_ids=period_ids,
    )
    return ApiResponse.success(data=data)
