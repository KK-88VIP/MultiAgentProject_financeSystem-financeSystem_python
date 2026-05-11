# -*- coding: utf-8 -*-
"""
Dashboard DSL 数据模型定义 (dashboard_dsl.py)

本模块定义了 Dashboard DSL（领域专用语言）的完整数据结构，是看板功能的核心 Schema 层。
所有看板的创建、渲染、校验都基于这些 Pydantic 模型进行数据验证和序列化。

DSL 设计思路：
- 一个 Dashboard 由多个 Widget 组成（图表、表格等）
- 每个 Widget 包含数据集定义（Dataset）和图表配置（ChartConfig）
- Dataset 定义"查什么"（指标、维度、过滤条件）
- ChartConfig 定义"怎么画"（图表类型、X/Y 轴映射）
- 通过 Position 控制 Widget 在看板中的布局位置

数据流向：
    前端 DSL JSON → DashboardDSL（反序列化/校验）→ DashboardDSLService（渲染）
    → DatasetService（查询）→ 图表数据组装 → 前端渲染

示例 DSL 结构：
    {
        "id": "dashboard_001",
        "title": "财务分析看板",
        "version": "v1",
        "filters": [
            {"name": "company", "type": "multi_select", "default": null}
        ],
        "widgets": [
            {
                "id": "chart_revenue",
                "type": "chart",
                "dataset": {
                    "metrics": ["revenue"],
                    "dimensions": ["company"],
                    "group_by": ["company"],
                    "filters": {"year": [2025]},
                    "limit": 100
                },
                "chart": {
                    "type": "bar",
                    "x": "company",
                    "y": "revenue"
                },
                "position": {"x": 0, "y": 0, "w": 6, "h": 4}
            }
        ]
    }
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# =========================
# 筛选器定义
# =========================

class FilterItem(BaseModel):
    """
    看板级筛选器定义，描述看板顶部的全局筛选条件。

    筛选器作用于看板内所有 Widget，用户选择的筛选值会注入到每个 Widget 的 Dataset 查询中。
    当前支持两种类型：
    - select: 单选下拉框（如选择单个年份）
    - multi_select: 多选下拉框（如选择多个公司）

    Attributes:
        name: 筛选器标识名，对应维度字段名（如 "company"、"year"）
        type: 筛选器交互类型，"select" 或 "multi_select"，默认 "select"
        default: 默认选中值，可为整数或字符串，None 表示无默认值
    """
    name: str
    type: Literal["select", "multi_select"] = "select"
    default: Optional[int | str] = None


# =========================
# 数据集定义
# =========================

class Dataset(BaseModel):
    """
    Widget 的数据集定义，描述"从哪里查、查什么、怎么过滤、怎么分组"。

    Dataset 是 Widget 的数据来源声明，渲染时由 DatasetService 将其转换为
    QueryPlan → SQL 并执行查询。它复用了问数引擎的完整查询链路。

    Attributes:
        metrics: 需要查询的指标 key 列表（如 ["revenue", "net_profit"]）
                 指标 key 必须在 semantic/metrics.yaml 中定义
        dimensions: 查询的维度列表（如 ["company", "year"]）
                    维度 key 必须在 semantic/dimensions.yaml 中定义
        group_by: 分组字段列表，通常与 dimensions 一致
                  SQL 中的 GROUP BY 子句将使用此字段
        filters: 过滤条件字典，键为维度名，值为过滤值
                 如 {"year": [2025], "company": ["华为技术有限公司"]}
        order_by: 排序规则列表，每个元素包含 field（字段名）和 direction（asc/desc）
                  如 [{"field": "revenue", "direction": "desc"}]
        limit: 返回结果的最大行数，默认 100，上限 1000
    """
    metrics: List[str]
    dimensions: List[str] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    filters: Dict = Field(default_factory=dict)
    order_by: Optional[List[Dict]] = None
    limit: Optional[int] = 100


# =========================
# 图表配置
# =========================

class ChartConfig(BaseModel):
    """
    图表渲染配置，定义图表类型和 X/Y 轴字段映射。

    x 和 y 的值必须是 Dataset 查询结果中存在的列名（指标 key 或维度 key）。

    Attributes:
        type: 图表类型（如 "bar"、"line"、"pie"、"table"、"kpi" 等）
        x: X 轴对应的字段名（通常是维度，如 "company"、"year"）
        y: Y 轴对应的字段名（通常是指标，如 "revenue"）
    """
    type: str
    x: str
    y: str


# =========================
# 布局定位
# =========================

class Position(BaseModel):
    """
    Widget 在看板网格中的布局位置。

    采用 12 列网格系统（类似 Bootstrap Grid），x/y 为网格坐标，w/h 为占用的网格单位。

    Attributes:
        x: 水平起始位置（列号，从 0 开始）
        y: 垂直起始位置（行号，从 0 开始）
        w: 宽度（占用的列数，最大 12）
        h: 高度（占用的行数）
    """
    x: int
    y: int
    w: int
    h: int


# =========================
# Widget 定义
# =========================

class Widget(BaseModel):
    """
    看板中的单个组件（图表、表格、KPI 卡片等）。

    每个 Widget 由三部分组成：
    - dataset: 数据来源（查什么指标、怎么过滤）
    - chart: 渲染配置（图表类型、轴映射）
    - position: 布局位置（在网格中的坐标和尺寸）

    Attributes:
        id: Widget 唯一标识符（如 "chart_revenue"、"kpi_total_assets"）
        type: Widget 类型，默认 "chart"（可扩展为 "table"、"kpi" 等）
        dataset: 数据集定义，包含指标、维度、过滤条件等
        chart: 图表渲染配置，定义图表类型和轴映射
        position: 布局位置，控制 Widget 在看板中的排列
    """
    id: str
    type: str = "chart"
    dataset: Dataset
    chart: ChartConfig
    position: Position


# =========================
# Dashboard DSL 顶层定义
# =========================

class DashboardDSL(BaseModel):
    """
    Dashboard DSL 顶层模型，完整描述一个看板的配置。

    DSL（Domain Specific Language）是看板的"设计图纸"，包含：
    - 元信息：id、title、version
    - 全局筛选器：filters，作用于所有 Widget
    - 组件列表：widgets，每个 Widget 独立定义数据和渲染

    校验规则：
    - version 强制为 "v1"（当前仅支持 v1 版本）

    Attributes:
        id: 看板唯一标识符（如 "dashboard_001"）
        title: 看板标题（如 "财务分析看板"）
        version: DSL 版本号，当前仅支持 "v1"，由 field_validator 强制校验
        filters: 全局筛选器列表，用户选择后注入到所有 Widget 的 Dataset 查询中
        widgets: Widget 组件列表，每个 Widget 独立描述数据来源和渲染方式
    """
    id: str
    title: str
    version: str = "v1"
    filters: List[FilterItem] = Field(default_factory=list)
    widgets: List[Widget]

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """
        校验 DSL 版本号，当前仅支持 v1。

        版本号是 DSL 的兼容性契约，前端解析器依赖 version 字段决定解析策略。
        非 v1 版本直接拒绝，避免使用不兼容的 DSL 导致渲染异常。

        Args:
            v: 版本号字符串

        Returns:
            校验通过的版本号

        Raises:
            ValueError: 当版本号不是 "v1" 时
        """
        if v != "v1":
            raise ValueError("DSL version must be v1")
        return v


# =========================
# 渲染请求体
# =========================

class DashboardRenderRequest(BaseModel):
    """
    看板渲染请求体，支持两种模式：直接传 DSL 或通过 dashboard_id 引用已存储的看板。

    渲染流程：
    1. 若提供 dashboard_id → 从数据库加载 DSL JSON
    2. 若直接提供 dsl → 直接使用
    3. runtime_filters 合并到每个 Widget 的 Dataset filters 中
    4. 逐个 Widget 执行查询并组装图表数据

    Attributes:
        dsl: 直接传入的 DSL 对象（与 dashboard_id 二选一）
        dashboard_id: 已存储看板的 ID（与 dsl 二选一）
                      系统会从 dashboard 表加载对应的 DSL JSON
        runtime_filters: 运行时筛选条件，由前端根据用户在筛选器中的选择传入
                         如 {"company": ["华为技术有限公司"], "year": [2025]}
                         这些条件会合并（覆盖）到每个 Widget 的 Dataset filters 中
    """
    dsl: Optional[DashboardDSL] = None
    dashboard_id: Optional[str] = None
    runtime_filters: Dict = Field(default_factory=dict)
