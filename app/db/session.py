# -*- coding: utf-8 -*-
"""
@file: session.py
@version: 0.1.0
@purpose: 数据库引擎与会话工厂初始化。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy


数据库会话管理模块 (session.py)

本模块负责创建并管理 SQLAlchemy 异步数据库引擎与会话，为整个应用提供统一的数据连接入口。
基于 SQLAlchemy 2.0 的异步特性构建，配合 `aiomysql` 驱动实现非阻塞的数据库访问。

核心职责：
1. 创建全局异步引擎 (`engine`)，管理底层连接池
2. 提供会话工厂 (`AsyncSessionLocal`)，用于按需生成独立的事务会话
3. 提供 FastAPI 依赖注入函数 (`get_db`)，确保每次请求会话正确创建与释放

注意：
- 本模块不定义 ORM 模型类（因本项目表结构由 DataWorks 维护），仅用于执行原生 SQL
- 会话生命周期遵循 FastAPI 请求生命周期，请求结束自动关闭连接，避免连接泄漏
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# =========================
# 创建异步引擎（全局单例）
# =========================
# engine 是整个应用的数据库连接池入口，只创建一次，全局复用。
# 通过 `create_async_engine` 生成异步引擎，内部管理连接池生命周期。
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # 当 DEBUG=True 时，打印实际执行的 SQL 语句（仅开发环境建议开启）
    pool_size=settings.DB_POOL_SIZE,      # 连接池常驻连接数
    max_overflow=settings.DB_MAX_OVERFLOW, # 峰值时额外允许创建的连接数
    pool_timeout=settings.DB_POOL_TIMEOUT, # 从池中获取连接的最大等待时间（秒）
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    connect_args={
        "connect_timeout": settings.DB_CONNECT_TIMEOUT,
    },
)

# =========================
# Session 工厂
# =========================
# `async_sessionmaker` 是生成会话对象的工厂函数。
# 每次调用 `AsyncSessionLocal()` 都会创建一个新的异步会话实例。
AsyncSessionLocal = async_sessionmaker(
    bind=engine,                    # 绑定到上面创建的引擎
    class_=AsyncSession,            # 指定会话类为异步版本
    expire_on_commit=False,         # 提交后不使对象过期，便于在事务外继续访问已加载的属性
    # autocommit=False,             # 默认关闭自动提交，需显式调用 commit() 或 rollback()
    # autoflush=False,              # 默认不自动刷新，需要手动 flush() 或在 commit 前自动执行
)

# =========================
# FastAPI 依赖注入
# =========================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    为 FastAPI 路由提供数据库会话的依赖注入函数。

    使用方式：
        from fastapi import Depends
        from app.db.session import get_db

        @router.get("/some-path")
        async def some_handler(db: AsyncSession = Depends(get_db)):
            # 在此函数内部使用 db 执行数据库操作
            ...

    工作原理：
    - FastAPI 在处理每个请求时调用本函数，进入 `async with` 上下文，
      通过 `yield` 将会话对象注入到路由函数。
    - 路由函数执行完毕后，自动回到 `finally` 块，确保会话被正确关闭，
      无论函数正常返回还是抛出异常。

    注意事项：
    - 不要在路由函数外部长期持有该会话对象，会话与请求生命周期绑定。
    - 若需要在后台任务中使用数据库，应单独创建会话，不可复用请求会话。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # 显式关闭会话，释放连接回连接池。
            # 注意：即使未调用 commit() 或 rollback()，关闭会话也会自动回滚未提交的事务。
            await session.close()