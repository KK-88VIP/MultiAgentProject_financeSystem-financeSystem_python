# -*- coding: utf-8 -*-
"""
@file: feishu_callback.py
@version: 0.1.0
@purpose: 飞书机器人回调接口预留，处理 challenge 校验与异步任务入口。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from typing import Any

from fastapi import APIRouter

from app.models.common import ApiResponse

router = APIRouter()


@router.post("/callback", response_model=ApiResponse[dict[str, Any]])
async def feishu_callback(payload: dict[str, Any]) -> ApiResponse[dict[str, Any]]:
    challenge = payload.get("challenge")
    if challenge:
        return ApiResponse.success(data={"challenge": challenge})
    return ApiResponse.success(data={"accepted": True})
