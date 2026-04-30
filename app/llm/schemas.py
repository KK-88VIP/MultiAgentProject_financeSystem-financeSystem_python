# -*- coding: utf-8 -*-
"""
@file: schemas.py
@version: 0.2.0
@purpose: LLM 输出结构约束定义，支持排序与分组字段扩展。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 21:08:57 +08:00
@author: aPy
"""

from pydantic import BaseModel


class SortSchema(BaseModel):
    field: str
    order: str


class IntentSchema(BaseModel):
    intent: str
    metrics: list[str]
    companies: list[str]
    periods: list[str]
    group_by: list[str] = []
    order_by: list[SortSchema] = []
