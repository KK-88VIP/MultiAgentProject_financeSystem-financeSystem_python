# -*- coding: utf-8 -*-
"""
@file: sql_builder.py
@version: 0.1.0
@purpose: 结构化查询意图（IR）到受控 SQL 的唯一构建入口。
@created: 2026-04-17 21:08:57 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy

SQL 构建器模块 (sql_builder.py)

本模块是系统核心组件之一，负责将经过校验的结构化中间表示（IR，即 ParsedIntent）
转换为可在 MySQL 数据库中直接执行的 SQL 语句。它是系统中 **唯一** 生成 SQL 的入口，
确保所有查询语句的构造逻辑集中可控。

设计原则：
1. 单一职责：仅处理 IR → SQL 的翻译，不涉及权限校验和安全拦截（交由 SQLGuard）。
2. 强白名单约束：所有字段名、表名均须来自 metric_registry 和 TABLE_MAPPING 中的预定义映射，
   杜绝动态拼接可能引入的非法字段或表。
3. 分层指标处理：
   - 原始指标（raw）直接映射为 SQL 聚合字段。
   - 派生指标（derived）不下推到 SQL 计算，而是解析其依赖的原始指标，
     将依赖字段加入 SELECT 列表，后续由 Pandas 层完成计算。
4. 自动补全与强制约束：
   - 若无指定 LIMIT，则使用配置中的默认值。
   - 任何情况下 LIMIT 不得超过 MAX_LIMIT 上限。
   - 存在维度（group_by）时自动补全 GROUP BY 子句。

流程概览：
    IR (ParsedIntent)
        │
        ▼
    [SQLBuilder.build()]
        ├── 1. 拆分 raw / derived 指标
        ├── 2. 派生指标 → 扩展依赖字段至 raw 列表
        ├── 3. 确定主表（当前仅支持单表查询）
        ├── 4. 构建 SELECT、WHERE、GROUP BY、ORDER BY、LIMIT 子句
        └── 5. 拼接并返回最终 SQL 字符串
"""

from typing import Dict, List, Tuple

from app.core.config import settings
from semantic.registry import MetricRegistry

# =========================
# 物理表名映射
# =========================
# 将指标注册表中的逻辑表标识符（bs/pl/cf）映射到数据库中的实际物理表名。
# 可根据真实数据库表结构调整。
TABLE_MAPPING = {
    "bs": "com_kk_sub_bs_risk_ident_t",
    "pl": "com_kk_sub_pl_risk_ident_t",
    "cf": "com_kk_sub_cf_risk_ident_t",
}

# =========================
# 维度字段映射
# =========================
# 将 IR 中通用的维度名称（company/year）映射到数据库表中的实际字段名。
# 用于 WHERE、GROUP BY、ORDER BY 子句中的字段引用。
DIMENSION_MAPPING = {
    "company": "company_cn_name",
    "year": "period_id",
}


class SQLBuilder:
    """
    SQL 构建器类

    使用方法：
        builder = SQLBuilder()
        sql = builder.build(ir)
    """

    def __init__(self):
        self.registry = MetricRegistry()

    def build(self, ir) -> str:
        """
        主入口：将 ParsedIntent 对象转换为完整的 MySQL SELECT 语句。

        参数：
            ir：包含以下属性的 ParsedIntent 对象
                - metrics：List[str] 标准指标 Key 列表
                - group_by：List[str] 维度列表（如 ["company", "year"]）
                - filters：Dict 过滤条件（如 {"year": 2025, "company": ["腾讯"]}）
                - order_by：List[Dict] 排序规则（如 [{"field": "revenue", "direction": "desc"}]）
                - limit：int 结果数量限制

        返回：
            格式化后的单行 SQL 字符串。

        异常：
            ValueError：当指标未找到有效表或查询涉及跨表时抛出。
        """
        # 1. 解析指标（区分 raw / derived）
        raw_metrics, derived_metrics = self._split_metrics(ir.metrics)

        # 2. 派生指标 → 补充依赖字段（下沉到 SQL 层取数）
        raw_metrics = self._expand_dependencies(raw_metrics, derived_metrics)

        # 3. 确定表（当前假设同一查询只涉及单表）
        table = self._resolve_table(raw_metrics)
        table_name = TABLE_MAPPING[table]

        # 4. 构建各子句
        select_clause = self._build_select(raw_metrics, ir.group_by)
        where_clause = self._build_where(ir.filters)
        group_clause = self._build_group_by(ir.group_by)
        order_clause = self._build_order_by(ir.order_by)
        limit_clause = self._build_limit(ir.limit)

        # 5. 拼装 SQL，使用字符串压缩去除多余空白
        sql = f"""
        SELECT {select_clause}
        FROM {table_name}
        {where_clause}
        {group_clause}
        {order_clause}
        {limit_clause}
        """

        return " ".join(sql.split())  # 压缩空白，输出整洁单行

    # =========================
    # 语义层适配方法
    # =========================
    def _get_metric_meta(self, metric: str) -> Dict:
        meta = self.registry.get_metric(metric) or {}
        if not isinstance(meta, dict):
            return {}
        # 兼容历史字段命名
        mapped = dict(meta)
        mapped.setdefault("report_item_cn_name", mapped.get("label"))
        mapped["aggregation"] = mapped.get("agg", mapped.get("aggregation", "sum"))
        return mapped

    def _get_column(self, metric: str) -> str | None:
        return self._get_metric_meta(metric).get("column")

    def _get_table(self, metric: str) -> str | None:
        return self._get_metric_meta(metric).get("table")

    def _is_derived(self, metric: str) -> bool:
        return self.registry.is_derived(metric)

    def _get_dependencies(self, metric: str) -> List[str]:
        return self.registry.dependencies_of(metric)

    def build_from_plan(self, plan: Dict) -> str:
        """
        从 QueryPlan 构建 SQL（Phase 2 适配层）。

        参数：
            plan: dict，至少包含 table / metrics / filters / group_by / order_by / limit
        """
        table_key = str(plan.get("table") or "")
        if table_key not in TABLE_MAPPING:
            raise ValueError(f"Unknown table key in plan: {table_key}")
        table_name = TABLE_MAPPING[table_key]

        metrics_meta = plan.get("metrics") or []
        metric_keys = plan.get("metric_keys") or []
        if metric_keys:
            select_clause = self._build_select(metric_keys, plan.get("group_by") or [])
        else:
            # 兜底：由 plan.metrics 推导 key
            keys = [str(m.get("key")) for m in metrics_meta if m.get("key")]
            select_clause = self._build_select(keys, plan.get("group_by") or [])

        where_clause = self._build_where(plan.get("filters") or {})
        group_clause = self._build_group_by(plan.get("group_by") or [])
        order_clause = self._build_order_by(plan.get("order_by") or [])
        limit_clause = self._build_limit(plan.get("limit"))

        sql = f"""
        SELECT {select_clause}
        FROM {table_name}
        {where_clause}
        {group_clause}
        {order_clause}
        {limit_clause}
        """
        return " ".join(sql.split())

    # =========================
    # 内部辅助方法
    # =========================

    def _split_metrics(self, metrics: List[str]) -> Tuple[List[str], List[str]]:
        """
        将指标列表拆分为原始指标和派生指标。

        依赖：
            is_derived() 查询 metric_registry 判断指标类型。

        返回：
            (raw_metrics, derived_metrics) 两个列表。
        """
        raw = []
        derived = []
        for m in metrics:
            if self._is_derived(m):
                derived.append(m)
            else:
                raw.append(m)
        return raw, derived

    def _expand_dependencies(self, raw: List[str], derived: List[str]) -> List[str]:
        """
        扩展原始指标列表，将派生指标所依赖的字段加入其中。

        原因：
            派生指标不在 SQL 中计算，因此需要在 SELECT 中拉取其依赖的原始字段，
            以便后续在 Pandas 层执行公式计算。

        示例：
            若 derived 包含 "gross_margin"（依赖 revenue 和 cost），
            则 raw 列表将追加 "revenue" 和 "cost"。

        返回：
            去重后的扩展原始指标列表。
        """
        expanded = set(raw)
        for m in derived:
            deps = self._get_dependencies(m)
            expanded.update(deps)
        return list(expanded)

    def _resolve_table(self, metrics: List[str]) -> str:
        """
        根据指标列表确定查询所属的主表。

        逻辑：
            遍历所有指标，通过 get_table() 获取其表标识符，收集去重。
            - 若所有指标均来自同一张表，返回该表标识符。
            - 若无有效表，抛出异常。
            - 若涉及多张表，抛出异常（当前版本不支持跨表 JOIN）。

        返回：
            表标识符（"bs"/"pl"/"cf" 之一）。
        """
        tables = set()
        for m in metrics:
            t = self._get_table(m)
            if t:
                tables.add(t)

        if not tables:
            raise ValueError("No valid table found for metrics")

        if len(tables) > 1:
            raise ValueError("Cross-table query is not supported in current version")

        return tables.pop()

    def _build_select(self, metrics: List[str], group_by: List[str]) -> str:
        """
        构建 SELECT 子句。

        规则：
            - 若存在 group_by，则维度字段作为普通列加入 SELECT。
            - 对于每个指标，默认应用 SUM() 聚合（因为财务数据通常需按公司/年份汇总）。
            - 使用 AS 将结果列重命名为标准指标 Key，便于后续 Pandas 识别。

        返回：
            形如 "company_name, year, SUM(revenue) AS revenue" 的字符串。
        """
        fields = []

        # 维度字段（不聚合）
        for dim in group_by or []:
            col = DIMENSION_MAPPING.get(dim)
            if col:
                fields.append(col)

        # 指标字段（聚合）
        for m in metrics:
            col = self._get_column(m)
            meta = self._get_metric_meta(m) or {}
            report_item_code = meta.get("report_item_code")
            report_item_cn_name = meta.get("report_item_cn_name")
            agg_fn = str(meta.get("aggregation", "sum")).upper()
            if agg_fn not in {"SUM", "AVG", "MAX", "MIN"}:
                agg_fn = "SUM"
            if not col:
                continue
            # 三张业务事实表采用统一 value 列承载指标值，按报表项中文名区分具体指标。
            if col == "value" and (report_item_code or report_item_cn_name):
                if report_item_code:
                    escaped_code = str(report_item_code).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_code = '{escaped_code}' THEN value ELSE 0 END) AS {m}"
                    )
                else:
                    escaped_name = str(report_item_cn_name).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_cn_name = '{escaped_name}' THEN value ELSE 0 END) AS {m}"
                    )
            else:
                fields.append(f"{agg_fn}({col}) AS {m}")

        return ", ".join(fields)

    def _build_where(self, filters: Dict) -> str:
        """
        构建 WHERE 子句。

        参数：
            filters：字典，键为维度名（如 "year"），值为过滤值（单值或列表）。

        处理：
            - 单值转为 = 条件。
            - 列表转为 IN 条件。
            - 字符串值自动添加单引号。

        返回：
            完整的 WHERE 子句字符串，若 filters 为空则返回空串。
        """
        if not filters:
            return ""

        conditions = []

        for k, v in filters.items():
            col = DIMENSION_MAPPING.get(k)
            if not col or not v:
                continue

            if isinstance(v, list):
                # 列表 → IN 条件
                values = ", ".join([self._format_value(x, col) for x in v])
                conditions.append(f"{col} IN ({values})")
            else:
                # 单值 → 等值条件
                conditions.append(f"{col} = {self._format_value(v, col)}")

        if not conditions:
            return ""

        return "WHERE " + " AND ".join(conditions)

    def _build_group_by(self, group_by: List[str]) -> str:
        """
        构建 GROUP BY 子句。

        参数：
            group_by：维度名称列表（如 ["company", "year"]）。

        返回：
            GROUP BY 子句字符串，若无有效维度则返回空串。
        """
        if not group_by:
            return ""

        cols = [DIMENSION_MAPPING.get(dim) for dim in group_by if dim in DIMENSION_MAPPING]
        cols = [c for c in cols if c]

        if not cols:
            return ""

        return "GROUP BY " + ", ".join(cols)

    def _build_order_by(self, order_by: List[Dict]) -> str:
        """
        构建 ORDER BY 子句。

        参数：
            order_by：排序规则列表，每项包含 field 和可选的 direction。

        注意：
            - field 应为标准指标 Key 或维度名（需已在 SELECT 中作为别名存在）。
            - 默认排序方向为 DESC（降序）。

        返回：
            ORDER BY 子句字符串。
        """
        if not order_by:
            return ""

        clauses = []
        for item in order_by:
            field = item.get("field")
            direction = item.get("direction", "desc").upper()

            if field:
                clauses.append(f"{field} {direction}")

        if not clauses:
            return ""

        return "ORDER BY " + ", ".join(clauses)

    def _build_limit(self, limit: int) -> str:
        """
        构建 LIMIT 子句，强制应用安全上限。

        逻辑：
            - 若未传入 limit，使用配置中的 DEFAULT_LIMIT。
            - 将 limit 与 MAX_LIMIT 比较，取较小值，防止超大结果集。

        返回：
            LIMIT 子句字符串。
        """
        if not limit:
            limit = settings.DEFAULT_LIMIT

        limit = min(limit, settings.MAX_LIMIT)

        return f"LIMIT {limit}"

    def _format_value(self, v, col: str | None = None):
        """
        将 Python 值格式化为 SQL 字面量。

        注意：
            本方法仅提供基础转义（字符串加单引号），
            实际防 SQL 注入由 SQLGuard 的 AST 解析和白名单校验负责。
            period_id 列统一按字符串字面量输出，以兼容 VARCHAR 期间字段。

        返回：
            格式化后的字符串。
        """
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