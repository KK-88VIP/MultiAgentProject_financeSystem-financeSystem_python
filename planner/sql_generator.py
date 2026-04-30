from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings
from app.services.sql_builder import DIMENSION_MAPPING, TABLE_MAPPING


class SQLGenerator:
    """Generate SQL from QueryPlan for side-by-side validation."""

    def generate(self, plan: Dict[str, Any]) -> str:
        table_name = TABLE_MAPPING[str(plan["table"])]
        metrics = list(plan.get("metrics") or [])
        group_by = list(plan.get("group_by") or [])
        filters = dict(plan.get("filters") or {})
        order_by = list(plan.get("order_by") or [])
        limit = plan.get("limit")

        select_clause = self._build_select(metrics, group_by)
        where_clause = self._build_where(filters)
        group_clause = self._build_group_by(group_by)
        order_clause = self._build_order_by(order_by)
        limit_clause = self._build_limit(limit)

        sql = f"""
        SELECT {select_clause}
        FROM {table_name}
        {where_clause}
        {group_clause}
        {order_clause}
        {limit_clause}
        """
        return " ".join(sql.split())

    def _build_select(self, metrics: List[Dict[str, Any]], group_by: List[str]) -> str:
        fields: List[str] = []
        for dim in group_by:
            col = DIMENSION_MAPPING.get(dim)
            if col:
                fields.append(col)

        for m in metrics:
            if str(m.get("type", "")).lower() == "derived":
                continue
            key = str(m.get("key"))
            col = m.get("column")
            report_item_code = m.get("report_item_code")
            report_item_cn_name = m.get("report_item_cn_name")
            agg_fn = str(m.get("agg", "sum")).upper()
            if agg_fn not in {"SUM", "AVG", "MAX", "MIN"}:
                agg_fn = "SUM"
            if not col:
                continue
            if col == "value" and (report_item_code or report_item_cn_name):
                if report_item_code:
                    escaped_code = str(report_item_code).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_code = '{escaped_code}' THEN value ELSE 0 END) AS {key}"
                    )
                else:
                    escaped_name = str(report_item_cn_name).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_cn_name = '{escaped_name}' THEN value ELSE 0 END) AS {key}"
                    )
            else:
                fields.append(f"{agg_fn}({col}) AS {key}")

        return ", ".join(fields)

    def _build_where(self, filters: Dict[str, Any]) -> str:
        if not filters:
            return ""
        conditions: List[str] = []
        for key, value in filters.items():
            col = DIMENSION_MAPPING.get(key)
            if not col or not value:
                continue
            if isinstance(value, list):
                values = ", ".join(self._format_value(v, col) for v in value)
                conditions.append(f"{col} IN ({values})")
            else:
                conditions.append(f"{col} = {self._format_value(value, col)}")
        return "" if not conditions else "WHERE " + " AND ".join(conditions)

    @staticmethod
    def _build_group_by(group_by: List[str]) -> str:
        cols = [DIMENSION_MAPPING.get(dim) for dim in group_by if DIMENSION_MAPPING.get(dim)]
        return "" if not cols else "GROUP BY " + ", ".join(cols)

    @staticmethod
    def _build_order_by(order_by: List[Dict[str, Any]]) -> str:
        clauses: List[str] = []
        for item in order_by:
            field = item.get("expr") or item.get("field")
            if field:
                direction = str(item.get("direction", "desc")).upper()
                clauses.append(f"{field} {direction}")
        return "" if not clauses else "ORDER BY " + ", ".join(clauses)

    @staticmethod
    def _build_limit(limit: int | None) -> str:
        n = settings.DEFAULT_LIMIT if not limit else min(int(limit), 1000)
        return f"LIMIT {n}"

    @staticmethod
    def _format_value(v: Any, col: str | None = None) -> str:
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"
        if isinstance(v, bool):
            return "1" if v else "0"
        if col == "period_id":
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            if isinstance(v, int):
                return f"'{v}'"
            return "'" + str(v).replace("'", "''") + "'"
        if isinstance(v, (int, float)):
            return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        return "'" + str(v).replace("'", "''") + "'"

