# -*- coding: utf-8 -*-
"""
@file: query_service.py
@version: 0.2.0
@purpose: 智能问数主服务，编排意图解析、澄清流程、SQL 构建、执行与 SSE 输出。
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
   - 调用 SQLBuilder 生成逻辑 SQL。
   - 调用 SQLGuard 进行安全校验和加固。
   - 调用 QueryExecutor 执行 SQL 获取原始数据。
   - 调用 MetricCalculator 计算派生指标。
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
"""

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator, Dict, Optional

from app.core.logger import get_logger
from app.services.intent_service import IntentService, QueryIR
from app.services.sql_builder import SQLBuilder
from app.security.sql_guard import SQLGuard
from app.db.query_executor import QueryExecutor
from app.services.metric_service import MetricCalculator
from app.services.conversation_service import ConversationContextManager
from app.services.audit_service import AuditService as AuditLogger  # 需实现（简单文件写入）
from app.llm.client import LLMClient
from app.llm.prompts import ANALYSIS_PROMPT
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
    将事件名和数据字典格式化为符合 SSE 规范的字符串。

    SSE 格式要求：
        - 每行以 "field: value" 形式表示。
        - 事件之间以空行分隔（即 "\\n\\n"）。
        - 数据中的换行符应被正确处理（此处使用 json.dumps 避免手动转义）。

    返回示例：
        event: intent
        data: {"metrics": ["revenue"], "companies": ["华为"]}

        （末尾有两个换行符）
    """
    # ensure_ascii=False 保证中文正常显示
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# =========================
# 主服务类
# =========================
class QueryService:
    """
    问数流程编排服务

    所有依赖均为可选（默认 None），便于路由层直接实例化。
    当各子模块就绪后，可通过构造函数注入完整依赖。
    """

    def __init__(
        self,
        intent_service: Optional[IntentService] = None,
        sql_builder: Optional[SQLBuilder] = None,
        sql_guard: Optional[SQLGuard] = None,
        query_executor: Optional[QueryExecutor] = None,
        metric_calculator: Optional[MetricCalculator] = None,
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
        self.intent_service = intent_service
        self.sql_builder = sql_builder
        self.sql_guard = sql_guard
        self.query_executor = query_executor
        self.metric_calculator = metric_calculator
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
        处理单次问数请求，通过异步生成器返回 SSE 事件流。

        参数：
            body: 已校验的请求体字典（通常来自 `AskRequest.model_dump()`）。
            user_info: 由路由解析的用户信息字典，至少包含 user_id、role。
            db: 异步数据库会话，由 get_db 依赖提供。

        生成器产出：
            符合 SSE 格式的字符串片段，每次 yield 发送一个完整事件。

        异常处理：
            所有异常均在内部捕获，通过 `error` 事件返回，不会导致生成器异常终止。
        """

        # 生成全局唯一的追踪 ID，贯穿日志和审计
        trace_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            question = body.get("question") or ""
            clarification = body.get("clarification") or {}

            user_id = user_info.get("user_id", "anonymous")

            # ---------- 1️⃣ 发送开始事件 ----------
            yield sse_event("start", {"trace_id": trace_id})

            # ---------- 2️⃣ 获取历史对话上下文 ----------
            context = await self.conversation_manager.get_context(user_id)

            # ---------- 3️⃣ 调用 LLM 解析意图，生成初步 IR ----------
            ir: QueryIR = await self.intent_service.parse_intent(
                question, context
            )

            # 如果请求中携带了澄清后的选择，直接覆盖 IR 中的相应字段
            if clarification:
                # clarification 预期格式：{"company": ["华为技术有限公司"]}
                ir.filters.update(clarification)

            # ---------- 3b️⃣ 闲聊：不补上下文、不查库，直接结束 ----------
            if ir.intent_type == "chitchat":
                reply = (ir.reply or "").strip() or (
                    "你好，我是财务数据智能助手，可以试试问我各公司的营收、利润或资产负债情况。"
                )
                yield sse_event(
                    "intent",
                    {
                        "intent_type": "chitchat",
                        "metrics": [],
                        "companies": [],
                        "years": [],
                        "reply": reply,
                    },
                )
                yield sse_event("summary", {"content": reply})
                latency = int((time.time() - start_time) * 1000)
                await self.audit_logger.log_query(
                    user_id=user_id,
                    query=question,
                    sql="",
                    status="success",
                    intent=ir.model_dump(),
                    latency_ms=latency,
                )
                yield sse_event("end", {"success": True})
                return

            # ---------- 4️⃣ 用历史上下文补全 IR 缺失字段 ----------
            ir = self.conversation_manager.enrich_ir(ir, context)

            # ---------- 5️⃣ 推送意图识别结果（供前端展示“正在分析...”）----------
            yield sse_event(
                "intent",
                {
                    "intent_type": "query",
                    "metrics": ir.metrics,
                    "companies": ir.filters.get("company", []),
                    "years": ir.filters.get("year", []),
                },
            )

            # ---------- 6️⃣ 歧义检测 ----------
            # 若公司匹配结果多于1个，则中断流程，要求前端澄清
            ambiguity = self.intent_service.detect_ambiguity(ir)
            if ambiguity:
                yield sse_event(
                    "clarification",
                    {
                        "type": "company",
                        "message": "你指的是哪个公司？",
                        "options": ambiguity,
                    },
                )
                return  # 中断生成器，等待客户端带着 clarification 再次请求

            # 若完全未匹配到公司，返回错误并中断
            if self.intent_service.detect_no_match(ir):
                yield sse_event(
                    "error",
                    {"code": "NO_MATCH", "message": "未匹配到公司"},
                )
                return

            # ---------- 7️⃣ 构建 QueryPlan ----------
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

            # ---------- 8️⃣ 优先走缓存 ----------
            scope = self._cache_scope(user_info)
            rows = self.query_cache.get(plan, scope) if self.query_cache else None
            cache_hit = rows is not None

            # ---------- 9️⃣ 缓存未命中：生成 SQL 并执行 ----------
            sql_for_audit = ""
            if rows is None:
                if self.sql_builder and "metric_keys" in plan:
                    sql = self.sql_builder.build_from_plan(plan)
                else:
                    sql = self.sql_builder.build(ir)

                # Phase 3: 并行 SQLGenerator 产物，做一致性观测（不影响主链路）
                if self.sql_generator:
                    try:
                        gen_sql = self.sql_generator.generate(plan)
                        if gen_sql != sql:
                            logger.info(
                                "[QueryService] SQL drift detected | trace_id=%s | builder=%s | generator=%s",
                                trace_id,
                                sql,
                                gen_sql,
                            )
                    except Exception as gen_err:
                        logger.warning("[QueryService] SQL generator failed | trace_id=%s | %s", trace_id, gen_err)

                # 可选权限注入（仅当上游提供授权公司时）
                sql_with_permission = sql
                allowed = scope.get("authorized_companies") or []
                if self.permission_injector and allowed and "*" not in allowed:
                    sql_with_permission = self.permission_injector.inject_company_filter(
                        sql, allowed
                    )

                # 调试环境下可将生成的 SQL 返回前端（便于排查）
                yield sse_event("sql", {"sql": sql_with_permission})

                # SQL 安全校验与加固
                safe_sql = self.sql_guard.validate(sql_with_permission)
                sql_for_audit = safe_sql

                rows = await self.query_executor.execute(db, safe_sql)
                if rows is None:
                    rows = []
                if self.query_cache and rows:
                    self.query_cache.set(plan, rows, scope)
            else:
                sql_for_audit = "[CACHE_HIT]"
                yield sse_event("sql", {"sql": "[CACHE_HIT]"})

            if rows is None:
                rows = []

            # 无数据：仍推送 data（rows 固定为数组），由 summary + end 表达无数据结论
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

            # ---------- 🔟 计算派生指标 ----------
            rows = self.metric_calculator.calc_derived_metrics(rows)

            # ---------- 1️⃣1️⃣ 推送数据 ----------
            yield sse_event(
                "data",
                {
                    "rows": rows,
                    "cache": cache_hit,
                    "meta": {"cache": cache_hit, "trace_id": trace_id},
                },
            )

            # ---------- 1️⃣2️⃣ 流式生成 LLM 文本摘要 ----------
            if self.llm_client:
                try:
                    async for chunk in self._stream_summary(rows, ir):
                        yield sse_event("summary", {"content": chunk})
                except Exception as llm_err:
                    # 摘要失败不影响主查询结果，降级为无 summary 继续返回 end
                    logger.warning(f"[QueryService] summary generation skipped | trace_id={trace_id} | {llm_err}")

            # ---------- 1️⃣3️⃣ 更新用户上下文（供后续追问）----------
            await self.conversation_manager.update_context(
                user_id,
                {
                    "company": ir.filters.get("company"),
                    "year": ir.filters.get("year"),
                    "metrics": ir.metrics,
                },
            )

            # 计算总耗时
            latency = int((time.time() - start_time) * 1000)

            # ---------- 1️⃣4️⃣ 记录审计日志 ----------
            await self.audit_logger.log_query(
                user_id=user_id,
                query=question,
                sql=sql_for_audit,
                status="success",
                intent=ir.model_dump(),
                latency_ms=latency,
            )

            # ---------- 1️⃣5️⃣ 成功结束 ----------
            yield sse_event("end", {"success": True})

        except asyncio.CancelledError:
            # 客户端主动断开连接，记录日志后静默结束
            logger.warning(f"[QueryService] cancelled | trace_id={trace_id}")
            return

        except Exception as e:
            latency = int((time.time() - start_time) * 1000)

            # 记录详细错误日志
            logger.error(f"[QueryService] error | trace_id={trace_id} | {e}")

            # 记录失败审计
            await self.audit_logger.log_query(
                user_id=user_info.get("user_id", "unknown"),
                query=body.get("question") or "",
                sql="",
                status="error",
                intent={},
                latency_ms=latency,
            )

            # 向客户端发送错误事件（避免泄露敏感堆栈）
            yield sse_event(
                "error",
                {"code": "INTERNAL_ERROR", "message": "系统处理请求时发生错误，请稍后重试"},
            )

    # =========================
    # LLM Summary 流式生成
    # =========================
    @staticmethod
    def _cache_scope(user_info: Dict) -> Dict:
        return {
            "role": user_info.get("role", "user"),
            "authorized_companies": user_info.get("authorized_companies") or [],
        }

    async def _stream_summary(self, rows, ir: QueryIR):
        """
        根据查询结果生成文本摘要（流式输出）。

        Phase 5:
        1) AnalysisEngine 先做确定性分析
        2) InsightBuilder 组装机器可读洞察
        3) LLM 仅负责语言表达
        """
        if not self.llm_client:
            return

        if not self.analysis_engine or not self.insight_builder:
            prompt = f"请用简洁的语言总结以下财务数据：{rows[:5]}"
        else:
            analysis = self.analysis_engine.analyze(rows, ir.metrics)
            insight = self.insight_builder.build(analysis)
            prompt = ANALYSIS_PROMPT.format(
                insights=json.dumps(insight, ensure_ascii=False)
            )

        async for chunk in self.llm_client.generate_stream(prompt):
            yield chunk

    # =========================
    # 路由对齐方法
    # =========================
    async def ask_stream(self, payload: AskRequest) -> AsyncGenerator[str, None]:
        """
        路由层直接调用的 SSE 入口（匹配 query.py 中的调用方式）。

        当前依赖未完全注入时，会走简化链路：
        - 调用 intent_service 解析意图（mock）
        - 输出 start / intent / end 事件
        待各子模块就绪后，自动切换到完整链路。
        """
        trace_id = str(uuid.uuid4())
        yield sse_event("start", {"trace_id": trace_id})

        try:
            if self.intent_service:
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
                yield sse_event("intent", {"message": "意图解析模块尚未接入"})

            # 完整链路（需要所有依赖就绪）
            if self.sql_builder and self.sql_guard and self.query_executor:
                # 后续接入完整链路时启用
                pass

            yield sse_event("end", {"success": True})

        except Exception as e:
            logger.error(f"[QueryService] ask_stream error | trace_id={trace_id} | {e}")
            yield sse_event(
                "error",
                {"code": "INTERNAL_ERROR", "message": "系统处理请求时发生错误，请稍后重试"},
            )

    def get_suggestions(self) -> list[SuggestionItem]:
        """返回快捷问题建议列表。"""
        return [
            SuggestionItem(question="今年各公司的营收排名如何？"),
            SuggestionItem(question="华为去年的净利润是多少？"),
            SuggestionItem(question="资产负债率最高的公司是哪家？"),
            SuggestionItem(question="对比腾讯和阿里的营收趋势"),
        ]