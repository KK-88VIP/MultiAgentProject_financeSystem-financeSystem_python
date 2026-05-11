# -*- coding: utf-8 -*-
"""
@file: whitelist.py
@version: 0.1.0
@purpose: 安全白名单定义，集中维护允许表与字段。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy


SQL 白名单配置模块 (whitelist.py)

本模块为 SQLGuard 提供白名单配置，采用“语义层主数据 + 安全覆盖差量”的策略：
1. 主数据：来自 semantic/models.yaml、semantic/dimensions.yaml、semantic/metrics.yaml
2. 差量覆盖：来自 semantic/security_overrides.yaml
   - allow：extra_allowed_tables / extra_allowed_columns
   - deny：deny_tables / deny_columns（优先级高于 allow）
3. 关键字：forbidden_keywords 为空时回退到本模块默认值

设计原则：
1. 最小权限：默认拒绝，白名单显式放行。
2. 单一事实源：业务主数据由语义层维护，避免双份配置漂移。
3. 安全可收紧：通过 deny 差量覆盖实现“安全层比语义层更严格”。
4. 防御深度：危险关键字拦截作为 AST 解析前的快速过滤层。
"""

from planner.sql_mappings import DIMENSION_MAPPING, TABLE_MAPPING
from semantic.registry import MetricRegistry

_registry = MetricRegistry()
_overrides = _registry.security_overrides


def _to_str_set(values) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(v) for v in values if v}


# =========================
# 表白名单（物理表名）
# =========================
# 允许查询的表：语义派生 + allow 差量 - deny 差量
_semantic_tables = set(TABLE_MAPPING.values())
_extra_tables = _to_str_set(_overrides.get("extra_allowed_tables"))
_deny_tables = _to_str_set(_overrides.get("deny_tables"))
ALLOWED_TABLES = (_semantic_tables | _extra_tables) - _deny_tables


# =========================
# 字段白名单
# =========================

# 基础字段白名单：语义维度列
BASE_COLUMNS = set(DIMENSION_MAPPING.values())

# 指标字段（从语义注册中心自动提取）
# 遍历所有指标元数据，仅收集 type="raw" 的 column 字段。
# 派生指标（derived）没有独立的 column，故不加入白名单。
METRIC_COLUMNS = set()

for metric, meta in _registry.metrics.items():
    # 仅原始指标有 column 字段，派生指标需通过依赖字段间接访问
    if meta.get("type") == "raw":
        col = meta.get("column")
        if col:
            METRIC_COLUMNS.add(col)

# 合并语义派生列与覆盖差量，deny 优先
_semantic_columns = BASE_COLUMNS.union(METRIC_COLUMNS)
_extra_columns = _to_str_set(_overrides.get("extra_allowed_columns"))
_deny_columns = _to_str_set(_overrides.get("deny_columns"))
ALLOWED_COLUMNS = (_semantic_columns | _extra_columns) - _deny_columns


# =========================
# 禁止关键字（简单拦截）
# =========================
# 这些关键字若在 SQL 字符串中出现（不区分大小写），将直接拒绝执行。
# 此拦截在 AST 解析前进行，可快速过滤明显的恶意注入。
# 注意：不在此拦截分号 `;`，否则与「用户 SQL 合法结尾分号」及多语句执行策略难以并存；
# 多语句防护主要依赖 SQLGlot 单语句解析与危险关键字拦截。
_DEFAULT_FORBIDDEN_KEYWORDS = [
    "DROP",         # 删除表/库
    "DELETE",       # 删除数据
    "UPDATE",       # 更新数据
    "INSERT",       # 插入数据
    "TRUNCATE",     # 清空表
    "ALTER",        # 修改表结构
    "CREATE",       # 创建表/库
    "REPLACE",      # 替换数据
    "--",           # SQL 单行注释（可能用于绕过后续语句）
    "/*",           # 多行注释起始
    "*/",           # 多行注释结束
]

_forbidden_from_overrides = _to_str_set(_overrides.get("forbidden_keywords"))
FORBIDDEN_KEYWORDS = list(_forbidden_from_overrides) if _forbidden_from_overrides else _DEFAULT_FORBIDDEN_KEYWORDS