# -*- coding: utf-8 -*-
"""
@file: query.py
@version: 0.2.0
@purpose: 智能问数接口，提供 SSE 问数与建议问题能力。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

"""
智能问数路由模块 (query.py)

本模块是智能问数功能的 HTTP 接口层，定义两个端点：

1. POST /api/query/ask — 智能问数主接口
   - 接收用户的自然语言问题（如"华为去年营收多少？"）
   - 通过 SSE (Server-Sent Events) 协议流式返回处理进度和结果
   - 事件流包括：start → intent → sql → data → summary → end
   - 前端可实时展示"正在解析意图"、"正在查询数据"、"正在生成分析"等状态

2. GET /api/query/suggestions — 建议问题列表
   - 返回预设的快捷问题（如"今年各公司的营收排名如何？"）
   - 供前端展示"猜你想问"功能
   - 纯静态数据，不依赖 DB/Redis，响应极快

请求头约定：
    X-User-Id:  用户唯一标识（可选，未传时默认 "anonymous"）
    X-User-Role: 用户角色（可选，默认 "user"），影响数据权限范围

SSE 协议说明：
    - 响应 Content-Type: text/event-stream
    - 每个事件格式为 "event: <事件名>\ndata: <JSON>\n\n"
    - 前端通过 EventSource 或 fetch + ReadableStream 接收
    - 事件顺序：start → intent → [clarification | sql → data → summary] → end/error
"""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_query_service
from app.db.session import get_db
from app.models.common import ApiResponse
from app.models.query import AskRequest
from app.services.permission_service import PermissionService
from app.services.query_service import QueryService as QueryServiceType

_permission_service = PermissionService()

# 创建路由组，所有接口挂载到 /api/query 前缀下
# prefix="/api/query" 由上层 app 注册时指定
router = APIRouter()


# =========================
# POST /api/query/ask — 智能问数主接口
# =========================
@router.post("/ask")
async def ask_question(
    payload: AskRequest,
    user_id: str | None = Header(None, alias="X-User-Id"),
    user_role: str = Header("user", alias="X-User-Role"),
    db: AsyncSession = Depends(get_db),
    service: QueryServiceType = Depends(get_query_service),
):
    """
    智能问数 SSE 接口，处理用户的自然语言财务数据查询请求。

    处理流程：
    1. 从请求头提取用户身份信息（user_id、role）
    2. 调用 QueryService.handle_sse_stream() 启动异步生成器
    3. 将生成器包装为 StreamingResponse 返回给前端
    4. 前端通过 SSE 协议实时接收处理进度和最终结果

    Args:
        payload: 请求体，包含以下字段（由 AskRequest 校验）：
            - question: 用户的自然语言问题（必填，如"华为去年营收多少？"）
            - clarification: 澄清选择（可选，用于歧义消解后的二次请求，
              如 {"company": ["华为技术有限公司"]}）
        user_id: 用户唯一标识，从请求头 X-User-Id 提取
                 用于对话上下文管理和审计日志
        user_role: 用户角色，从请求头 X-User-Role 提取
                   默认 "user"，影响数据权限范围（如 admin 可查所有公司）
        db: 异步数据库会话，由 FastAPI Depends(get_db) 自动注入
            请求结束时自动关闭
        service: QueryService 实例，由 Depends(get_query_service) 自动组装
            内部已注入所有子模块（意图解析、SQL 生成、安全校验等）

    Returns:
        StreamingResponse: SSE 流式响应，Content-Type 为 text/event-stream
        事件流格式示例：
            event: start
            data: {"trace_id": "xxx"}

            event: intent
            data: {"intent_type": "query", "metrics": ["revenue"], ...}

            event: data
            data: {"rows": [...], "cache": false, ...}

            event: summary
            data: {"content": "华为2025年营收..."}  (流式多块)

            event: end
            data: {"success": true}
    """
    # 组装用户信息：与 PermissionService 对齐，写入 authorized_companies 供缓存 scope / SQL 注入
    perm = _permission_service.get_user_permissions(
        user_id or "anonymous", user_role
    )
    user_info = {
        "user_id": perm.user_id,
        "role": perm.role,
        "authorized_companies": perm.authorized_companies,
    }

    # 调用 QueryService 的 SSE 主入口，获取异步生成器
    # handle_sse_stream 是一个 AsyncGenerator，内部通过 yield 逐个推送 SSE 事件
    gen = service.handle_sse_stream(payload.model_dump(), user_info, db)

    # 将异步生成器包装为 FastAPI 的 StreamingResponse
    # media_type="text/event-stream" 告知浏览器这是 SSE 流
    # 前端可通过 EventSource API 或 fetch + ReadableStream 消费
    return StreamingResponse(gen, media_type="text/event-stream")


# =========================
# GET /api/query/suggestions — 建议问题列表
# =========================
@router.get("/suggestions")
async def list_suggestions() -> ApiResponse[list[dict]]:
    """
    返回快捷问题建议列表，供前端展示"猜你想问"功能。

    纯静态数据接口，不依赖 DB/Redis/LLM，响应极快。
    直接实例化 QueryService（无需注入子模块），仅调用 get_suggestions() 方法。

    Returns:
        ApiResponse[list[dict]]: 统一响应格式，data 字段为建议问题列表
        示例：
            {
                "code": 200,
                "message": "success",
                "data": [
                    {"question": "今年各公司的营收排名如何？"},
                    {"question": "华为去年的净利润是多少？"},
                    ...
                ]
            }
    """
    # 直接实例化 QueryService（无子模块注入），仅使用其 get_suggestions 方法
    # 这是 QueryService 的一个无状态方法，不需要数据库或 LLM 支持
    return ApiResponse.success(data=[s.model_dump() for s in QueryServiceType().get_suggestions()])
