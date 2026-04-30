# -*- coding: utf-8 -*-
"""
@file: time_utils.py
@version: 0.1.0
@purpose: 时间处理工具。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from datetime import datetime


def now_iso() -> str:
    return datetime.now().isoformat()
