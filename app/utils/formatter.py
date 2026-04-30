# -*- coding: utf-8 -*-
"""
@file: formatter.py
@version: 0.1.0
@purpose: 数据输出格式化工具。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""


def format_optional_float(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}"
