# -*- coding: utf-8 -*-
"""
@file: conversation_service.py
@version: 0.1.0
@purpose: 会话上下文管理服务，占位用于维护基础追问槽位。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy



多轮对话上下文管理模块 (conversation_service.py)

本模块负责管理用户在智能问数过程中的短期对话上下文，实现追问场景下的信息继承。
通过 Redis 存储用户最近一次查询涉及的公司、年份、指标等关键实体，使得系统能够
理解诸如“那华为呢？”或“那 2024 年呢？”这类省略主语的追问。

核心职责：
1. 存储和检索用户对话上下文（公司 / 年份 / 指标）。
2. 支持上下文自动过期（TTL），避免长期占用内存。
3. 提供上下文补全能力，自动填充用户当前问题中缺失的实体。
4. 与 SSE 交互流程配合，支持在澄清（clarification）中断后继续上下文保持。

设计要点：
- Redis 键格式：`conversation:{user_id}`，按用户隔离。
- 存储值：JSON 格式，包含 `company`、`year`、`metrics` 等字段。
- TTL：通过 `settings.REDIS_TTL_SECONDS` 控制，默认 30 分钟。
- 更新策略：采用合并（merge）模式，不会覆盖已有字段，除非显式覆盖。
- 补全逻辑在 `enrich_ir` 中实现，由 QueryService 调用。

注意事项：
- Redis 连接异常时降级返回空上下文，不阻塞主流程。
- 所有 Redis 操作均捕获异常并记录日志，保证服务鲁棒性。
"""

import json
from typing import Dict, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class ConversationContextManager:
    """
    对话上下文管理器（基于 Redis 异步客户端）

    使用方法：
        ctx_mgr = ConversationContextManager()
        context = await ctx_mgr.get_context(user_id)
        await ctx_mgr.update_context(user_id, {"company": "华为"})
    """

    def __init__(self):
        """
        初始化 Redis 异步客户端。

        参数 `decode_responses=True` 使返回的字符串自动解码为 Python str，
        避免手动处理 bytes。
        """
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    # =========================
    # Key 设计
    # =========================
    def _build_key(self, user_id: str) -> str:
        """
        生成 Redis 存储键。

        格式：
            conversation:{user_id}

        示例：
            conversation:user_001
        """
        return f"conversation:{user_id}"

    # =========================
    # 获取上下文
    # =========================
    async def get_context(self, user_id: str) -> Dict:
        """
        获取指定用户的当前对话上下文。

        若 Redis 中无记录或发生异常，返回空字典。

        返回格式示例：
            {
                "company": "华为技术有限公司",
                "year": 2025,
                "metrics": ["revenue"]
            }
        """
        key = self._build_key(user_id)

        try:
            data = await self.client.get(key)
            if not data:
                return {}

            return json.loads(data)

        except Exception as e:
            logger.error(f"[Conversation] get_context error: {e}")
            return {}

    # =========================
    # 更新上下文（合并模式）
    # =========================
    async def update_context(self, user_id: str, new_context: Dict):
        """
        以合并方式更新上下文，新字段会覆盖旧字段，但未指定的字段保持不变。

        适用场景：
            用户在本次查询中明确了部分实体（如年份），希望将这些信息存入上下文，
            同时保留之前已确认的公司和指标，以便后续追问继承。

        参数：
            user_id: 用户标识。
            new_context: 包含待更新字段的字典，值可为 None（此时不会覆盖已有值）。
        """
        key = self._build_key(user_id)

        try:
            # 先获取旧上下文
            old = await self.get_context(user_id)

            # 合并：仅当新字段非 None 时才覆盖
            merged = {
                **old,
                **{k: v for k, v in new_context.items() if v is not None},
            }

            await self.client.set(
                key,
                json.dumps(merged),
                ex=settings.REDIS_TTL_SECONDS,
            )

        except Exception as e:
            logger.error(f"[Conversation] update_context error: {e}")

    # =========================
    # 覆盖上下文（完全替换）
    # =========================
    async def set_context(self, user_id: str, context: Dict):
        """
        完全覆盖式设置上下文，旧数据将被丢弃。

        适用场景：
            用户发起全新查询，或主动清除历史上下文（如“新对话”命令）。

        注意：
            该方法较少使用，通常用 `update_context` 合并即可。
        """
        key = self._build_key(user_id)

        try:
            await self.client.set(
                key,
                json.dumps(context),
                ex=settings.REDIS_TTL_SECONDS,
            )
        except Exception as e:
            logger.error(f"[Conversation] set_context error: {e}")

    # =========================
    # 清空上下文
    # =========================
    async def clear_context(self, user_id: str):
        """
        手动清除指定用户的对话上下文。

        可用于用户退出登录、会话结束或测试场景。
        """
        key = self._build_key(user_id)

        try:
            await self.client.delete(key)
        except Exception as e:
            logger.error(f"[Conversation] clear_context error: {e}")

    # =========================
    # 上下文补全（核心能力）
    # =========================
    def enrich_ir(self, ir, context: Dict):
        """
        使用历史上下文补全当前查询 IR 中缺失的实体。

        补全规则：
            - 若 IR 中未指定公司，则从上下文中继承 `company` 字段。
            - 若 IR 中未指定年份，则从上下文中继承 `year` 字段。
            - 若 IR 中未指定指标，则从上下文中继承 `metrics` 字段。

        调用时机：
            在 IntentService 解析完成后、SQLBuilder 构建 SQL 之前，由 QueryService 调用。

        参数：
            ir: 当前问题的 QueryIR 对象（已包含 LLM 解析结果）。
            context: 从 Redis 获取的历史上下文字典。

        返回：
            补全后的 QueryIR 对象（原地修改并返回）。

        示例：
            用户第一问：“2025 年华为的营收是多少？”
                → 上下文存储 {"company": "华为", "year": 2025, "metrics": ["revenue"]}
            用户追问：“那净利润呢？”
                → IR 中 metrics 为 ["net_profit"]，其他为空。
                → 本方法自动补全 company 和 year。
        """
        # 补公司
        if not ir.filters.get("company") and context.get("company"):
            ir.filters["company"] = context["company"]

        # 补年份
        if not ir.filters.get("year") and context.get("year"):
            ir.filters["year"] = context["year"]

        # 补指标
        if not ir.metrics and context.get("metrics"):
            ir.metrics = context["metrics"]

        return ir
