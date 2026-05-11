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


安全校验流程（按顺序执行，任一步骤失败即终止）：
    原始 SQL -> 关键字拦截 -> AST 解析 -> 语句类型校验 -> 表名校验
    -> 字段名校验 -> LIMIT 加固 -> 超时注入 -> 安全 SQL


依赖说明：
- sqlglot: 用于将 SQL 字符串解析为抽象语法树 (AST)，便于结构化的安全检查
- 白名单配置 (whitelist): 定义了 ALLOWED_COLUMNS、ALLOWED_TABLES、FORBIDDEN_KEYWORDS
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
    SQL 安全守卫，对 SQL 查询进行多层安全校验和加固。

    采用"纵深防御"策略：即使某一层校验被绕过，后续层仍能拦截。
    校验顺序经过精心设计——先做低成本的文本匹配，再做高成本的 AST 解析，
    以最小化性能开销。
    """

    def validate(self, sql: str) -> str:
        """
        对 SQL 执行完整的安全校验流程，并返回加固后的安全 SQL。

        校验步骤：
        1. 快速关键字拦截（纯文本匹配，无需解析 AST，性能开销最低）
        2. 将 SQL 解析为抽象语法树 (AST)，解析失败说明 SQL 格式异常
        3. 校验语句类型，仅允许 SELECT
        4. 校验表名白名单
        5. 校验字段名白名单
        6. 强制注入或替换 LIMIT 子句
        7. 注入数据库执行超时指令

        Args:
            sql: 待校验的 SQL 查询字符串

        Returns:
            经过安全加固的 SQL 字符串（含超时指令和强制 LIMIT）

        Raises:
            ValueError: 当 SQL 存在安全风险时（包含禁用关键字、非 SELECT 语句、
                       引用未授权的表或字段等）
        """
        # 步骤1：快速关键字拦截（纯文本匹配，无需解析 AST）
        # 在进入昂贵的 AST 解析前，先用低成本的字符串匹配过滤掉明显的危险 SQL
        self._check_forbidden_keywords(sql)

        # 步骤2：解析 SQL 为 AST（抽象语法树）
        # 使用 sqlglot 将 SQL 文本转为结构化的树形表示，便于后续的精确校验
        try:
            parsed = sqlglot.parse_one(sql)
        except Exception as e:
            raise ValueError(f"SQL parse error: {e}")

        # 步骤3：仅允许 SELECT 语句
        # 检查 AST 根节点类型，拒绝 INSERT/UPDATE/DELETE/DDL 等非查询语句
        self._check_select_only(parsed)

        # 步骤4：校验表名白名单
        # 遍历 AST 中所有 Table 节点，确保引用的表都在允许列表中
        self._check_tables(parsed)

        # 步骤5：校验字段名白名单
        # 遍历 AST 中所有 Column 节点，确保引用的字段都在允许列表中
        # （SELECT 中自定义的别名也会被加入白名单，避免误判）
        self._check_columns(parsed)

        # 步骤6：强制 LIMIT
        # 确保查询有行数上限，替换过大的 LIMIT 或补充缺失的 LIMIT
        sql = self._enforce_limit(parsed)

        # 步骤7：注入执行超时限制
        # 在 SQL 前添加 MAX_EXECUTION_TIME 指令，防止慢查询长时间占用数据库资源
        sql = self._inject_timeout(sql)

        return sql

    def _check_forbidden_keywords(self, sql: str):
        """
        快速关键字拦截：检查 SQL 中是否包含禁用的关键字。

        采用纯文本匹配（转大写后比较），无需解析 AST，性能开销极低。
        这是第一道防线，能快速过滤掉包含 DML/DDL 关键字的危险 SQL。

        Args:
            sql: 待检查的 SQL 字符串

        Raises:
            ValueError: 当检测到任何禁用关键字时
        """
        # 将 SQL 统一转为大写，避免大小写绕过（如 InSeRt）
        upper_sql = sql.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            if keyword in upper_sql:
                raise ValueError(f"Forbidden keyword detected: {keyword}")

    def _check_select_only(self, parsed: exp.Expression):
        """
        语句类型校验：确保 SQL 是 SELECT 查询语句。

        通过检查 AST 根节点的类型实现，能精确区分 SELECT 与
        INSERT/UPDATE/DELETE/CREATE/DROP 等语句。

        Args:
            parsed: sqlglot 解析后的 AST 表达式

        Raises:
            ValueError: 当语句不是 SELECT 类型时
        """
        if not isinstance(parsed, exp.Select):
            raise ValueError("Only SELECT statements are allowed")

    def _check_tables(self, parsed: exp.Select):
        """
        表名白名单校验：确保查询引用的所有表都在允许列表中。

        使用 AST 的 find_all 方法遍历所有 Table 节点，提取表名后逐一校验。
        相比正则匹配，AST 遍历能准确识别表名，不会被子查询、注释等干扰。

        Args:
            parsed: 解析后的 SELECT 语句 AST

        Raises:
            ValueError: 当发现未授权的表名时
        """
        tables: Set[str] = set()

        # 遍历 AST 中所有 Table 类型的节点，收集引用的表名
        for table in parsed.find_all(exp.Table):
            tables.add(table.name)

        # 逐一校验表名是否在白名单中
        for t in tables:
            if t not in ALLOWED_TABLES:
                raise ValueError(f"Table not allowed: {t}")

    def _check_columns(self, parsed: exp.Select):
        """
        字段名白名单校验：确保查询引用的所有字段都在允许列表中。

        校验范围包括：
        - SQL 中显式引用的列名（如 SELECT col1, table.col2）
        - 但排除 SQL 中 SELECT 子句定义的别名（避免将 AS revenue 误判为非法列）

        Args:
            parsed: 解析后的 SELECT 语句 AST

        Raises:
            ValueError: 当发现未授权的字段名时
        """
        columns: Set[str] = set()

        # 遍历 AST 中所有 Column 类型的节点，提取列名（忽略表前缀）
        # 例如 table.column 只取 "column"，避免表前缀导致误判
        for col in parsed.find_all(exp.Column):
            # 只取列名部分（忽略表名前缀，如 t.col -> col）
            if col.name:
                columns.add(col.name)

        # 合并白名单：预定义的允许列 + SELECT 中自定义的别名
        # 例如 SELECT revenue AS total_income 中的 "total_income" 不应被拦截
        allowed = ALLOWED_COLUMNS | self._collect_select_aliases(parsed)

        # 逐一校验列名是否在合并后的白名单中
        for c in columns:
            if c not in allowed:
                raise ValueError(f"Column not allowed: {c}")

    def _collect_select_aliases(self, parsed: exp.Select) -> Set[str]:
        """
        收集 SELECT 子句中定义的所有列别名。

        这些别名在字段校验时会被加入白名单，避免以下场景的误判：
            SELECT SUM(value) AS revenue -> "revenue" 是别名，不是外部列引用

        Args:
            parsed: 解析后的 SELECT 语句 AST

        Returns:
            SELECT 子句中所有别名的集合
        """
        names: Set[str] = set()

        # 遍历 SELECT 子句中的所有投影表达式（即 SELECT 后面的每一项）
        for proj in parsed.expressions:
            # 只处理带别名的表达式（如 expr AS alias）
            if not isinstance(proj, exp.Alias):
                continue

            # 别名节点可能是 Identifier 对象或纯字符串，兼容两种情况
            al = proj.args.get("alias")
            if isinstance(al, exp.Identifier) and al.name:
                names.add(al.name)
            elif isinstance(al, str) and al:
                names.add(al)
        return names

    def _enforce_limit(self, parsed: exp.Select) -> str:
        """
        强制 LIMIT 加固：确保所有查询都有合理的结果行数上限。

        处理逻辑：
        - 若 SQL 中已存在 LIMIT，将其替换为系统配置的最大值（防止设置过大）
        - 若 SQL 中不存在 LIMIT，追加系统配置的最大值

        这是防止全表扫描和大结果集拖慢数据库的关键保护措施。

        Args:
            parsed: 解析后的 SELECT 语句 AST

        Returns:
            包含强制 LIMIT 的 SQL 字符串
        """
        limit_value = settings.MAX_LIMIT

        # 将 AST 还原为 SQL 字符串，再通过正则操作 LIMIT 子句
        # （直接操作 AST 修改 LIMIT 也可，但正则在此场景下更简洁）
        sql = parsed.sql()

        # 检查 SQL 中是否已存在 LIMIT 子句（不区分大小写）
        if re.search(r"\bLIMIT\b", sql, flags=re.IGNORECASE):
            # 已存在：替换为系统允许的最大值
            return re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {limit_value}", sql, flags=re.IGNORECASE)

        # 不存在：在末尾追加 LIMIT
        return f"{sql} LIMIT {limit_value}"

    def _inject_timeout(self, sql: str) -> str:
        """
        注入执行超时限制：在 SQL 前添加 MAX_EXECUTION_TIME 指令。

        该指令是 MySQL 特有的会话级设置，用于限制单条查询的最大执行时间。
        若查询执行超过指定毫秒数，数据库会自动终止该查询，防止慢查询
        长时间占用连接和计算资源。

        Args:
            sql: 待注入超时的 SQL 字符串

        Returns:
            前缀了超时指令的 SQL 字符串，格式为：
            "SET SESSION MAX_EXECUTION_TIME=<ms>; <原始SQL>"
        """
        timeout = settings.SQL_TIMEOUT_MS
        # 使用分号分隔超时指令和实际查询，在同一个会话中顺序执行
        return f"SET SESSION MAX_EXECUTION_TIME={timeout}; {sql}"
