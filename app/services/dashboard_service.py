# -*- coding: utf-8 -*-
"""
@file: dashboard_service.py
@version: 0.2.0
@purpose: 看板数据聚合服务，处理 KPI 与图表组装逻辑。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.metric_service import MetricService
from semantic.registry import MetricRegistry


def _kpi_item(value: float, yoy_change: float | None, is_aggregated: bool, unit: str) -> Dict[str, Any]:
    return {
        "value": float(value) if value is not None else 0.0,
        "yoy_change": yoy_change,
        "unit": unit,
        "is_aggregated": is_aggregated,
    }


class DashboardService:
    """看板 KPI / 图表聚合。"""

    _TABLE_MAP = {
        "bs": "com_kk_sub_bs_risk_ident_t",
        "pl": "com_kk_sub_pl_risk_ident_t",
        "cf": "com_kk_sub_cf_risk_ident_t",
    }
    _KPI_KEYS = ("total_assets", "revenue", "net_profit", "operating_cashflow")
    _RATE_UNITS = {"%", "比例"}

    def __init__(self) -> None:
        self.metric_service = MetricService()
        self.registry = MetricRegistry()

    async def _sum_by_period(
        self,
        db: AsyncSession,
        table: str,
        report_item_code: str | None,
        report_item_cn_name: str,
        company_codes: Sequence[int],
        periods: Sequence[str],
    ) -> List[Row]:
        if not company_codes or not periods:
            return []
        if report_item_code:
            sql = f"""
                SELECT period_id, SUM(value) AS v
                FROM {table}
                WHERE company_code IN :company_codes
                  AND period_id IN :periods
                  AND report_item_code = :report_item_code
                GROUP BY period_id
                ORDER BY period_id DESC
            """
            params = {
                "company_codes": tuple(company_codes),
                "periods": tuple(periods),
                "report_item_code": report_item_code,
            }
        else:
            sql = f"""
                SELECT period_id, SUM(value) AS v
                FROM {table}
                WHERE company_code IN :company_codes
                  AND period_id IN :periods
                  AND report_item_cn_name = :report_item_cn_name
                GROUP BY period_id
                ORDER BY period_id DESC
            """
            params = {
                "company_codes": tuple(company_codes),
                "periods": tuple(periods),
                "report_item_cn_name": report_item_cn_name,
            }
        result = await db.execute(
            text(sql),
            params,
        )
        return list(result.fetchall())

    def _yoy_from_rows(self, rows: List[Row]) -> tuple[float | None, float | None]:
        if not rows:
            return None, None
        current = rows[0].v
        yoy_change: float | None = None
        if len(rows) > 1:
            previous = rows[1].v
            ratio = self.metric_service.safe_divide((current - previous), previous)
            if ratio is not None:
                yoy_change = round(ratio * 100, 2)
        return current, yoy_change

    def _format_metric_output(self, value: float, unit: str) -> tuple[float, str]:
        """
        非率指标统一换算为亿元输出；率指标保留原值。
        """
        if unit in self._RATE_UNITS:
            return float(value or 0), unit
        return float(value or 0) / 100000000.0, "亿元"

    async def get_kpi_data(self, db: AsyncSession, company_codes: str, period_ids: str) -> Dict[str, Any]:
        """获取 KPI 指标卡数据（与 `KpiResponse` 字段对齐）。"""
        company_code_list = [int(c.strip()) for c in company_codes.split(",") if c.strip()]
        periods = [p.strip() for p in period_ids.split(",") if p.strip()]
        target_periods = sorted(periods, reverse=True)[:2]
        is_agg = len(company_code_list) > 1

        out: Dict[str, Any] = {}
        for key in self._KPI_KEYS:
            meta = self.registry.get_metric(key) or {}
            table = self._TABLE_MAP.get(meta.get("table", ""))
            report_item_code = meta.get("report_item_code")
            report_item_cn_name = meta.get("report_item_cn_name") or meta.get("label")
            unit = str(meta.get("unit", "元"))
            if not table or not report_item_cn_name:
                out[key] = _kpi_item(0.0, None, is_agg, "亿元")
                continue
            try:
                rows = await self._sum_by_period(
                    db, table, report_item_code, report_item_cn_name, company_code_list, target_periods
                )
            except Exception:
                out[key] = _kpi_item(0.0, None, is_agg, "亿元" if unit not in self._RATE_UNITS else unit)
                continue
            if not rows:
                out[key] = _kpi_item(0.0, None, is_agg, "亿元" if unit not in self._RATE_UNITS else unit)
                continue
            current, yoy = self._yoy_from_rows(rows)
            formatted_value, out_unit = self._format_metric_output(float(current or 0), unit)
            out[key] = _kpi_item(formatted_value, yoy, is_agg, out_unit)
        return out

    async def get_chart_data(
        self,
        db: AsyncSession,
        chart_type: str,
        metric: str,
        company_codes: str,
        period_ids: str,
    ) -> Dict[str, Any]:
        """获取图表数据，返回与 `ChartResponse` 一致的扁平结构。"""
        company_code_list = [int(c.strip()) for c in company_codes.split(",") if c.strip()]
        periods = sorted({p.strip() for p in period_ids.split(",") if p.strip()})
        mkey = self.registry.resolve_metric(metric) or metric
        meta = self.registry.get_metric(mkey) or {}
        report_item_code = meta.get("report_item_code")
        report_item_cn_name = meta.get("report_item_cn_name") or meta.get("label")
        table_id = meta.get("table")
        unit = str(meta.get("unit", "元"))
        if not report_item_cn_name or not table_id:
            return {
                "chart_type": chart_type,
                "x_axis": periods,
                "y_axis": [0.0 for _ in periods],
                "metric_name": metric,
                "unit": unit,
            }

        table = self._TABLE_MAP.get(table_id, self._TABLE_MAP["pl"])

        values_by_period: Dict[str, float] = {p: 0.0 for p in periods}
        try:
            if report_item_code:
                sql = f"""
                    SELECT period_id, SUM(value) AS v
                    FROM {table}
                    WHERE company_code IN :company_codes
                      AND period_id IN :periods
                      AND report_item_code = :report_item_code
                    GROUP BY period_id
                    ORDER BY period_id ASC
                """
                params = {
                    "company_codes": tuple(company_code_list),
                    "periods": tuple(periods),
                    "report_item_code": report_item_code,
                }
            else:
                sql = f"""
                    SELECT period_id, SUM(value) AS v
                    FROM {table}
                    WHERE company_code IN :company_codes
                      AND period_id IN :periods
                      AND report_item_cn_name = :report_item_cn_name
                    GROUP BY period_id
                    ORDER BY period_id ASC
                """
                params = {
                    "company_codes": tuple(company_code_list),
                    "periods": tuple(periods),
                    "report_item_cn_name": report_item_cn_name,
                }
            result = await db.execute(
                text(sql),
                params,
            )
            for row in result.fetchall():
                values_by_period[str(row.period_id)] = float(row.v or 0)
        except Exception:
            pass

        y_axis = [values_by_period.get(p, 0.0) for p in periods]
        if unit not in self._RATE_UNITS:
            y_axis = [float(v) / 100000000.0 for v in y_axis]
            unit = "亿元"
        return {
            "chart_type": chart_type,
            "x_axis": periods,
            "y_axis": y_axis,
            "metric_name": mkey,
            "unit": unit,
        }
