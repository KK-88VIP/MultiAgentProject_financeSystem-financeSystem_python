# -*- coding: utf-8 -*-
"""
@file: claw_callback.py
@version: 0.1.0
@purpose: OpenClaw 回调接口预留，用于接收 Agent 调用请求。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from typing import Any

from fastapi import APIRouter

from app.models.common import ApiResponse

router = APIRouter()


@router.post("/callback", response_model=ApiResponse[dict[str, Any]])
async def claw_callback(payload: dict[str, Any]) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.success(data={"accepted": True, "payload": payload})
