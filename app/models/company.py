# -*- coding: utf-8 -*-
"""
@file: company.py
@version: 0.1.0
@purpose: 公司列表模型定义。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from pydantic import BaseModel


class CompanyItem(BaseModel):
    company_code: int
    company_cn_name: str
    company_en_name: str | None = None
