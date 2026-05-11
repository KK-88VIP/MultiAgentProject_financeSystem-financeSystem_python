"""
查询计划构建器 (Query Planner)

本模块负责将中间表示 (QueryIR) 转换为确定性的查询计划 (QueryPlan)。

核心职责：
- 将用户意图中的指标名称解析为标准 key，并展开派生指标的依赖链
- 校验指标合法性、数据源一致性（不支持跨表查询）、排序字段合法性
- 组装包含完整元数据的 QueryPlan 对象，供下游 SQL 生成器使用

数据流向：
    QueryIR (用户意图) -> QueryPlanner.plan() -> QueryPlan (可执行查询计划)

典型使用场景：
    registry = MetricRegistry()
    planner = QueryPlanner(registry)
    plan = planner.plan(ir)       # ir 为 QueryIR 实例
    sql = plan.model_dump()       # 序列化为字典，传递给 SQL 生成层
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from semantic.registry import MetricRegistry


@dataclass
class QueryPlan:
    """
    查询计划数据类，封装一次语义查询的全部执行信息。

    该对象是 QueryPlanner 的输出，也是下游 SQL 生成器的输入。
    所有字段均为确定性的，即相同的 QueryIR 输入始终产生相同的 QueryPlan。

    Attributes:
        semantic_version: 语义层配置版本号，用于变更追踪和缓存失效
        model: 数据模型标识（通常对应数据库表名）
        table: 查询的目标数据库表名
        metrics: 指标的完整元数据列表，每个元素包含 key、table、type 等信息
        metric_keys: 展开后的标准指标 key 列表（已去重，含派生指标的依赖项）
        filters: 查询过滤条件字典，键为字段名，值为过滤值或表达式
        group_by: 分组字段列表（维度列名）
        order_by: 排序规则列表，每个元素包含 field（字段名）和 direction（排序方向）
        limit: 返回结果的最大行数，范围 [1, 1000]，默认 100
        post_compute: 需要在查询结果上进行后计算的派生指标 key 列表
    """
    semantic_version: str
    model: str
    table: str
    metrics: List[Dict[str, Any]]
    metric_keys: List[str]
    filters: Dict[str, Any]
    group_by: List[str]
    order_by: List[Dict[str, Any]]
    limit: int | None
    post_compute: List[str]

    def model_dump(self) -> Dict[str, Any]:
        """
        将查询计划序列化为字典，便于传递给下游的 SQL 生成器或日志系统。

        使用 dataclasses.asdict 实现深拷贝式的递归转换。

        Returns:
            包含所有字段的字典
        """
        return asdict(self)


class QueryPlanner:
    """
    查询计划构建器，负责将 QueryIR (查询中间表示) 转换为确定性的 QueryPlan。

    处理流程：
    1. 解析指标名称 -> 展开派生指标依赖 -> 去重
    2. 收集指标元数据和数据源表信息
    3. 校验数据源一致性（单表约束）
    4. 组装分组、排序、过滤条件
    5. 生成最终的 QueryPlan
    """

    def __init__(self, registry: MetricRegistry | None = None):
        """
        初始化查询计划构建器。

        Args:
            registry: 语义指标注册中心实例，为 None 时自动创建默认实例
        """
        self.registry = registry or MetricRegistry()

    def plan(self, ir) -> QueryPlan:
        """
        将查询中间表示 (QueryIR) 转换为确定性的查询计划。

        处理步骤：
        1. 提取并解析所有指标，展开派生指标的底层依赖
        2. 收集指标元数据，验证数据源表的一致性
        3. 校验排序字段必须是已查询的指标或分组维度
        4. 规范化 limit 值到 [1, 1000] 范围
        5. 组装并返回 QueryPlan

        Args:
            ir: 查询中间表示对象，需包含以下属性：
                - metrics: 请求的指标名称列表
                - dimensions: 维度列表（可选）
                - group_by: 分组字段列表（可选）
                - order_by: 排序规则列表（可选）
                - filters: 过滤条件字典（可选）
                - limit: 结果行数限制（可选）

        Returns:
            确定性的 QueryPlan 对象

        Raises:
            ValueError: 当指标为空、指标未知、跨表查询、或排序字段不合法时
        """
        # ========== 第一步：提取并解析指标 ==========
        # 从 IR 中获取用户请求的指标 key 列表
        metric_keys = list(ir.metrics or [])
        if not metric_keys:
            raise ValueError("No metrics found in intent")

        # 展开指标列表：将派生指标拆解为其底层依赖的基础指标
        # expanded 存储展开后的所有指标 key（含基础指标和派生指标的依赖）
        # post_compute 存储需要在结果集上做后计算的派生指标
        expanded: List[str] = []
        post_compute: List[str] = []

        for key in metric_keys:
            # 将可能的别名解析为标准 key
            resolved = self.registry.resolve_metric(key) or key

            # 获取该指标的元数据，若不存在则说明是无效指标
            m = self.registry.get_metric(resolved)
            if not m:
                raise ValueError(f"Unknown metric: {key}")

            # 将标准 key 加入展开列表
            expanded.append(resolved)

            # 如果是派生指标，需要额外处理：
            # 1. 将其标记为需要后计算
            # 2. 将其依赖的基础指标也加入展开列表，确保 SQL 查询能获取到原始数据
            if self.registry.is_derived(resolved):
                post_compute.append(resolved)
                expanded.extend(self.registry.dependencies_of(resolved))

        # ========== 第二步：去重并保持原始顺序 ==========
        # 使用 set 跟踪已出现的 key，确保列表中无重复且保持首次出现的顺序
        seen = set()
        metric_keys_expanded: List[str] = []
        for k in expanded:
            if k not in seen:
                seen.add(k)
                metric_keys_expanded.append(k)

        # ========== 第三步：收集指标元数据和数据源表 ==========
        metrics: List[Dict[str, Any]] = []
        tables = set()

        for key in metric_keys_expanded:
            meta = self.registry.get_metric(key)
            if not meta:
                continue

            # 复制元数据并在其中注入标准 key，方便下游使用
            metric_meta = dict(meta)
            metric_meta["key"] = key
            metrics.append(metric_meta)

            # 收集指标对应的数据源表名
            table = meta.get("table")
            if table:
                tables.add(str(table))

        # 校验数据源：至少需要一个有效表，且不支持跨表查询
        if not tables:
            raise ValueError("No valid table found for metrics")
        if len(tables) > 1:
            raise ValueError("Cross-table query is not supported in current version")

        # ========== 第四步：组装分组和排序 ==========
        # 从 IR 中提取维度和分组信息
        # dimensions 是语义维度（如 "region"），group_by 是具体列名
        # 优先使用 dimensions，若为空则使用 group_by
        dimensions = list(getattr(ir, "dimensions", []) or [])
        group_by = list(ir.group_by or [])
        group_dims = dimensions or group_by

        # 多年份过滤但未按期间分组时，聚合 SQL 会打成单行且结果中无 period_id，
        # 分析引擎无法做趋势/同比。此处自动补上按「年」分组（语义键 year → period_id）。
        ir_filters = dict(ir.filters or {})
        year_f = ir_filters.get("year")
        if isinstance(year_f, list) and len(year_f) > 1 and "year" not in group_dims:
            group_dims = list(group_dims) + ["year"]

        # 校验排序字段：排序字段必须是已查询的指标或分组维度之一
        # 防止用户对未查询的字段进行排序，避免生成无效 SQL
        order_by = list(ir.order_by or [])
        valid_order_fields = set(metric_keys_expanded) | set(group_dims)
        for ob in order_by:
            field = ob.get("field")
            if field and field not in valid_order_fields:
                raise ValueError(f"order_by.field not matched: {field}")

        # ========== 第五步：规范化 limit ==========
        # 默认值为 100，强制限制在 [1, 1000] 范围内
        # 防止因异常值导致查询过慢或返回空结果
        limit = ir.limit if getattr(ir, "limit", None) else 100
        try:
            limit = int(limit)
        except Exception:
            limit = 100
        limit = min(max(limit, 1), 1000)

        # ========== 第六步：组装并返回查询计划 ==========
        # 从 tables 集合中取出唯一的表名作为查询目标
        table_key = tables.pop()

        return QueryPlan(
            semantic_version=self.registry.version,  # 语义层版本，用于缓存和追踪
            model=table_key,                          # 数据模型标识
            table=table_key,                          # 实际查询的目标表
            metrics=metrics,                          # 指标完整元数据列表
            metric_keys=metric_keys_expanded,          # 展开后的标准指标 key 列表
            filters=dict(ir.filters or {}),           # 过滤条件，深拷贝防止外部修改
            group_by=group_dims,                      # 分组字段
            order_by=order_by,                        # 排序规则
            limit=limit,                              # 结果行数上限
            post_compute=post_compute,                # 需要后计算的派生指标
        )
