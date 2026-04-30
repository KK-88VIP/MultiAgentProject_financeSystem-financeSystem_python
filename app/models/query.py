# -*- coding: utf-8 -*-
"""
@file: query.py
@version: 0.2.0
@purpose: 智能问数 API 的请求/响应模型（与 `IntentService` 中的 QueryIR 解耦）。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-22 15:27:17 +08:00
@author: aPy
"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """POST /ask 请求体：自然语言问题及可选澄清结果。"""

    question: str = Field(..., min_length=1, description="用户自然语言问题")
    clarification: dict = Field(default_factory=dict, description="歧义澄清选项回传")


class SuggestionItem(BaseModel):
    """快捷建议问题条目。"""

    question: str = Field(..., description="建议问题文本")
