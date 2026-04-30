# -*- coding: utf-8 -*-
"""
@file: permission_injector.py
@version: 0.1.0
@purpose: 权限条件注入模块，占位用于为查询增加授权公司过滤条件。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

# 使用sqlglot对SQL进行语法树（AST）重写。无论原SQL有没有WHERE条件，它都会强制追加公司权限过滤。
import sqlglot
from sqlglot import exp


class PermissionInjector:
    @staticmethod
    def inject_company_filter(sql: str, allowed_companies: list[str]) -> str:
        """
        向 SQL 中强制注入公司权限过滤条件
        例如: SELECT * FROM table -> SELECT * FROM table WHERE company_cn_name IN ('A', 'B')
        """
        if not allowed_companies:
            return sql

        # 解析 SQL
        expression = sqlglot.parse_one(sql, read="mysql")

        # 构造过滤条件: company_cn_name IN ('Comp1', 'Comp2')
        company_values = [exp.Literal.string(c) for c in allowed_companies]
        in_condition = exp.In(
            this=exp.column("company_cn_name"),
            field=exp.Tuple(expressions=company_values)
        )

        # 找到 SELECT 语句的主体
        select_stmt = expression.find(exp.Select)

        if select_stmt.args.get("where"):
            # 如果已有 WHERE，使用 AND 连接
            new_where = exp.and_(select_stmt.args["where"].this, in_condition)
            select_stmt.set("where", exp.Where(this=new_where))
        else:
            # 如果没有 WHERE，直接加上
            select_stmt.set("where", exp.Where(this=in_condition))

        return expression.sql(dialect="mysql")

# 使用示例：
# injector = PermissionInjector()
# safe_sql = injector.inject_company_filter("SELECT * FROM com_kk_sub_bs_t", ["华为", "腾讯"])
# print(safe_sql)
# -> SELECT * FROM com_kk_sub_bs_t WHERE company_cn_name IN ('华为', '腾讯')
