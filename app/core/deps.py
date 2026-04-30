# -*- coding: utf-8 -*-
"""
@file: deps.py
@version: 0.2.0
@purpose: 依赖注入定义，集中管理公共依赖对象。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
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
from app.services.metric_service import MetricCalculator
from app.services.permission_service import PermissionService
from app.services.query_service import QueryService
from app.services.sql_builder import SQLBuilder
from app.db.query_executor import QueryExecutor
from app.services.analysis_engine import AnalysisEngine
from app.services.insight_builder import InsightBuilder
from app.security.permission_injector import PermissionInjector
from cache.query_cache import QueryCache
from planner.query_planner import QueryPlanner
from planner.sql_generator import SQLGenerator

permission_service = PermissionService()

_conversation_manager: ConversationContextManager | None = None
_llm_client: LLMClient | None = None
_query_cache: QueryCache | None = None
_query_planner: QueryPlanner | None = None


def _get_conversation_manager() -> ConversationContextManager:
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationContextManager()
    return _conversation_manager


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def _get_query_cache() -> QueryCache:
    global _query_cache
    if _query_cache is None:
        _query_cache = QueryCache()
    return _query_cache


def _get_query_planner() -> QueryPlanner:
    global _query_planner
    if _query_planner is None:
        _query_planner = QueryPlanner()
    return _query_planner


def get_query_service(db: AsyncSession = Depends(get_db)) -> QueryService:
    """组装智能问数编排服务（按请求注入 DB 与公司仓库）。"""
    company_repo = CompanyRepository(db)
    return QueryService(
        intent_service=IntentService(
            llm_client=_get_llm_client(), company_repo=company_repo
        ),
        sql_builder=SQLBuilder(),
        sql_guard=SQLGuard(),
        query_executor=QueryExecutor(),
        metric_calculator=MetricCalculator(),
        conversation_manager=_get_conversation_manager(),
        audit_logger=AuditService(),
        llm_client=_get_llm_client(),
        query_planner=_get_query_planner(),
        sql_generator=SQLGenerator(),
        query_cache=_get_query_cache(),
        analysis_engine=AnalysisEngine(),
        insight_builder=InsightBuilder(),
        permission_injector=PermissionInjector(),
    )
