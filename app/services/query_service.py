# -*- coding: utf-8 -*-
"""
@file: query_service.py
@version: 0.2.0
@purpose: 智能问数主服务，编排意图解析、澄清流程、SQL 生成、执行与 SSE 输出。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy
"""


# app/services/query_service.py

"""
智能问数核心编排服务 (query_service.py)

本模块是智能问数流程的总指挥，负责将意图解析、SQL 构建、安全校验、数据查询、
指标计算、LLM 总结以及上下文管理等子模块串联为一个完整的 SSE（Server-Sent Events）
流式响应链路。它是前端“对话式问数”交互体验的最终实现者。

核心职责：
1. 接收用户自然语言问题，生成全局追踪 ID（trace_id）。
2. 按顺序调度各子模块：
   - 获取对话上下文（Redis）。
   - 调用 IntentService 解析问题，生成 QueryIR。
   - 进行歧义检测，必要时中断流程并返回澄清选项（clarification）。
   - 调用 SQLGenerator 生成逻辑 SQL。
   - 调用 SQLGuard 进行安全校验和加固。
   - 调用 QueryExecutor 执行 SQL 获取原始数据。
   - 调用 MetricService 计算派生指标。
   - 调用 LLMClient 流式生成数据摘要。
   - 更新用户上下文并记录审计日志。
3. 全程通过 SSE 协议向客户端推送进度事件（thinking、intent、sql、data、summary 等）。
4. 统一处理异常，保证错误信息对客户端友好且内部可追踪。

设计原则：
- 流程控制集中化：仅在本模块编排步骤，具体逻辑由子模块实现。
- 依赖注入：所有子服务通过构造函数传入，便于单元测试和替换实现。
- 可观测性：每个请求分配 trace_id，关键节点输出结构化日志。
- 健壮降级：Redis 或 LLM 异常不影响核心数据查询返回。

SSE 事件约定：
| 事件名         | 说明                                 |
|----------------|--------------------------------------|
| start          | 开始处理，携带 trace_id               |
| intent         | 意图解析完成，返回识别的指标/公司/年份 |
| sql            | SQL 生成完成（仅调试环境推荐输出）     |
| clarification  | 需要用户澄清歧义，中断流程             |
| data           | 查询结果数据返回                      |
| summary        | LLM 生成的文本摘要（流式）            |
| end            | 处理成功结束                          |
| error          | 发生错误，携带错误码和消息             |

注意：
- 本服务依赖 FastAPI 的异步特性，需在路由层使用 `StreamingResponse` 返回。
- SSE 流一旦开始，不能通过 HTTP 状态码改变，所有错误均通过 `error` 事件发送。



完整处理流程（15 步）：
    用户问题
    -> 1. 发送 start 事件
    -> 2. 获取历史对话上下文
    -> 3. LLM 意图解析 -> QueryIR
    -> 3b. 闲聊检测（流式 LLM 对话或兜底文案，不查库）
    -> 4. 用上下文补全 IR 缺失字段
    -> 5. 推送 intent 事件
    -> 6. 歧义检测（可能触发 clarification 并中断）
    -> 7. 构建 QueryPlan
    -> 8. 查询缓存
    -> 9. 缓存未命中：生成 SQL -> 权限注入 -> 安全校验 -> 执行查询
    -> 10. 计算派生指标
    -> 11. 推送 data 事件
    -> 12. 流式生成 LLM 文本摘要
    -> 13. 更新用户对话上下文
    -> 14. 记录审计日志
    -> 15. 发送 end 事件

"""

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator, Dict, Optional

from app.core.logger import get_logger
from app.services.intent_service import IntentService, QueryIR
from app.security.sql_guard import SQLGuard
from app.db.query_executor import QueryExecutor
from app.services.metric_service import MetricService
from app.services.conversation_service import ConversationContextManager
from app.services.audit_service import AuditService as AuditLogger
from app.llm.client import LLMClient
from app.llm.prompts import (
    ANALYSIS_PROMPT,
    CHITCHAT_DEFAULT_BOUNDARY,
    CHITCHAT_PROMPT,
    MAX_COMPANIES_IN_CONVERSATION_CONTEXT,
    format_chitchat_context_block,
    format_company_catalog_for_chitchat,
    question_asks_company_catalog,
    scoped_company_names,
)
from app.models.query import AskRequest, SuggestionItem
from app.security.permission_injector import PermissionInjector
from app.services.analysis_engine import AnalysisEngine
from app.services.insight_builder import InsightBuilder
from cache.query_cache import QueryCache
from planner.query_planner import QueryPlanner
from planner.sql_generator import SQLGenerator

logger = get_logger(__name__)


# =========================
# SSE 工具函数
# =========================
def sse_event(event: str, data: Dict) -> str:
    """
    将事件名和数据字典格式化为符合 SSE (Server-Sent Events) 规范的字符串。

    SSE 协议格式要求：
        - 每行以 "field: value" 形式表示
        - 事件之间以空行分隔（即 "\\n\\n"）
        - data 字段的值为 JSON 字符串，确保结构化数据的完整传输

    Args:
        event: 事件名称，如 "start"、"intent"、"data"、"summary"、"end"、"error"
        data: 事件携带的数据字典，将被序列化为 JSON

    Returns:
        符合 SSE 规范的字符串片段

    示例输出：
        event: intent
        data: {"metrics": ["revenue"], "companies": ["华为"]}

        （末尾有两个换行符作为事件分隔）
    """
    # ensure_ascii=False 确保中文字符正常显示，不会被转义为 \uXXXX
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# =========================
# 主服务类
# =========================
class QueryService:
    """
    问数流程编排服务，串联所有子模块完成端到端的自然语言查询处理。

    设计特点：
    - 所有依赖均为可选（默认 None），便于路由层直接实例化
    - 当子模块未注入时，自动降级到简化链路（如仅返回意图解析结果）
    - 通过异步生成器 (AsyncGenerator) 实现 SSE 流式推送
    """

    def __init__(
        self,
        intent_service: Optional[IntentService] = None, 
        sql_guard: Optional[SQLGuard] = None,
        query_executor: Optional[QueryExecutor] = None,
        metric_service: Optional[MetricService] = None,
        conversation_manager: Optional[ConversationContextManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        llm_client: Optional[LLMClient] = None,
        query_planner: Optional[QueryPlanner] = None,
        sql_generator: Optional[SQLGenerator] = None,
        query_cache: Optional[QueryCache] = None,
        analysis_engine: Optional[AnalysisEngine] = None,
        insight_builder: Optional[InsightBuilder] = None,
        permission_injector: Optional[PermissionInjector] = None,
    ):
        """
        初始化查询服务，注入所有子模块依赖。

        所有参数均为可选，支持渐进式集成：
        - 开发初期可只注入 intent_service，走简化链路
        - 各子模块就绪后逐步注入，自动切换到完整链路

        Args:
            intent_service: 意图解析服务，将自然语言转为 QueryIR
            sql_guard: SQL 安全守卫，校验和加固 SQL
            query_executor: 数据库查询执行器
            metric_service: 指标计算服务，处理派生指标
            conversation_manager: 对话上下文管理器，支持多轮追问
            audit_logger: 审计日志服务，记录每次查询的全链路信息
            llm_client: LLM 客户端，用于生成流式文本摘要
            query_planner: 查询计划构建器
            sql_generator: SQL 生成器
            query_cache: 查询缓存，避免重复查询
            analysis_engine: 确定性分析引擎
            insight_builder: 洞察构建器
            permission_injector: 权限注入器，注入数据权限过滤条件
        """
        self.intent_service = intent_service
        self.sql_guard = sql_guard
        self.query_executor = query_executor
        self.metric_service = metric_service
        self.conversation_manager = conversation_manager
        self.audit_logger = audit_logger
        self.llm_client = llm_client
        self.query_planner = query_planner
        self.sql_generator = sql_generator
        self.query_cache = query_cache
        self.analysis_engine = analysis_engine
        self.insight_builder = insight_builder
        self.permission_injector = permission_injector

    # =========================
    # SSE 主入口
    # =========================
    async def handle_sse_stream(
        self,
        body: Dict,
        user_info: Dict,
        db,
    ) -> AsyncGenerator[str, None]:
        """
        处理单次问数请求的核心方法，通过异步生成器返回 SSE 事件流。

        这是整个系统的主入口，编排了从意图解析到数据返回的完整 15 步流程。
        每个关键步骤通过 yield 推送对应的 SSE 事件，前端可实时展示处理进度。

        Args:
            body: 已校验的请求体字典（通常来自 AskRequest.model_dump()），包含：
                - question: 用户的自然语言问题（必填）
                - clarification: 澄清选择（可选，用于歧义消解后的二次请求）
            user_info: 由路由层解析的用户信息字典，包含：
                - user_id: 用户唯一标识
                - role: 用户角色（如 "admin"、"user"）
                - authorized_companies: 授权访问的公司列表（可选）
            db: 异步数据库会话，由 FastAPI 的 get_db 依赖注入提供

        Yields:
            符合 SSE 格式的字符串片段，每次 yield 发送一个完整事件。
            事件类型包括：start、intent、clarification、sql、data、summary、end、error

        异常处理策略：
            - asyncio.CancelledError: 客户端断开连接，静默结束
            - 其他异常: 记录日志 + 审计，通过 error 事件通知前端，不暴露堆栈
        """
        # 生成全局唯一的追踪 ID，贯穿本次请求的所有日志和审计记录
        trace_id = str(uuid.uuid4())
        # 记录请求开始时间，用于计算总耗时
        start_time = time.time()

        try:
            # 从请求体中提取问题和澄清信息
            question = body.get("question") or ""
            clarification = body.get("clarification") or {}

            user_id = user_info.get("user_id", "anonymous")

            # ---------- 步骤 1：发送开始事件 ----------
            # 通知前端请求处理已启动，trace_id 用于全链路追踪
            yield sse_event("start", {"trace_id": trace_id})

            # ---------- 步骤 2：获取历史对话上下文 ----------
            # 多轮对话场景下，用户的追问可能省略主语（如"那利润呢？"），
            # 需要从上下文中恢复缺失的信息
            context = await self.conversation_manager.get_context(user_id)

            # ---------- 步骤 3：调用 LLM 解析意图，生成初步 IR ----------
            # 将自然语言问题解析为结构化的 QueryIR（查询中间表示），
            # 包含指标、维度、过滤条件、排序等信息
            ir: QueryIR = await self.intent_service.parse_intent(
                question, context
            )

            # 如果请求中携带了澄清后的选择（如用户在前端选择了具体公司），
            # 直接覆盖 IR 中的相应过滤字段
            if clarification:
                # clarification 预期格式：{"company": ["华为技术有限公司"]}
                ir.filters.update(clarification)

            # ---------- 步骤 3b：闲聊检测 ----------
            # 不查库；已注入 LLM 时始终流式生成闲聊回复；失败或未配置时回退到 IR.reply / 默认欢迎语
            if ir.intent_type == "chitchat":
                fallback_reply = (ir.reply or "").strip() or (
                    "你好，我是财务数据智能助手，可以试试问我各公司的营收、利润或资产负债情况。"
                )
                boundary_text = (ir.reply or "").strip() or CHITCHAT_DEFAULT_BOUNDARY
                yield sse_event(
                    "intent",
                    {
                        "intent_type": "chitchat",
                        "metrics": [],
                        "companies": [],
                        "years": [],
                        "reply": None,
                    },
                )
                streamed_any = False
                summary_chunks: list[str] = []
                company_names_for_context: list[str] | None = None
                if self.llm_client:
                    base_ctx = format_chitchat_context_block(context).strip()
                    catalog_appendix = ""
                    if self.intent_service and question_asks_company_catalog(question):
                        try:
                            company_names = (
                                await self.intent_service.list_all_company_names()
                            )
                            catalog_appendix = format_company_catalog_for_chitchat(
                                company_names,
                                user_info.get("authorized_companies") or [],
                            )
                            scoped = scoped_company_names(
                                company_names,
                                user_info.get("authorized_companies") or [],
                            )
                            if scoped:
                                company_names_for_context = scoped[
                                    :MAX_COMPANIES_IN_CONVERSATION_CONTEXT
                                ]
                        except Exception as cat_err:
                            logger.warning(
                                "[QueryService] company catalog for chitchat failed | "
                                "trace_id=%s | %s",
                                trace_id,
                                cat_err,
                            )
                    if catalog_appendix:
                        ctx_blk = (
                            f"{base_ctx}\n\n{catalog_appendix}".strip()
                            if base_ctx
                            else catalog_appendix
                        )
                    else:
                        ctx_blk = base_ctx or "（当前无上一轮问数上下文。）"
                    prompt = CHITCHAT_PROMPT.format(
                        boundary_text=boundary_text,
                        context_block=ctx_blk,
                        question=question,
                    )
                    try:
                        async for chunk in self.llm_client.generate_stream(prompt):
                            if chunk:
                                streamed_any = True
                                summary_chunks.append(chunk)
                                yield sse_event("summary", {"content": chunk})
                    except Exception as llm_err:
                        logger.warning(
                            "[QueryService] chitchat LLM stream failed | trace_id=%s | %s",
                            trace_id,
                            llm_err,
                        )
                if not streamed_any:
                    yield sse_event("summary", {"content": fallback_reply})
                assistant_reply = (
                    "".join(summary_chunks) if summary_chunks else fallback_reply
                )
                if company_names_for_context:
                    await self.conversation_manager.update_context(
                        user_id,
                        {"company": company_names_for_context},
                    )
                latency = int((time.time() - start_time) * 1000)
                await self.audit_logger.log_query(
                    user_id=user_id,
                    query=question,
                    sql="",
                    status="success",
                    intent=ir.model_dump(),
                    latency_ms=latency,
                    assistant_reply=assistant_reply,
                )
                yield sse_event("end", {"success": True})
                return

            # ---------- 步骤 4：用历史上下文补全 IR 缺失字段 ----------
            # 例如用户上一轮问了"华为的营收"，本轮问"那利润呢？"，
            # 上下文补全会将"华为"注入到本轮 IR 的 company 过滤条件中
            ir = self.conversation_manager.enrich_ir(ir, context)

            # ---------- 步骤 5：推送意图识别结果 ----------
            # 前端收到此事件后可展示"正在查询 XX 公司的 XX 指标..."等提示
            yield sse_event(
                "intent",
                {
                    "intent_type": "query",
                    "metrics": ir.metrics,
                    "companies": ir.filters.get("company", []),
                    "years": ir.filters.get("year", []),
                },
            )

            # ---------- 步骤 6：歧义检测 ----------
            # 若公司名称匹配到多个候选（如"华为"匹配到"华为技术"和"华为投资"），
            # 中断流程，要求前端展示候选列表让用户澄清
            ambiguity = self.intent_service.detect_ambiguity(ir)
            if ambiguity:
                yield sse_event(
                    "clarification",
                    {
                        "type": "company",
                        "message": "你指的是哪个公司？",
                        "options": ambiguity,  # 候选公司列表
                    },
                )
                # 中断生成器，等待客户端带着用户的选择再次请求（含 clarification 字段）
                return

            # 若完全未匹配到公司，返回错误事件并中断
            if self.intent_service.detect_no_match(ir):
                yield sse_event(
                    "error",
                    {"code": "NO_MATCH", "message": "未匹配到公司"},
                )
                return

            # ---------- 步骤 7：构建 QueryPlan ----------
            # 将 QueryIR 转换为确定性的查询计划，包含展开后的指标列表、
            # 数据源表、分组/排序规则等完整执行信息
            # 若 query_planner 未注入，降级为从 IR 直接构建简化计划
            plan = (
                self.query_planner.plan(ir).model_dump()
                if self.query_planner
                else {
                    "model": ir.table,
                    "table": ir.table,
                    "metric_keys": ir.metrics,
                    "metrics": [],
                    "filters": ir.filters,
                    "group_by": ir.group_by,
                    "order_by": ir.order_by,
                    "limit": ir.limit,
                    "semantic_version": "legacy",
                    "post_compute": [],
                }
            )

            # ---------- 步骤 8：查询缓存 ----------
            # 基于查询计划和用户权限范围生成缓存 key，尝试命中缓存
            # 缓存可显著减少重复查询对数据库的压力
            scope = self._cache_scope(user_info)
            rows = self.query_cache.get(plan, scope) if self.query_cache else None
            cache_hit = rows is not None

            # ---------- 步骤 9：缓存未命中，生成 SQL 并执行 ----------
            sql_for_audit = ""
            if rows is None:
                if not self.sql_generator:
                    raise RuntimeError("SQLGenerator is required for query execution")

                # 9a. 从查询计划生成 SQL
                sql = self.sql_generator.generate(plan)

                # 9b. 权限注入：根据用户授权的公司列表，在 SQL 中注入 WHERE 条件
                # 确保用户只能查询到其权限范围内的数据
                sql_with_permission = sql
                allowed = scope.get("authorized_companies") or []
                if self.permission_injector and allowed and "*" not in allowed:
                    sql_with_permission = self.permission_injector.inject_company_filter(
                        sql, allowed
                    )

                # 9c. 推送 SQL 事件（调试模式下前端可展示生成的 SQL）
                yield sse_event("sql", {"sql": sql_with_permission})

                # 9d. SQL 安全校验与加固（关键字拦截、白名单、强制 LIMIT、超时注入）
                safe_sql = self.sql_guard.validate(sql_with_permission)
                sql_for_audit = safe_sql

                # 9e. 执行安全 SQL，获取查询结果
                rows = await self.query_executor.execute(db, safe_sql)
                if rows is None:
                    rows = []

                # 9f. 将查询结果写入缓存（仅缓存非空结果）
                if self.query_cache and rows:
                    self.query_cache.set(plan, rows, scope)
            else:
                # 缓存命中，跳过 SQL 生成和执行
                sql_for_audit = "[CACHE_HIT]"
                yield sse_event("sql", {"sql": "[CACHE_HIT]"})

            # 兜底：确保 rows 不为 None
            if rows is None:
                rows = []

            # ---------- 空结果快速返回 ----------
            # 查询结果为空时，推送空数据事件和提示摘要，提前结束流程
            if not rows:
                yield sse_event(
                    "data",
                    {
                        "rows": [],
                        "cache": cache_hit,
                        "meta": {"cache": cache_hit, "trace_id": trace_id},
                    },
                )
                yield sse_event("summary", {"content": "未查询到匹配数据。"})
                latency = int((time.time() - start_time) * 1000)
                await self.audit_logger.log_query(
                    user_id=user_id,
                    query=question,
                    sql=sql_for_audit,
                    status="success",
                    intent=ir.model_dump(),
                    latency_ms=latency,
                )
                yield sse_event("end", {"success": True})
                return

            # ---------- 步骤 10：计算派生指标 ----------
            # 派生指标（如毛利率、资产负债率）无法在 SQL 层直接计算，
            # 需要在结果集上基于基础指标进行后计算
            rows = self.metric_service.calc_derived_metrics(rows)

            # ---------- 步骤 11：推送数据事件 ----------
            # 将查询结果推送给前端，前端可立即渲染数据表格/图表
            yield sse_event(
                "data",
                {
                    "rows": rows,
                    "cache": cache_hit,
                    "meta": {"cache": cache_hit, "trace_id": trace_id},
                },
            )

            # ---------- 步骤 12：流式生成 LLM 文本摘要 ----------
            # 调用 LLM 对查询结果进行专业的财务分析总结，
            # 以流式方式逐块推送，前端可逐字展示（打字机效果）
            if self.llm_client:
                try:
                    async for chunk in self._stream_summary(rows, ir):
                        yield sse_event("summary", {"content": chunk})
                except Exception as llm_err:
                    # 摘要生成失败不影响主查询结果，降级为无 summary 继续返回
                    logger.warning(
                        f"[QueryService] summary generation skipped | "
                        f"trace_id={trace_id} | {llm_err}"
                    )

            # ---------- 步骤 13：更新用户对话上下文 ----------
            # 将本次查询的关键信息（公司、年份、指标）存入上下文，
            # 供后续追问时使用（如用户问"那利润呢？"可自动补全公司信息）
            await self.conversation_manager.update_context(
                user_id,
                {
                    "company": ir.filters.get("company"),
                    "year": ir.filters.get("year"),
                    "metrics": ir.metrics,
                    "table": ir.table,
                    "group_by": list(ir.group_by or []),
                },
            )

            # 计算本次请求的总耗时（毫秒）
            latency = int((time.time() - start_time) * 1000)

            # ---------- 步骤 14：记录审计日志 ----------
            # 记录完整的查询信息，用于合规审计、问题排查和使用统计
            await self.audit_logger.log_query(
                user_id=user_id,
                query=question,
                sql=sql_for_audit,
                status="success",
                intent=ir.model_dump(),
                latency_ms=latency,
            )

            # ---------- 步骤 15：发送结束事件 ----------
            # 通知前端本次请求处理完毕
            yield sse_event("end", {"success": True})

        except asyncio.CancelledError:
            # 客户端主动断开连接（如用户刷新页面），记录日志后静默结束
            # 不发送 error 事件，因为客户端已离线
            logger.warning(f"[QueryService] cancelled | trace_id={trace_id}")
            return

        except Exception as e:
            # 捕获所有未预期的异常，确保生成器不会因异常而终止
            latency = int((time.time() - start_time) * 1000)

            # 记录详细错误日志（含 trace_id 便于问题定位）
            logger.error(f"[QueryService] error | trace_id={trace_id} | {e}")

            # 记录失败审计（SQL 为空，因为可能在 SQL 生成之前就出错了）
            await self.audit_logger.log_query(
                user_id=user_info.get("user_id", "unknown"),
                query=body.get("question") or "",
                sql="",
                status="error",
                intent={},
                latency_ms=latency,
            )

            # 向客户端发送错误事件
            # 注意：不暴露异常堆栈，避免敏感信息泄露
            yield sse_event(
                "error",
                {"code": "INTERNAL_ERROR", "message": "系统处理请求时发生错误，请稍后重试"},
            )

    # =========================
    # 辅助方法
    # =========================
    @staticmethod
    def _cache_scope(user_info: Dict) -> Dict:
        """
        构建缓存作用域标识，用于缓存 key 的生成。

        不同用户角色和数据权限范围的查询结果应分开缓存，
        避免越权访问（如普通用户命中管理员的缓存，看到无权访问的数据）。

        Args:
            user_info: 用户信息字典

        Returns:
            缓存作用域字典，包含 role 和 authorized_companies
        """
        return {
            "role": user_info.get("role", "user"),
            "authorized_companies": user_info.get("authorized_companies") or [],
        }

    async def _stream_summary(self, rows, ir: QueryIR):
        """
        根据查询结果生成流式文本摘要。

        采用三阶段流水线（Phase 5 架构）：
        1. AnalysisEngine 执行确定性统计分析（排名、趋势、异常等）
        2. InsightBuilder 将分析结果转换为机器可读的洞察文本
        3. LLM 仅负责将洞察文本润色为自然流畅的财务分析话术

        这种设计确保了分析逻辑的确定性（不依赖 LLM），同时利用 LLM 的
        语言能力生成高质量的文本输出。

        若 AnalysisEngine 或 InsightBuilder 未注入，降级为直接将数据交给 LLM 总结。

        Args:
            rows: 查询结果数据列表
            ir: 查询中间表示，包含用户请求的指标列表等信息

        Yields:
            摘要文本的增量片段（每个 chunk 为一个字符串片段）
        """
        if not self.llm_client:
            return

        # 若分析引擎或洞察构建器未注入，降级为直接将数据交给 LLM
        if not self.analysis_engine or not self.insight_builder:
            prompt = f"请用简洁的语言总结以下财务数据：{rows[:5]}"
        else:
            # 阶段 1：确定性分析（统计、排名、趋势、异常检测等）
            analysis = self.analysis_engine.analyze(rows, ir.metrics)
            # 阶段 2：将分析结果转为结构化洞察文本
            insight = self.insight_builder.build(analysis)
            # 阶段 3：将洞察交给 LLM 润色为自然语言
            prompt = ANALYSIS_PROMPT.format(
                insights=json.dumps(insight, ensure_ascii=False)
            )

        # 流式调用 LLM，逐块输出摘要文本
        async for chunk in self.llm_client.generate_stream(prompt):
            yield chunk

    # =========================
    # 路由对齐方法
    # =========================
    async def ask_stream(self, payload: AskRequest) -> AsyncGenerator[str, None]:
        """
        路由层直接调用的 SSE 入口，匹配 query.py 路由中的调用方式。

        当前为简化链路实现，仅执行意图解析并推送结果。
        待所有子模块依赖注入完成后，将切换到 handle_sse_stream 的完整链路。

        Args:
            payload: 请求体对象，包含 question 等字段

        Yields:
            SSE 格式的事件字符串
        """
        trace_id = str(uuid.uuid4())
        yield sse_event("start", {"trace_id": trace_id})

        try:
            if self.intent_service:
                # 调用意图解析（简化版，无上下文）
                ir = await self.intent_service.parse_intent(
                    payload.question, {}
                )
                yield sse_event(
                    "intent",
                    {
                        "metrics": ir.metrics,
                        "companies": ir.filters.get("company", []),
                        "years": ir.filters.get("year", []),
                    },
                )
            else:
                # 意图解析模块未注入，返回提示
                yield sse_event("intent", {"message": "意图解析模块尚未接入"})

            # 完整链路预留（待所有依赖就绪后启用）
            if self.sql_generator and self.sql_guard and self.query_executor:
                pass

            yield sse_event("end", {"success": True})

        except Exception as e:
            logger.error(f"[QueryService] ask_stream error | trace_id={trace_id} | {e}")
            yield sse_event(
                "error",
                {"code": "INTERNAL_ERROR", "message": "系统处理请求时发生错误，请稍后重试"},
            )

    def get_suggestions(self) -> list[SuggestionItem]:
        """
        返回快捷问题建议列表，供前端展示"猜你想问"功能。

        Returns:
            建议问题列表，每个元素包含一个 question 字段
        """
        return [
            SuggestionItem(question="今年各公司的营收排名如何？"),
            SuggestionItem(question="华为去年的净利润是多少？"),
            SuggestionItem(question="资产负债率最高的公司是哪家？"),
            SuggestionItem(question="对比腾讯和阿里的营收趋势"),
        ]
