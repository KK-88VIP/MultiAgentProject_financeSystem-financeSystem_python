# -*- coding: utf-8 -*-
"""
@file: common.py
@version: 0.1.0
@purpose: 通用响应模型与基础 Pydantic 模型定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel
from app.core.request_context import get_request_id, get_trace_id

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None

    @classmethod
    def success(cls, data: Optional[T] = None, message: str = "success") -> "ApiResponse[T]":
        return cls(
            code=200,
            message=message,
            data=data,
            request_id=get_request_id(),
            trace_id=get_trace_id(),
        )
