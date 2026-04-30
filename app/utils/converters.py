# -*- coding: utf-8 -*-
"""
@file: converters.py
@version: 0.1.0
@purpose: 单位转换与数值格式处理工具。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""


def yuan_to_wan(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 10000, 2)


def ratio_to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 1)
