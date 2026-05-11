"""
SQL 生成器 (SQL Generator)

本模块负责将查询计划 (QueryPlan) 转换为可在数据库上执行的 SQL 语句。

核心职责：
- 根据查询计划中的指标、维度、过滤条件等信息，拼装完整的 SQL 查询
- 处理指标的聚合函数（SUM、AVG、MAX、MIN）
- 支持"一列多指标"的报表场景：当多个指标共享同一 value 列时，
  通过 CASE WHEN + report_item_code/report_item_cn_name 进行条件聚合
- 处理维度名称到数据库列名的映射（如 "region" -> "area_name"）
- 构建 WHERE、GROUP BY、ORDER BY、LIMIT 子句

数据流向：
    QueryPlan (字典形式) -> SQLGenerator.generate() -> SQL 字符串

安全措施：
- 所有用户输入值均通过 _format_value 进行转义，防止 SQL 注入
- 聚合函数白名单校验，仅允许 SUM/AVG/MAX/MIN
- LIMIT 强制上限为 1000，防止大结果集拖慢数据库

"""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings
from planner.sql_mappings import DIMENSION_MAPPING, TABLE_MAPPING


class SQLGenerator:
    """
    SQL 生成器，将 QueryPlan 字典转换为可执行的 SQL 查询字符串。

    生成的 SQL 遵循以下结构：
        SELECT <聚合字段 + 维度字段>
        FROM <目标表>
        WHERE <过滤条件>
        GROUP BY <维度字段>
        ORDER BY <排序规则>
        LIMIT <行数限制>
    """

    def generate(self, plan: Dict[str, Any]) -> str:
        """
        根据查询计划字典生成完整的 SQL 查询语句。

        Args:
            plan: 查询计划字典，通常由 QueryPlan.model_dump() 生成，需包含：
                - table: 目标表标识（将通过 TABLE_MAPPING 映射为实际表名）
                - metrics: 指标元数据列表，每个元素需包含 key、column、agg 等字段
                - group_by: 分组维度列表
                - filters: 过滤条件字典
                - order_by: 排序规则列表
                - limit: 结果行数上限

        Returns:
            压缩后的 SQL 查询字符串（多余的空白已被移除）
        """
        # 通过 TABLE_MAPPING 将语义层的表标识映射为实际数据库表名
        table_name = TABLE_MAPPING[str(plan["table"])]

        # 提取查询计划中的各组成部分，使用空值兜底确保类型安全
        metrics = list(plan.get("metrics") or [])
        group_by = list(plan.get("group_by") or [])
        filters = dict(plan.get("filters") or {})
        order_by = list(plan.get("order_by") or [])
        limit = plan.get("limit")

        # 分别构建 SQL 的各个子句
        select_clause = self._build_select(metrics, group_by)
        where_clause = self._build_where(filters)
        group_clause = self._build_group_by(group_by)
        order_clause = self._build_order_by(order_by)
        limit_clause = self._build_limit(limit)

        # 拼装完整 SQL，使用 " ".join(sql.split()) 移除多余空白和换行
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
        """
        构建 SELECT 子句，包含维度字段和聚合指标字段。

        处理逻辑：
        1. 先添加分组维度对应的列（通过 DIMENSION_MAPPING 映射）
        2. 再遍历指标列表，为每个非派生指标生成聚合表达式：
           - 若指标的 column 为 "value" 且存在 report_item_code 或 report_item_cn_name，
             说明是"一列多指标"的报表场景，使用 CASE WHEN 条件聚合
           - 否则直接对 column 应用聚合函数

        Args:
            metrics: 指标元数据列表
            group_by: 分组维度 key 列表

        Returns:
            SELECT 子句的内容（不含 "SELECT" 关键字）
        """
        fields: List[str] = []

        # 第一部分：添加分组维度字段
        # 通过 DIMENSION_MAPPING 将语义维度名映射为实际数据库列名
        for dim in group_by:
            col = DIMENSION_MAPPING.get(dim)
            if col:
                fields.append(col)

        # 第二部分：添加聚合指标字段
        for m in metrics:
            # 派生指标不在 SQL 层计算，跳过（由 post_compute 在结果集上处理）
            if str(m.get("type", "")).lower() == "derived":
                continue

            key = str(m.get("key"))                        # 指标的别名，用作 SQL 的 AS 名称
            col = m.get("column")                          # 指标对应的数据库列名
            report_item_code = m.get("report_item_code")   # 报表项目编码（用于一列多指标场景）
            report_item_cn_name = m.get("report_item_cn_name")  # 报表项目中文名（备选条件）

            # 获取聚合函数，默认为 SUM，并校验白名单
            agg_fn = str(m.get("agg", "sum")).upper()
            if agg_fn not in {"SUM", "AVG", "MAX", "MIN"}:
                agg_fn = "SUM"

            # 若指标没有对应的列定义，无法生成 SQL，跳过
            if not col:
                continue

            # 场景一：一列多指标（column 为 "value" 且有报表项目标识）
            # 需要使用 CASE WHEN 按 report_item_code 或 report_item_cn_name 进行条件聚合
            if col == "value" and (report_item_code or report_item_cn_name):
                if report_item_code:
                    # 优先使用 report_item_code 作为筛选条件
                    # 对单引号进行转义防止 SQL 注入
                    escaped_code = str(report_item_code).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_code = '{escaped_code}' THEN value ELSE 0 END) AS {key}"
                    )
                else:
                    # 退而使用 report_item_cn_name 作为筛选条件
                    escaped_name = str(report_item_cn_name).replace("'", "''")
                    fields.append(
                        f"{agg_fn}(CASE WHEN report_item_cn_name = '{escaped_name}' THEN value ELSE 0 END) AS {key}"
                    )
            else:
                # 场景二：普通指标，直接对列应用聚合函数
                fields.append(f"{agg_fn}({col}) AS {key}")

        return ", ".join(fields)

    def _build_where(self, filters: Dict[str, Any]) -> str:
        """
        构建 WHERE 子句，将过滤条件字典转换为 SQL 条件表达式。

        支持两种过滤形式：
        - 精确匹配：field = value
        - 列表匹配：field IN (v1, v2, ...)

        所有值均通过 _format_value 进行类型感知的格式化和转义。

        Args:
            filters: 过滤条件字典，键为维度名，值为过滤值（标量或列表）

        Returns:
            完整的 WHERE 子句字符串；若无有效条件则返回空字符串
        """
        if not filters:
            return ""

        conditions: List[str] = []
        for key, value in filters.items():
            # 将维度名映射为实际数据库列名
            col = DIMENSION_MAPPING.get(key)
            # 若映射不存在或值为空，跳过该条件
            if not col or not value:
                continue

            if isinstance(value, list):
                # 列表类型：生成 IN 子句，对每个值进行格式化
                values = ", ".join(self._format_value(v, col) for v in value)
                conditions.append(f"{col} IN ({values})")
            else:
                # 标量类型：生成等值匹配条件
                conditions.append(f"{col} = {self._format_value(value, col)}")

        # 若所有条件均被过滤掉（如映射不存在），返回空字符串
        return "" if not conditions else "WHERE " + " AND ".join(conditions)

    @staticmethod
    def _build_group_by(group_by: List[str]) -> str:
        """
        构建 GROUP BY 子句。

        将语义维度名通过 DIMENSION_MAPPING 映射为实际数据库列名，
        仅保留映射成功的维度。

        Args:
            group_by: 分组维度 key 列表

        Returns:
            完整的 GROUP BY 子句字符串；若无有效分组字段则返回空字符串
        """
        # 过滤掉映射不存在的维度，仅保留有效列名
        cols = [DIMENSION_MAPPING.get(dim) for dim in group_by if DIMENSION_MAPPING.get(dim)]
        return "" if not cols else "GROUP BY " + ", ".join(cols)

    @staticmethod
    def _build_order_by(order_by: List[Dict[str, Any]]) -> str:
        """
        构建 ORDER BY 子句。

        每个排序项支持以下字段：
        - expr: 自定义排序表达式（优先使用）
        - field: 排序字段名（当 expr 不存在时使用）
        - direction: 排序方向，默认为 "desc"

        Args:
            order_by: 排序规则列表，每个元素为包含 field/expr 和 direction 的字典

        Returns:
            完整的 ORDER BY 子句字符串；若无有效排序规则则返回空字符串
        """
        clauses: List[str] = []
        for item in order_by:
            # 优先使用 expr（表达式），其次使用 field（字段名）
            field = item.get("expr") or item.get("field")
            if field:
                # 排序方向默认为降序，统一转为大写
                direction = str(item.get("direction", "desc")).upper()
                clauses.append(f"{field} {direction}")
        return "" if not clauses else "ORDER BY " + ", ".join(clauses)

    @staticmethod
    def _build_limit(limit: int | None) -> str:
        """
        构建 LIMIT 子句。

        若未指定 limit，使用全局配置的默认值；
        若指定，强制上限为 1000 以防止大结果集查询拖慢数据库。

        Args:
            limit: 请求的结果行数上限

        Returns:
            LIMIT 子句字符串
        """
        # 未指定时使用全局默认值；指定时取请求值与 1000 的较小值
        n = settings.DEFAULT_LIMIT if not limit else min(int(limit), 1000)
        return f"LIMIT {n}"

    @staticmethod
    def _format_value(v: Any, col: str | None = None) -> str:
        """
        将 Python 值格式化为 SQL 字面量，同时进行转义以防止 SQL 注入。

        处理规则：
        - 字符串：用单引号包裹，内部单引号转义为两个单引号
        - 布尔值：转为 1/0
        - period_id 列的特殊处理：无论原始类型如何，都作为字符串处理（加单引号），
          因为 period_id 在数据库中通常为字符串类型（如 "202401"）
        - 整数和浮点数：直接转为数字字符串（浮点整数如 3.0 转为 "3"）
        - 其他类型：转为字符串并用单引号包裹

        Args:
            v: 待格式化的值
            col: 该值对应的列名，用于特殊列的类型处理（如 period_id）

        Returns:
            格式化后的 SQL 字面量字符串
        """
        # 字符串类型：单引号包裹 + 单引号转义（' -> ''）
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"

        # 布尔类型：转为整数表示（Python 的 bool 是 int 的子类，需先判断）
        if isinstance(v, bool):
            return "1" if v else "0"

        # period_id 列特殊处理：统一作为字符串输出
        # 因为 period_id 在数据库中通常为 VARCHAR 类型（如 "202401"）
        if col == "period_id":
            # 浮点整数（如 202401.0）先转为 int，再作为字符串输出
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            if isinstance(v, int):
                return f"'{v}'"
            return "'" + str(v).replace("'", "''") + "'"

        # 数值类型：浮点整数转为 int，其余保持原样
        if isinstance(v, (int, float)):
            return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)

        # 兜底：转为字符串并用单引号包裹，内部单引号转义
        return "'" + str(v).replace("'", "''") + "'"
