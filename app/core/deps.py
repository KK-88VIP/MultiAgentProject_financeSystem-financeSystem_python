# -*- coding: utf-8 -*-
"""
@file: deps.py
@version: 0.2.0
@purpose: 依赖注入定义，集中管理公共依赖对象。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy


依赖注入工厂模块 (deps.py)

本模块是 FastAPI 依赖注入体系的核心组装层，负责在请求生命周期内
创建并组装所有业务子服务，最终返回完整的 QueryService 实例。

设计思路：
- FastAPI 的 Depends 机制会在每次请求时调用工厂函数，实现"按请求注入"。
- 重型单例组件（LLMClient、QueryCache、QueryPlanner 等）采用懒加载单例模式：
  模块级全局变量 + 工厂函数，首次调用时创建，后续复用同一实例。
- 轻量无状态组件（SQLGuard、MetricService 等）每次请求直接新建实例。
- QueryService 是最终的编排器，本模块将所有子模块注入其构造函数。

依赖关系图（简化）：
    路由层 (query.py)
        -> Depends(get_query_service)
            -> Depends(get_db)                    # 异步数据库会话
            -> CompanyRepository(db)              # 公司数据仓库（依赖 DB 会话）
            -> IntentService(llm, company_repo)   # 意图解析（依赖 LLM + 公司仓库）
            -> SQLGuard()                         # SQL 安全校验（无状态）
            -> QueryExecutor()                    # SQL 执行器（无状态）
            -> MetricService()                    # 派生指标计算（无状态）
            -> ConversationContextManager()       # 对话上下文（懒加载单例）
            -> AuditService()                     # 审计日志（无状态）
            -> LLMClient()                        # LLM 客户端（懒加载单例）
            -> QueryPlanner()                     # 查询计划构建器（懒加载单例）
            -> SQLGenerator()                     # SQL 生成器（无状态）
            -> QueryCache()                       # 查询缓存（懒加载单例）
            -> AnalysisEngine()                   # 确定性分析引擎（无状态）
            -> InsightBuilder()                   # 洞察构建器（无状态）
            -> PermissionInjector()               # 权限注入器（无状态）
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.company_repository import CompanyRepository
from app.db.session import get_db
from app.llm.client import LLMClient
from app.security.sql_guard import SQLGuard
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationContextManager
from app.services.intent_service import IntentService
from app.services.metric_service import MetricService
from app.services.permission_service import PermissionService
from app.services.query_service import QueryService
from app.db.query_executor import QueryExecutor
from app.services.analysis_engine import AnalysisEngine
from app.services.insight_builder import InsightBuilder
from app.security.permission_injector import PermissionInjector
from cache.query_cache import QueryCache
from planner.query_planner import QueryPlanner
from planner.sql_generator import SQLGenerator

# =========================
# 全局服务实例
# =========================

# 权限服务：管理用户数据权限（如可访问的公司列表）
# 当前为无状态服务，直接模块级实例化即可
permission_service = PermissionService()


# =========================
# 懒加载单例管理
# =========================
# 以下全局变量 + 工厂函数实现懒加载单例模式。
# 原因：LLMClient、QueryCache、QueryPlanner、ConversationContextManager
# 初始化开销较大（如加载模型配置、建立 Redis 连接等），
# 采用懒加载确保只在首次请求时创建，整个应用生命周期内复用同一实例。
# 线程安全性说明：FastAPI 基于 asyncio 单线程模型，不存在竞态条件。

# 对话上下文管理器：维护用户多轮对话状态（如上一轮查询的公司、年份等）
_conversation_manager: ConversationContextManager | None = None

# LLM 客户端：封装大模型 API 调用（意图解析、流式摘要生成等）
_llm_client: LLMClient | None = None

# 查询缓存：基于 QueryPlan + 权限 scope 的哈希缓存，TTL 300s
_query_cache: QueryCache | None = None

# 查询计划构建器：将 QueryIR 转换为确定性的 QueryPlan
_query_planner: QueryPlanner | None = None


def _get_conversation_manager() -> ConversationContextManager:
    """
    获取对话上下文管理器单例。

    ConversationContextManager 负责：
    - 从 Redis 读取用户历史对话上下文（公司、年份、指标等）
    - 用上下文补全当前 IR 中缺失的字段（如追问"那利润呢？"自动补全公司）
    - 查询完成后更新上下文

    Returns:
        ConversationContextManager 单例实例
    """
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationContextManager()
    return _conversation_manager


def _get_llm_client() -> LLMClient:
    """
    获取 LLM 客户端单例。

    LLMClient 负责：
    - 意图解析：将自然语言问题解析为结构化 QueryIR
    - 流式摘要：对查询结果生成财务分析文本（SSE 流式推送）
    - 内部管理 API Key、Base URL、超时、重试等配置

    Returns:
        LLMClient 单例实例
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def _get_query_cache() -> QueryCache:
    """
    获取查询缓存单例。

    QueryCache 负责：
    - 基于 QueryPlan（语义层版本 + 指标 + 筛选条件）和权限 scope 生成缓存 key
    - 缓存命中时直接返回结果，跳过 SQL 生成和执行，显著降低数据库压力
    - TTL 300 秒，缓存命中标记通过 SSE/HTTP 返回（cache=true）

    Returns:
        QueryCache 单例实例
    """
    global _query_cache
    if _query_cache is None:
        _query_cache = QueryCache()
    return _query_cache


def _get_query_planner() -> QueryPlanner:
    """
    获取查询计划构建器单例。

    QueryPlanner 负责：
    - 将 QueryIR（意图解析的中间表示）转换为确定性的 QueryPlan
    - 展开指标别名、确定数据源表、分组/排序规则
    - 生成 post_compute 列表（派生指标，禁止下推 SQL）

    Returns:
        QueryPlanner 单例实例
    """
    global _query_planner
    if _query_planner is None:
        _query_planner = QueryPlanner()
    return _query_planner


# =========================
# 核心工厂函数
# =========================

def get_query_service(db: AsyncSession = Depends(get_db)) -> QueryService:
    """
    组装智能问数编排服务（按请求注入 DB 与公司仓库）。

    这是 FastAPI 路由层的依赖入口，每次 POST /api/query/ask 请求到达时，
    FastAPI 会自动调用此函数，完成以下工作：
    1. 通过 Depends(get_db) 获取异步数据库会话（请求级生命周期）
    2. 基于 DB 会话创建 CompanyRepository（公司数据查询）
    3. 将所有子服务注入 QueryService 构造函数
    4. 返回完整的 QueryService 实例供路由使用

    Args:
        db: 异步数据库会话，由 FastAPI 的 get_db 依赖注入提供，
            请求结束时自动关闭（async with 管理生命周期）

    Returns:
        组装完成的 QueryService 实例，包含所有子模块依赖
    """
    # 公司仓库：查询公司信息（名称匹配、授权校验等），依赖当前请求的 DB 会话
    company_repo = CompanyRepository(db)

    return QueryService(
        # 意图解析服务：自然语言 -> QueryIR（指标、维度、过滤条件等）
        # 依赖 LLM 客户端（调用大模型）和公司仓库（公司名称匹配与消歧）
        intent_service=IntentService(
            llm_client=_get_llm_client(), company_repo=company_repo
        ),
        # SQL 安全守卫：校验 SQL 合法性（仅允许 SELECT）、白名单表名、
        # 敏感字段拦截、强制 LIMIT 1000、超时注入
        sql_guard=SQLGuard(),
        # 查询执行器：异步执行安全 SQL，返回结果集
        query_executor=QueryExecutor(),
        # 指标计算服务：计算派生指标（如毛利率 = (营收-成本)/营收）
        # 派生指标禁止下推 SQL，统一在结果集上 post_compute
        metric_service=MetricService(),
        # 对话上下文管理器：维护多轮对话状态，支持追问补全
        conversation_manager=_get_conversation_manager(),
        # 审计日志服务：记录每次查询的全链路信息（用户、SQL、耗时、状态）
        audit_logger=AuditService(),
        # LLM 客户端：用于流式生成数据摘要（财务分析话术）
        llm_client=_get_llm_client(),
        # 查询计划构建器：QueryIR -> QueryPlan（确定性执行计划）
        query_planner=_get_query_planner(),
        # SQL 生成器：QueryPlan -> 可执行 SQL（问数与看板统一路径）
        sql_generator=SQLGenerator(),
        # 查询缓存：基于 plan + scope 哈希缓存，避免重复查询
        query_cache=_get_query_cache(),
        # 确定性分析引擎：统计、排名、趋势、异常检测等（不依赖 LLM）
        analysis_engine=AnalysisEngine(),
        # 洞察构建器：将分析结果转换为机器可读的洞察文本
        insight_builder=InsightBuilder(),
        # 权限注入器：根据用户授权的公司列表，在 SQL 中注入 WHERE 条件
        permission_injector=PermissionInjector(),
    )
