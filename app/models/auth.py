# -*- coding: utf-8 -*-
"""
@file: auth.py
@version: 0.1.0
@purpose: 权限接口相关模型定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from pydantic import BaseModel


class PermissionResponse(BaseModel):
    user_id: str
    role: str
    authorized_companies: list[str]
    allowed: bool
