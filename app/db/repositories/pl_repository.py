# -*- coding: utf-8 -*-
"""
@file: pl_repository.py
@version: 0.1.0
@purpose: 利润表数据访问层。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from app.db.repositories.base import BaseRepository

class PLRepository(BaseRepository):
    async def get_by_companies_and_periods(self, companies: list, periods: list):
        sql = """
            SELECT * FROM com_kk_sub_pl_t 
            WHERE company_cn_name IN :companies AND period_id IN :periods
        """
        return await self.execute_query(sql, {"companies": tuple(companies), "periods": tuple(periods)})
