# -*- coding: utf-8 -*-
"""
@file: whitelist.py
@version: 0.1.0
@purpose: 安全白名单定义，集中维护允许表与字段。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy


SQL 白名单配置模块 (whitelist.py)

本模块为 SQLGuard 提供静态的安全白名单配置，明确声明了允许访问的数据库表名、
字段名以及禁止出现的危险关键字。所有 SQL 校验均依赖此白名单，遵循"默认拒绝，
仅允许明确声明"的安全原则。

设计原则：
1. 最小权限：只允许访问明确声明的表和字段，未列出的均视为非法。
2. 集中维护：所有白名单均在此文件中定义，避免散落在多处导致不一致。
3. 自动同步：指标字段白名单从 metric_registry 自动提取，减少人工维护成本。
4. 防御深度：黑名单关键字拦截作为 AST 解析前的快速过滤层。

⚠️ 维护提醒：
- 表名和字段名必须与数据库物理结构完全一致（区分大小写）。
- 若 metric_registry 中新增原始指标（raw），其 `column` 字段会自动加入白名单。
- 若数据库新增维度字段（如 `quarter`），需手动添加到 BASE_COLUMNS。
"""

from semantic.registry import MetricRegistry

# =========================
# 表白名单（物理表名）
# =========================
# 仅这三张财务主表允许被查询，其他表（如系统表、用户表）一律拦截。
# 表名需与 SQLBuilder 中的 TABLE_MAPPING 值保持一致。
ALLOWED_TABLES = {
    "com_kk_sub_bs_risk_ident_t",  # 资产负债表风险识别明细
    "com_kk_sub_pl_risk_ident_t",  # 利润表风险识别明细
    "com_kk_sub_cf_risk_ident_t",  # 现金流量表风险识别明细
    "com_kk_sub_company_d",        # 公司维表
}


# =========================
# 字段白名单
# =========================

# 维度字段（必须手动维护）
# 这些字段用于 WHERE、GROUP BY、ORDER BY 中的筛选和分组。
# 若后续增加季度、月份等维度，需在此处同步添加。
BASE_COLUMNS = {
    "company_code",
    "company_cn_name",  # 公司中文名称
    "company_en_name",
    "period_id",        # 报告期（财年/期间）
    "report_item_code",
    "report_item_cn_name",
    "report_item_en_name",
    "risk_identification",
}

# 指标字段（从 metric_registry 自动提取）
# 遍历所有指标元数据，仅收集 type="raw" 的 column 字段。
# 派生指标（derived）没有独立的 column，故不加入白名单。
METRIC_COLUMNS = set()
_registry = MetricRegistry()

for metric, meta in (_registry._metrics or {}).items():  # noqa: SLF001
    # 仅原始指标有 column 字段，派生指标需通过依赖字段间接访问
    if meta.get("type") == "raw":
        col = meta.get("column")
        if col:
            METRIC_COLUMNS.add(col)

# 合并维度字段与指标字段，构成完整的允许字段集合
ALLOWED_COLUMNS = BASE_COLUMNS.union(METRIC_COLUMNS)


# =========================
# 禁止关键字（简单拦截）
# =========================
# 这些关键字若在 SQL 字符串中出现（不区分大小写），将直接拒绝执行。
# 此拦截在 AST 解析前进行，可快速过滤明显的恶意注入。
# 注意：不在此拦截分号 `;`，否则与「用户 SQL 合法结尾分号」及多语句执行策略难以并存；
# 多语句防护主要依赖 SQLGlot 单语句解析与危险关键字拦截。
FORBIDDEN_KEYWORDS = [
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