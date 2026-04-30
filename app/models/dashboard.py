# -*- coding: utf-8 -*-
"""
@file: dashboard.py
@version: 0.1.0
@purpose: 看板 KPI 与图表响应模型定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from pydantic import BaseModel


class KpiItem(BaseModel):
    value: float
    yoy_change: float | None = None
    unit: str
    is_aggregated: bool = False


class KpiResponse(BaseModel):
    total_assets: KpiItem
    revenue: KpiItem
    net_profit: KpiItem
    operating_cashflow: KpiItem


class ChartResponse(BaseModel):
    chart_type: str
    x_axis: list[str]
    y_axis: list[float]
    metric_name: str
    unit: str
