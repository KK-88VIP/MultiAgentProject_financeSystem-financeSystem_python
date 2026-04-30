# -*- coding: utf-8 -*-
"""
@file: sql_guard.py
@version: 0.1.0
@purpose: SQL 安全校验核心模块，占位用于 SQLGlot 解析与白名单校验。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy


SQL 安全守卫模块 (sql_guard.py)

本模块是系统数据安全的最后一道防线，负责对即将执行的 SQL 语句进行严格的语法解析和
白名单校验。无论上游 SQL 生成逻辑是否存在缺陷，本模块都能拦截非法访问，确保数据库
仅执行符合安全策略的只读查询。

核心职责：
1. 仅允许 SELECT 查询（禁止 DROP / DELETE / UPDATE / INSERT / ALTER 等写操作）。
2. 校验涉及的表名必须在预定义白名单内，防止跨表越权访问。
3. 校验涉及的字段名必须在预定义白名单内，防止敏感字段泄露。
4. 拦截明显的危险关键字（如 DROP、DELETE），作为快速第一道过滤。
5. 强制为所有查询添加或覆盖 LIMIT 子句，限制单次返回行数上限。
6. 注入 MySQL 执行超时语句，防止慢查询拖垮数据库连接池。

设计要点：
- 基于 sqlglot 库对 SQL 进行 AST 解析，实现语法级的精确校验，避免正则匹配的疏漏。
- 所有白名单配置均来自 `app.security.whitelist`，便于集中维护。
- 校验失败时抛出明确的 `ValueError` 异常，由上层统一捕获处理并返回友好错误信息。
"""

import re
from typing import Set

import sqlglot
from sqlglot import exp

from app.core.config import settings
from app.security.whitelist import (
    ALLOWED_COLUMNS,
    ALLOWED_TABLES,
    FORBIDDEN_KEYWORDS,
)


class SQLGuard:
    """
    SQL 安全守卫类

    使用方法：
        guard = SQLGuard()
        safe_sql = guard.validate(raw_sql)
    """

    def validate(self, sql: str) -> str:
        """
        对输入的 SQL 进行完整的安全校验，并返回经过强制策略加固的安全 SQL。

        执行流程：
            1. 快速关键字拦截（性能优化，提前过滤明显恶意语句）。
            2. 使用 sqlglot 解析 SQL 为 AST。
            3. 校验语句类型必须为 SELECT。
            4. 校验涉及的表名均在白名单内。
            5. 校验涉及的字段名均在白名单内。
            6. 强制添加或覆盖 LIMIT 子句为配置的最大允许值。
            7. 在 SQL 前注入 MySQL 执行超时设置语句。

        参数：
            sql: 待校验的原始 SQL 字符串。

        返回：
            经过加固的安全 SQL 字符串，可能包含多条语句（如 SET + SELECT）。

        异常：
            ValueError: 当 SQL 不符合任一安全策略时抛出，包含具体原因。
        """
        # 步骤1：快速关键字拦截（无需解析 AST）
        self._check_forbidden_keywords(sql)

        # 步骤2：解析 SQL 为 AST，解析失败则抛出异常
        try:
            parsed = sqlglot.parse_one(sql)
        except Exception as e:
            raise ValueError(f"SQL parse error: {e}")

        # 步骤3：仅允许 SELECT 语句
        self._check_select_only(parsed)

        # 步骤4：校验表名白名单
        self._check_tables(parsed)

        # 步骤5：校验字段名白名单
        self._check_columns(parsed)

        # 步骤6：强制 LIMIT
        sql = self._enforce_limit(parsed)

        # 步骤7：注入执行超时限制
        sql = self._inject_timeout(sql)

        return sql

    # =========================
    # 校验逻辑（内部方法）
    # =========================

    def _check_forbidden_keywords(self, sql: str):
        """
        基于字符串匹配拦截危险关键字。

        目的：
            - 在 AST 解析前快速识别明显恶意 SQL（如 DROP TABLE）。
            - 作为防御深度的一环，即使 AST 解析器存在潜在漏洞，此层仍能提供基础保护。

        方法：
            将 SQL 转为大写，遍历 FORBIDDEN_KEYWORDS 黑名单，若存在子串匹配则立即拒绝。
        """
        upper_sql = sql.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            if keyword in upper_sql:
                raise ValueError(f"Forbidden keyword detected: {keyword}")

    def _check_select_only(self, parsed: exp.Expression):
        """
        确保 AST 根节点为 SELECT 语句。

        原理：
            sqlglot.parse_one() 返回的表达式对象类型为 exp.Select 当且仅当 SQL 是 SELECT 查询。
            若非 SELECT 类型（如 exp.Insert, exp.Delete），则直接拒绝。
        """
        if not isinstance(parsed, exp.Select):
            raise ValueError("Only SELECT statements are allowed")

    def _check_tables(self, parsed: exp.Select):
        """
        遍历 AST 中所有表引用，确保每个表名均在 ALLOWED_TABLES 白名单内。

        实现细节：
            - 使用 `parsed.find_all(exp.Table)` 递归查找所有表节点（包括 FROM、JOIN 等子句中的表）。
            - 提取表名（忽略数据库前缀）并与白名单比对。
        """
        tables: Set[str] = set()

        for table in parsed.find_all(exp.Table):
            tables.add(table.name)

        for t in tables:
            if t not in ALLOWED_TABLES:
                raise ValueError(f"Table not allowed: {t}")

    def _check_columns(self, parsed: exp.Select):
        """
        遍历 AST 中所有列引用，确保每个列名均在 ALLOWED_COLUMNS 白名单内。

        注意：
            - 此处仅提取纯列名（exp.Column 的 name 属性），忽略表别名前缀。
            - 若 SQL 中包含派生列或别名，其原始列名仍会被 AST 捕获并校验。
            - 白名单需包含所有可查询字段，包括维度字段（如 company_name）和指标字段（如 revenue）。
        """
        columns: Set[str] = set()

        for col in parsed.find_all(exp.Column):
            # 只取列名（忽略表前缀）
            if col.name:
                columns.add(col.name)

        allowed = ALLOWED_COLUMNS | self._collect_select_aliases(parsed)
        for c in columns:
            if c not in allowed:
                raise ValueError(f"Column not allowed: {c}")

    def _collect_select_aliases(self, parsed: exp.Select) -> Set[str]:
        """
        SELECT 列表中的 AS 别名（如 SUM(...) AS revenue）会出现在 ORDER BY 等子句的
        Column 引用中；这些不是物理表字段，但属于本查询的合法输出名，应允许通过校验。
        """
        names: Set[str] = set()
        for proj in parsed.expressions:
            if not isinstance(proj, exp.Alias):
                continue
            al = proj.args.get("alias")
            if isinstance(al, exp.Identifier) and al.name:
                names.add(al.name)
            elif isinstance(al, str) and al:
                names.add(al)
        return names

    # =========================
    # 强制策略（内部方法）
    # =========================

    def _enforce_limit(self, parsed: exp.Select) -> str:
        """
        强制添加或覆盖 LIMIT 子句，使用配置的最大行数限制。

        目的：
            - 防止因 SQL 生成遗漏 LIMIT 导致的全表扫描或结果集过大。
            - 若已有 LIMIT，将其值替换为 MAX_LIMIT，防止用户通过前端绕过限制。

        实现：
            - 使用 exp.Limit 表达式节点设置 LIMIT 值。
            - 调用 parsed.sql() 重新生成修改后的 SQL 字符串。
        """
        limit_value = settings.MAX_LIMIT
        sql = parsed.sql()
        # 兼容 sqlglot 在不同方言/版本下对 Limit AST 的序列化差异，
        # 统一用字符串方式确保语句末尾始终为 "LIMIT <n>"。
        if re.search(r"\bLIMIT\b", sql, flags=re.IGNORECASE):
            return re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {limit_value}", sql, flags=re.IGNORECASE)
        return f"{sql} LIMIT {limit_value}"

    def _inject_timeout(self, sql: str) -> str:
        """
        在 SELECT 语句前注入 MySQL 会话级执行超时设置。

        背景：
            MySQL 5.7+ 支持 `MAX_EXECUTION_TIME` 提示，单位为毫秒，可限制单条 SELECT 的执行时长。

        返回：
            形如 "SET SESSION MAX_EXECUTION_TIME=3000; SELECT ..." 的多语句字符串。
        """
        timeout = settings.SQL_TIMEOUT_MS
        return f"SET SESSION MAX_EXECUTION_TIME={timeout}; {sql}"