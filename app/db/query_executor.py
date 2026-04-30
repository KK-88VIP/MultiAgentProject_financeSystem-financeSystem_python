# -*- coding: utf-8 -*-
"""
@file: query_executor.py
@version: 0.2.0
@purpose: SQL 执行器，占位用于受控执行查询并应用 LIMIT 与 timeout 控制。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy


SQL 执行器模块 (query_executor.py)

本模块负责在数据库会话中安全执行已经过 SQLGuard 校验的 SQL 语句，并将结果转换为
统一的 Python 数据结构（字典列表）。它是数据查询链路中的最后一环，聚焦于执行效率、
错误处理和执行监控。

核心职责：
1. 接收已通过安全校验的 SQL 字符串（可能包含多条语句，如 SET + SELECT）。
2. 利用 SQLAlchemy 异步会话执行 SQL，正确处理 MySQL 多语句场景。
3. 将数据库返回的行数据转换为 `List[Dict]` 格式，便于后续 Pandas 处理和 JSON 序列化。
4. 记录每次查询的执行耗时和结果行数，为审计日志提供基础数据。
5. 统一捕获并记录执行异常，不向上层泄露数据库内部错误细节。

设计边界：
- 不做任何 SQL 生成或修改，输入 SQL 必须是 SQLGuard 处理后的安全 SQL。
- 不做业务逻辑加工，仅负责数据获取和格式转换。
- 不管理数据库连接，会话对象由上层（FastAPI 依赖注入）传入并负责生命周期。
"""

import time
from typing import List, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.logger import get_logger

logger = get_logger(__name__)


class QueryExecutor:
    """
    SQL 执行器类

    使用方法：
        executor = QueryExecutor()
        rows = await executor.execute(db_session, safe_sql)
    """

    async def execute(self, db: AsyncSession, sql: str) -> List[Dict]:
        """
        在给定的异步会话中执行 SQL，并返回结构化结果。

        参数：
            db: FastAPI 通过 Depends(get_db) 注入的异步数据库会话。
            sql: 已通过 SQLGuard 校验和加固的 SQL 字符串，可能包含多条语句
                 （例如 "SET SESSION MAX_EXECUTION_TIME=3000; SELECT ..."）。

        返回：
            查询结果的列表，每行为一个字典，键为列名，值为数据库原始值。
            若执行非 SELECT 语句（如 SET），该部分不产生返回行。

        异常：
            任何数据库执行错误（超时、语法错误、连接中断等）将被捕获、
            记录日志后重新抛出，由上层统一异常处理器接管。

        性能说明：
            - 使用 `text(stmt)` 构造 SQLAlchemy 可执行对象。
            - 逐条分割并执行多语句，因为 MySQL 驱动通常不支持在一次 execute 中发送多条语句。
            - 仅最后一条 SELECT 语句的结果会被返回（通常业务 SQL 只有一条 SELECT）。
        """
        # 记录查询开始时间，用于计算执行耗时
        start_time = time.time()

        try:
            # 将可能的复合语句按分号拆分为独立语句
            # 注意：SQLGuard 已确保注入的 SET 语句以分号结尾，拆分后能得到干净的单条语句
            statements = [s.strip() for s in sql.split(";") if s.strip()]

            result_rows = []
            columns = []

            for stmt in statements:
                # 使用 SQLAlchemy text() 构造可执行对象
                result = await db.execute(text(stmt))

                # 只有返回行的语句（SELECT）才会产生结果集
                if result.returns_rows:
                    rows = result.fetchall()
                    columns = result.keys()

                    # 将 Row 对象转换为标准字典列表，方便后续 Pandas 或 JSON 处理
                    result_rows = [dict(zip(columns, row)) for row in rows]

            # 计算总耗时（毫秒）
            latency = int((time.time() - start_time) * 1000)

            logger.info(
                f"[QueryExecutor] success | rows={len(result_rows)} | latency={latency}ms"
            )

            return result_rows

        except Exception as e:
            latency = int((time.time() - start_time) * 1000)

            # 记录错误日志，包含耗时和错误信息，便于问题排查
            logger.error(
                f"[QueryExecutor] failed | latency={latency}ms | error={str(e)}"
            )

            # 重新抛出异常，让上层服务或全局异常处理器决定如何响应客户端
            raise
