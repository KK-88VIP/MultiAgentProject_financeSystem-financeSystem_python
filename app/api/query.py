# -*- coding: utf-8 -*-
"""
@file: query.py
@version: 0.2.0
@purpose: 智能问数接口，提供 SSE 问数与建议问题能力。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_query_service
from app.db.session import get_db
from app.models.common import ApiResponse
from app.models.query import AskRequest
from app.services.query_service import QueryService as QueryServiceType

router = APIRouter()


@router.post("/ask")
async def ask_question(
    payload: AskRequest,
    user_id: str | None = Header(None, alias="X-User-Id"),
    user_role: str = Header("user", alias="X-User-Role"),
    db: AsyncSession = Depends(get_db),
    service: QueryServiceType = Depends(get_query_service),
):
    user_info = {"user_id": user_id or "anonymous", "role": user_role}
    gen = service.handle_sse_stream(payload.model_dump(), user_info, db)
    return StreamingResponse(gen, media_type="text/event-stream")


@router.get("/suggestions")
async def list_suggestions() -> ApiResponse[list[dict]]:
    """不依赖 DB/Redis，仅返回静态建议列表。"""
    return ApiResponse.success(data=[s.model_dump() for s in QueryServiceType().get_suggestions()])
