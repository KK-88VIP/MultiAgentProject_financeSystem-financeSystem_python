# -*- coding: utf-8 -*-
"""
@file: enums.py
@version: 0.1.0
@purpose: 项目通用枚举定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from enum import Enum


class UserRole(str, Enum):
    MANAGEMENT = "management"
    FINANCE_STAFF = "finance_staff"
    NO_ROLE = "no_role"


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    RING = "ring"
    TABLE = "table"
